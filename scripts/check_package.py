"""Check the skill package's portable, static contracts (Python 3.10+)."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


PACKAGE_VERSION = "0.5.0"
STATE_VERSION = "1.9"
WORKFLOW_SCHEMA = "SINGLE_TEXT_CONFIRMED_ASSET_STAGES_V4"
SOURCE_SHA256 = "ed1d533c3019d7048a602887b523967d2312dd2cc6a23fe9ac8891bf91d5defe"
EXPECTED_CASES = {f"G{group:02d}-{case:02d}" for group, count in enumerate(
    [4, 2, 4, 1, 5, 2, 3, 7, 4, 4, 9, 7, 10, 10], 1
) for case in range(1, count + 1)} | {f"T{group:02d}-{case:02d}" for group in range(1, 5) for case in range(1, 3)}
REQUIRED = (
    "SKILL.md", "README.md", "references/asset-templates.md",
    "references/camera-reference.md", "references/model-adaptation.md",
    "references/shot-writing.md", "references/state-and-revision.md",
    "references/timing.md", "references/video-template.md", "references/validation.md",
    "references/transitions.md", "references/examples.md",
    "scripts/storyboard_checks.py", "scripts/prompt_lint.py", "scripts/build_package.py",
    "tests/test_state_budget.py", "tests/test_gates_and_tools.py",
    "evals/scenarios.md", "evals/fixtures/state-budget", "evals/media-pilot/apimart_pilot.py",
    "specs/script-to-storyboard-prompts-v1.8.txt",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def anchors(text: str) -> tuple[set[str], list[str]]:
    explicit = re.findall(r"<a\s+(?:id|name)=[\"']([^\"']+)", text)
    result = set(explicit)
    duplicates = [value for value, count in Counter(explicit).items() if count > 1]
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*$", text, re.M):
        result.add(re.sub(r"[^\w\-\s]", "", heading.lower()).replace(" ", "-"))
    return result, duplicates


def check_package(root: Path) -> dict:
    root = root.resolve()
    errors = []
    for name in REQUIRED:
        if not (root / name).exists():
            errors.append(f"Missing required path: {name}")
    documents = {}
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        try:
            documents[path] = read(path)
        except (OSError, UnicodeError) as exc:
            errors.append(f"Cannot read {relative.as_posix()}: {exc}")
    count = 0
    anchor_count = 0
    for path, text in documents.items():
        _, duplicate_ids = anchors(text)
        for value in duplicate_ids:
            errors.append(f"Duplicate explicit anchor in {path.relative_to(root)}: {value}")
        for match in re.finditer(r"(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)", text):
            raw = match.group(1).strip().strip("<>")
            parsed = urlsplit(raw)
            if parsed.scheme or parsed.netloc:
                continue
            count += 1
            location = unquote(parsed.path)
            fragment = unquote(parsed.fragment)
            target = (path.parent / location).resolve() if location else path
            line = text[:match.start()].count("\n") + 1
            if not target.exists():
                errors.append(f"Broken link {path.relative_to(root)}:{line}: {raw}")
            elif fragment and target.is_file():
                anchor_count += 1
                target_text = documents.get(target)
                if target_text is None:
                    target_text = read(target)
                if fragment not in anchors(target_text)[0]:
                    errors.append(f"Missing anchor {path.relative_to(root)}:{line}: {raw}")
    source_path = root / "specs/script-to-storyboard-prompts-v1.8.txt"
    state_path = root / "references/state-and-revision.md"
    field_count = 0
    if source_path.is_file() and state_path.is_file():
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_SHA256:
            errors.append("Historical v1.8 source bytes changed")
        source = read(source_path)
        state = read(state_path)
        blocks = [block for block in re.findall(r"```[^\n]*\n(.*?)\n```", state, re.S)
                  if re.search(r"^state_version=", block, re.M)]
        if len(blocks) != 1:
            errors.append("Expected exactly one RUN_STATE template")
        else:
            fields = re.findall(r"^([a-z][a-z0-9_]*)=", blocks[0], re.M)
            field_count = len(fields)
            original = re.findall(r"^([a-z][a-z0-9_]*)=", source, re.M)
            start = original.index("state_seq")
            if len(fields) != 75 or len(set(fields)) != 75 or fields != original[start:start + 75]:
                errors.append("RUN_STATE must retain the original 75 field names in order")
            for expected in [f"state_version={STATE_VERSION}", f"workflow_schema={WORKFLOW_SCHEMA}"]:
                if expected not in blocks[0].splitlines():
                    errors.append(f"RUN_STATE version mismatch: {expected}")
    entry = documents.get(root / "SKILL.md", "")
    if not re.match(r"\A---\s*\nname: script-to-storyboard-prompts\s*\ndescription: >", entry):
        errors.append("Skill metadata is missing or has the wrong name")
    if f"技能包版本：{PACKAGE_VERSION}" not in entry or f"版本：{STATE_VERSION}" not in entry or WORKFLOW_SCHEMA not in entry:
        errors.append("SKILL.md version declaration mismatch")
    if len(entry.splitlines()) >= 500:
        errors.append("SKILL.md exceeds the 500-line routing budget")
    cases_text = documents.get(root / "evals/scenarios.md", "")
    cases = re.findall(r"^####\s+((?:G|T)\d{2}-\d{2})\b", cases_text, re.M)
    if set(cases) != EXPECTED_CASES or len(cases) != len(set(cases)):
        errors.append(f"Case IDs differ: missing={sorted(EXPECTED_CASES - set(cases))}, unexpected={sorted(set(cases) - EXPECTED_CASES)}")
    for match in re.finditer(r"^####\s+((?:G|T)\d{2}-\d{2})\b.*?\n(.*?)(?=^#{1,4}\s|\Z)", cases_text, re.M | re.S):
        for label in ["前置条件", "用户输入", "应读资料", "预期交付", "允许状态变化", "禁止状态变化", "方法", "实际结果"]:
            if f"- {label}：" not in match.group(2):
                errors.append(f"{match.group(1)} lacks {label}")
    rules = re.findall(r"^\|\s*(R\d{2})\s*\|[^|\n]*\|([^|\n]*)\|", cases_text, re.M)
    if not rules:
        errors.append("Rule coverage index is missing from evals/scenarios.md")
    for rule, cell in rules:
        listed = re.findall(r"(?:G|T)\d{2}-\d{2}", cell)
        if not listed:
            errors.append(f"Rule {rule} lists no case")
        for case in listed:
            if case not in EXPECTED_CASES:
                errors.append(f"Rule {rule} lists unknown case {case}")
    camera = documents.get(root / "references/camera-reference.md", "")
    if "all parallel lines converge to central vanishing point" in camera:
        errors.append("Obsolete one-point perspective definition remains")
    template = documents.get(root / "references/video-template.md", "")
    if "时间码均相对本段0秒。" not in template:
        errors.append("Copyable master template lacks the segment clock declaration")
    runtime_files = [root / "SKILL.md", *sorted((root / "references").glob("*.md")),
                     *sorted((root / "scripts").glob("*.py")), root / "evals/scenarios.md"]
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in runtime_files if path.is_file()}
    return {
        "status": "FAIL" if errors else "PASS",
        "scope": "Static package contracts only; no model behavior, external capability, or media test.",
        "package_version": PACKAGE_VERSION,
        "state_version": STATE_VERSION,
        "local_links": count,
        "anchor_references": anchor_count,
        "state_fields": field_count,
        "human_case_count": len(cases),
        "rule_count": len(rules),
        "errors": errors,
        "runtime_sha256": hashes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        report = check_package(args.root)
    except (OSError, UnicodeError, ValueError) as exc:
        report = {"status": "FAIL", "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
