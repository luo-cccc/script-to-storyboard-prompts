"""Build a clean installable copy of the skill: runtime files only, with a hash manifest.

Maintainer tool (Python 3.10+, standard library). It never writes into an existing non-empty
directory. Evaluation archives, media pilot data, docs, specs, tests and maintainer scripts stay
in the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ("SKILL.md", "references", "scripts/storyboard_checks.py", "scripts/prompt_lint.py",
           "evals/scenarios.md", "evals/fixtures")
EXCLUDED = ("evals/runs", "evals/media-pilot", "docs", "specs", "tests", "README.md",
            "scripts/check_package.py", "scripts/run_checks.py", "scripts/build_package.py")


def files_under(path):
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def build(output):
    output = Path(output).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise SystemExit(f"{output} exists and is not a directory")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"{output} is not empty; choose a new directory")
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("Build outside the repository")
    copied = []
    for name in RUNTIME:
        for source in files_under(ROOT / name):
            relative = source.relative_to(ROOT)
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative.as_posix())
    outside = []
    for relative in copied:
        if not relative.endswith(".md"):
            continue
        path = output / relative
        text = path.read_text(encoding="utf-8-sig")
        for match in re.finditer(r"(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)", text):
            parsed = urlsplit(match.group(1).strip().strip("<>"))
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            if not (path.parent / unquote(parsed.path)).resolve().exists():
                outside.append(f"{relative}: {match.group(1)}")
    entry = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    version = re.search(r"技能包版本：([\d.]+)", entry)
    manifest = {
        "package": "script-to-storyboard-prompts",
        "package_version": version.group(1) if version else "UNKNOWN",
        "files": {name: {"sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
                         "bytes": (output / name).stat().st_size} for name in copied},
        "excluded_from_install": list(EXCLUDED),
        "links_to_repository_only_files": sorted(outside),
    }
    (output / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True, help="New, empty directory such as ~/.agents/skills/script-to-storyboard-prompts")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    manifest = build(args.output)
    total = sum(item["bytes"] for item in manifest["files"].values())
    print(json.dumps({"ok": True, "output": str(Path(args.output).expanduser().resolve()), "files": len(manifest["files"]),
                      "bytes": total, "links_to_repository_only_files": len(manifest["links_to_repository_only_files"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
