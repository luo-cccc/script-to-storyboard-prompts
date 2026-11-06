"""Run the package and deterministic regression checks with reproducible evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def input_hashes(root: Path) -> dict[str, str]:
    paths = [root / "SKILL.md", root / "README.md", root / "evals/scenarios.md"]
    for directory in ["references", "scripts", "tests", "evals/fixtures", "evals/media-pilot", "specs", "docs"]:
        paths.extend(path for path in (root / directory).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts
                     and path.suffix in {".py", ".md", ".json", ".txt"})
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths)) if path.is_file()}


def execute(root: Path, arguments: list[str]) -> dict:
    command = [sys.executable, "-I", "-B", "-X", "utf8", *arguments]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=180)
        return {"command": ["python", "-I", "-B", "-X", "utf8", *arguments],
                "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"command": ["python", "-I", "-B", "-X", "utf8", *arguments],
                "exit_code": None, "stdout": "", "stderr": "Timed out after 180 seconds"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New JSON evidence file; existing files are never overwritten")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.output is not None and args.output.exists():
        parser.error("--output already exists; choose a new run filename")
    root = Path(__file__).resolve().parents[1]
    before = input_hashes(root)
    package = execute(root, ["scripts/check_package.py"])
    tests = execute(root, ["-m", "unittest", "discover", "-s", "tests", "-v"])
    summary = re.search(r"Ran (\d+) tests? in", tests["stderr"] + tests["stdout"])
    test_count = int(summary.group(1)) if summary else 0
    after = input_hashes(root)
    passed = package["exit_code"] == 0 and tests["exit_code"] == 0 and test_count > 0 and before == after
    report = {
        "status": "PASS" if passed else "FAIL",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "scope": "S: static package checks; D: deterministic synthetic regression. H/F/M not run by this command.",
        "test_count": test_count,
        "inputs_unchanged": before == after,
        "input_sha256": before,
        "changed_inputs": sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name)),
        "package": package,
        "tests": tests,
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
        print(json.dumps({"status": report["status"], "test_count": test_count,
                          "inputs_unchanged": before == after, "evidence": str(args.output)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
