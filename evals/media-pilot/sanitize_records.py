"""Remove provider CDN links from pilot records before publishing.

Moves the original records to records-raw/ (git-ignored) and writes copies in records/ where every
http(s) URL is replaced by "<redacted-url>". File hashes, sizes and task ids stay, so results remain
verifiable against the local media files. Run once per run directory; it refuses to overwrite.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

URL = re.compile(r"https?://[^\s\"']+")


def scrub(value):
    if isinstance(value, str):
        return URL.sub("<redacted-url>", value)
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run = Path(args.run_dir).resolve()
    records, raw = run / "records", run / "records-raw"
    if raw.exists():
        raise SystemExit(f"{raw} already exists; records were sanitized before")
    shutil.copytree(records, raw)
    count = 0
    for path in sorted(records.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        count += len(URL.findall(text))
        path.write_text(json.dumps(scrub(json.loads(text)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    left = sum(len(URL.findall(p.read_text(encoding="utf-8"))) for p in records.glob("*.json"))
    print(json.dumps({"records": len(list(records.glob("*.json"))), "urls_redacted": count, "urls_left": left,
                      "raw_copy": str(raw)}, ensure_ascii=False))
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
