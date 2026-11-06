"""Media pilot harness for apimart.ai, standard library only.

Submits image and video generation tasks, polls them, downloads results and
writes one JSON record per task. Credentials come from an env file outside the
repository (default ~/.config/storyboard-pilot/apimart.env) or from environment
variables; they are never written to records or printed.

This is a maintainer test tool. It is not part of the installed skill package
and must only be run when a user has explicitly authorized paid generation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_ENV = Path.home() / ".config" / "storyboard-pilot" / "apimart.env"
USER_AGENT = "storyboard-media-pilot/0.5"
TERMINAL = {"completed", "failed", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_env(path):
    values = {}
    env_path = Path(path)
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    for key in ("APIMART_BASE_URL", "APIMART_API_KEY", "APIMART_IMAGE_MODEL", "APIMART_VIDEO_MODEL"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    if not values.get("APIMART_API_KEY"):
        raise SystemExit("APIMART_API_KEY is not configured")
    values.setdefault("APIMART_BASE_URL", "https://api.apimart.ai/v1")
    return values


class Client:
    def __init__(self, env):
        self.base = env["APIMART_BASE_URL"].rstrip("/")
        self._key = env["APIMART_API_KEY"]

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self._key, "<redacted>")
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value

    def call(self, method, path, body=None, raw=None, content_type=None, timeout=120):
        headers = {"Authorization": "Bearer " + self._key, "User-Agent": USER_AGENT,
                   "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif raw is not None:
            data = raw
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", "replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            status = exc.code
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return 0, {"transport_error": str(exc)}
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {"raw": text[:2000]}
        return status, self.redact(payload)

    def upload(self, file_path):
        path = Path(file_path)
        boundary = "----pilot" + uuid.uuid4().hex
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{path.name}\"\r\nContent-Type: {content_type}\r\n\r\n").encode("utf-8")
        body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
        status, payload = self.call("POST", "/uploads/images", raw=body,
                                    content_type=f"multipart/form-data; boundary={boundary}")
        urls = find_urls(payload)
        if status != 200 or not urls:
            raise RuntimeError(f"upload failed: HTTP {status} {json.dumps(payload, ensure_ascii=False)[:500]}")
        return urls[0], payload


def find_urls(value):
    found = []
    if isinstance(value, str):
        if re.match(r"https?://", value):
            found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(find_urls(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(find_urls(item))
    return found


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def media_meta(path):
    meta = {}
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        try:
            from PIL import Image
            with Image.open(path) as image:
                meta.update(width=image.width, height=image.height, mode=image.mode)
        except Exception as exc:  # metadata is optional evidence
            meta["meta_error"] = str(exc)
    elif shutil.which("ffprobe"):
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                 "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels,duration",
                                 "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8")
        if result.returncode == 0:
            meta["ffprobe"] = json.loads(result.stdout)
        else:
            meta["meta_error"] = result.stderr[:500]
    return meta


def resolve_inputs(client, run_dir, specs):
    """specs: list of 'role=path_or_url'. Local files are uploaded (72 h URLs)."""
    inputs = []
    for spec in specs:
        role, _, target = spec.partition("=")
        record = {"role": role}
        if re.match(r"https?://", target):
            record["url"] = target
        else:
            path = Path(target).resolve()
            record.update(local_file=os.path.relpath(path, run_dir), sha256=sha256_file(path))
            record["url"], _ = client.upload(path)
            record["uploaded_at"] = now()
        inputs.append(record)
    return inputs


def submit(args):
    env = load_env(args.env_file)
    client = Client(env)
    run_dir = Path(args.run_dir).resolve()
    record_path = run_dir / "records" / f"{args.id}.json"
    if record_path.exists():
        raise SystemExit(f"record {args.id} already exists; use a new id")
    prompt_path = Path(args.prompt_file).resolve()
    prompt = prompt_path.read_text(encoding="utf-8-sig").strip()
    inputs = resolve_inputs(client, run_dir, args.input or [])
    if args.kind == "image":
        model = args.model or env.get("APIMART_IMAGE_MODEL", "gpt-image-2")
        body = {"model": model, "prompt": prompt, "n": 1, "size": args.size, "resolution": args.resolution}
        if inputs:
            body["image_urls"] = [item["url"] for item in inputs]
        endpoint = "/images/generations"
    else:
        model = args.model or env.get("APIMART_VIDEO_MODEL", "wan3.0-video")
        body = {"model": model, "prompt": prompt, "resolution": args.resolution, "size": args.size,
                "duration": args.duration, "audio": not args.no_audio, "watermark": False}
        if args.seed is not None:
            body["seed"] = args.seed
        if inputs:
            body["image_with_roles"] = [{"url": item["url"], "role": item["role"]} for item in inputs]
        endpoint = "/videos/generations"
    attempts = []
    status, payload = client.call("POST", endpoint, body)
    attempts.append({"model": body["model"], "http_status": status, "response": payload})
    if status != 200 and args.fallback_model:
        body["model"] = args.fallback_model
        status, payload = client.call("POST", endpoint, body)
        attempts.append({"model": body["model"], "http_status": status, "response": payload})
    task_id = None
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        task_id = data[0].get("task_id")
    logged_body = {k: v for k, v in body.items() if k != "prompt"}
    if "image_urls" in logged_body or "image_with_roles" in logged_body:
        logged_body.pop("image_urls", None)
        logged_body.pop("image_with_roles", None)
    record = {
        "id": args.id, "kind": args.kind, "purpose": args.purpose, "round": args.round,
        "endpoint": endpoint, "model_used": body["model"], "parameters": logged_body,
        "prompt_file": os.path.relpath(prompt_path, run_dir), "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_chars": len(prompt), "inputs": inputs, "submitted_at": now(), "submit_attempts": attempts,
        "task_id": task_id, "status": "submitted" if task_id else "submit_failed", "polls": 0,
    }
    write_json(record_path, record)
    print(json.dumps({"id": args.id, "status": record["status"], "task_id": task_id,
                      "model": body["model"], "http_status": status}, ensure_ascii=False))
    return 0 if task_id else 1


def collect(args):
    env = load_env(args.env_file)
    client = Client(env)
    run_dir = Path(args.run_dir).resolve()
    paths = sorted((run_dir / "records").glob("*.json"))
    if args.ids:
        wanted = set(args.ids)
        paths = [p for p in paths if p.stem in wanted]
    deadline = time.time() + args.timeout
    pending = [p for p in paths if json.loads(p.read_text(encoding="utf-8"))["status"] not in TERMINAL | {"submit_failed"}]
    while pending and time.time() < deadline:
        for path in list(pending):
            record = json.loads(path.read_text(encoding="utf-8"))
            status, payload = client.call("GET", f"/tasks/{record['task_id']}?language=en")
            record["polls"] += 1
            data = payload.get("data") if isinstance(payload, dict) else None
            if status != 200 or not isinstance(data, dict):
                record["last_poll_error"] = {"http_status": status, "response": payload}
                write_json(path, record)
                continue
            record["status"] = data.get("status", record["status"])
            record["progress"] = data.get("progress")
            if record["status"] in TERMINAL:
                record["finished_at"] = now()
                record["task"] = {k: data.get(k) for k in ("cost", "credits_cost", "created", "completed",
                                                          "estimated_time", "actual_time", "error", "fail_reason")
                                  if k in data}
                record["result_raw"] = data.get("result")
                record["outputs"] = []
                ext_default = ".png" if record["kind"] == "image" else ".mp4"
                for index, url in enumerate(dict.fromkeys(find_urls(data.get("result")))):
                    suffix = Path(url.split("?")[0]).suffix.lower()
                    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"):
                        suffix = ext_default
                    target = run_dir / "media" / f"{record['id']}-{index + 1}{suffix}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(request, timeout=300) as response, open(target, "wb") as handle:
                        shutil.copyfileobj(response, handle)
                    record["outputs"].append({"url": url, "file": os.path.relpath(target, run_dir),
                                              "sha256": sha256_file(target), "bytes": target.stat().st_size,
                                              "meta": media_meta(target)})
                pending.remove(path)
                print(json.dumps({"id": record["id"], "status": record["status"], "task": record["task"],
                                  "outputs": [o["file"] for o in record["outputs"]]}, ensure_ascii=False))
            write_json(path, record)
        if pending:
            time.sleep(args.interval)
    for path in pending:
        print(json.dumps({"id": path.stem, "status": "still_pending"}))
    return 0 if not pending else 3


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=os.environ.get("APIMART_ENV_FILE", DEFAULT_ENV))
    parser.add_argument("--run-dir", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    for kind in ("image", "video"):
        p = sub.add_parser(kind)
        p.add_argument("--id", required=True)
        p.add_argument("--purpose", required=True)
        p.add_argument("--round", default="images" if kind == "image" else None)
        p.add_argument("--prompt-file", required=True)
        p.add_argument("--model")
        p.add_argument("--fallback-model")
        p.add_argument("--size", default="16:9")
        p.add_argument("--resolution", default="2k" if kind == "image" else "720P")
        p.add_argument("--input", action="append", help="role=path_or_url; local files are uploaded")
        if kind == "video":
            p.add_argument("--duration", type=int, required=True)
            p.add_argument("--seed", type=int)
            p.add_argument("--no-audio", action="store_true")
        p.set_defaults(func=submit, kind=kind)
    p = sub.add_parser("collect")
    p.add_argument("--ids", nargs="*")
    p.add_argument("--interval", type=float, default=8)
    p.add_argument("--timeout", type=float, default=1500)
    p.set_defaults(func=collect)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
