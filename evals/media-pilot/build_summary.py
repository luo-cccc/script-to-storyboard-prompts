"""Merge pilot task records, observations, lint results and totals into summary.json.

Reads only files inside the run directory and the archived 0.4.1 project; writes summary.json.
It also confirms that no configured API key string appears in tracked pilot files.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "evals/runs/0.4.1-user-review/workflow/project"
DEFAULT_ENV = Path.home() / ".config" / "storyboard-pilot" / "apimart.env"


def lint(prompt_file, record_id):
    if record_id.startswith("V"):
        kind = "master" if "baseline" in Path(prompt_file).name else "adapter"
        formal = "FORMAL_1" if record_id.endswith("-A") else "FORMAL_2"
        extra = ["--source", str(PROJECT / "source/source.md.txt"), "--formal-id", formal]
    else:
        kind, extra = "asset", []
    command = [sys.executable, "-I", "-B", "-X", "utf8", str(ROOT / "scripts/prompt_lint.py"), kind,
               "--prompt", str(prompt_file), "--state", str(PROJECT / "run-state.json"), *extra]
    result = json.loads(subprocess.run(command, capture_output=True, text=True, encoding="utf-8").stdout)
    counts = {}
    for item in result["errors"] + result["warnings"]:
        counts[item["code"]] = counts.get(item["code"], 0) + 1
    return {"kind": kind, "ok": result["ok"], "codes": counts, "chars": result["metrics"].get("chars")}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--env-file", default=os.environ.get("APIMART_ENV_FILE", DEFAULT_ENV))
    args = parser.parse_args()
    run = Path(args.run_dir).resolve()
    observations = {}
    for name in ("observations-images.json", "observations-videos.json"):
        observations.update(json.loads((run / name).read_text(encoding="utf-8")))
    tasks, totals = [], {"image_tasks": 0, "video_tasks": 0, "video_seconds": 0, "credits_cost": 0.0, "cost": 0.0}
    for path in sorted((run / "records").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        rid = record["id"]
        entry = {"id": rid, "kind": record["kind"], "purpose": record.get("purpose") or record.get("reason")}
        if record["kind"] in ("image", "video"):
            task = record.get("task", {})
            entry.update(round=record.get("round"), model=record["model_used"], parameters=record["parameters"],
                         prompt_file=record["prompt_file"], prompt_sha256=record["prompt_sha256"],
                         prompt_chars=record["prompt_chars"], inputs=[{k: v for k, v in i.items() if k != "url"} for i in record["inputs"]],
                         status=record["status"], seconds_to_finish=task.get("actual_time"),
                         credits_cost=task.get("credits_cost"), cost=task.get("cost"),
                         outputs=[{k: o[k] for k in ("file", "sha256", "bytes")} for o in record.get("outputs", [])],
                         lint=lint(run / record["prompt_file"], rid))
            totals[record["kind"] + "_tasks"] += 1
            totals["credits_cost"] += task.get("credits_cost") or 0
            totals["cost"] += task.get("cost") or 0
            if record["kind"] == "video":
                totals["video_seconds"] += record["parameters"]["duration"]
        else:
            entry.update(source=record["source"], operation=record["operation"], output=record["output"],
                         output_sha256=record["output_sha256"])
        entry["observation"] = observations.get(rid)
        tasks.append(entry)
    totals = {k: round(v, 6) if isinstance(v, float) else v for k, v in totals.items()}
    key = None
    env = Path(args.env_file)
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("APIMART_API_KEY="):
                key = line.split("=", 1)[1].strip()
    leaked = []
    if key:
        for path in run.rglob("*"):
            if path.is_file() and "media" not in path.parts and path.suffix in (".json", ".txt", ".md"):
                if key in path.read_text(encoding="utf-8", errors="replace"):
                    leaked.append(str(path.relative_to(run)))
    summary = {"run": run.name, "scope": "M: real media pilot on one sample story; see docs/0.5.0-媒体试点报告.md",
               "credentials_in_tracked_files": "NOT_CHECKED" if key is None else ("FOUND" if leaked else "NONE"),
               "credential_hits": leaked, "totals": totals, "tasks": tasks,
               "missing_observations": sorted(set(observations) - {t["id"] for t in tasks})}
    (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "totals": totals, "credentials": summary["credentials_in_tracked_files"],
                      "missing_observations": summary["missing_observations"]}, ensure_ascii=False))
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.exit(main())
