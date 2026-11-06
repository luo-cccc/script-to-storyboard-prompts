"""Lint generator-facing prompt text: structure, leftovers, timecodes, style, height and dialogue.

Standard library only. It checks wording that the media pilot showed to matter and facts that can
be compared mechanically. It does not judge story, camera design or how a model will render it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

DASH = r"\s*[–\-—~～至到]\s*"
NUM = r"(\d+(?:\.\d+)?)"
# A range counts as a timecode only where a time stamp is written: at a line start or after
# punctuation, and followed by punctuation. "尾音持续1到2秒" is a duration and is not checked.
RANGE = re.compile(r"(?:^|(?<=[\s，。；：、（(]))" + NUM + DASH + NUM + r"\s*秒(?=\s*[，。；：、）)\n]|$)", re.M)
SHOT = re.compile(r"^镜头([一二三四五六七八九十百\d]+)\s*\{(.*?)^\}", re.M | re.S)
ADAPTER_SHOT = re.compile(r"^镜头([一二三四五六七八九十百\d]+)\s*[（(]\s*" + NUM + DASH + NUM + r"\s*秒\s*[）)]\s*[：:]"
                          r"(.*?)(?=^镜头[一二三四五六七八九十百\d]+\s*[（(]|^声音[：:]|^声效[：:]|^【|\Z)", re.M | re.S)
QUOTE = re.compile(r"“([^”\n]+)”|「([^」\n]+)」|『([^』\n]+)』|\"([^\"\n]+)\"")
HEIGHT = re.compile(r"身高\s*(?:约|为|是)?\s*(\d{2,3})\s*(?:厘米|cm|公分)")
MASTER_LABELS = ["总时长：", "时间码均相对本段0秒。", "【角色锚定】", "【全片风格】", "【整体描述】",
                 "场景与环境：", "本段光线、色彩与环境基调：", "【禁止项】"]
SHOT_LABELS = ["时间：", "景别、机位：", "运镜及拍摄主体：", "构图：", "画面内容：", "声效："]
SHORTHAND = ["同上", "其余不变", "按前段", "见资产表", "已确认造型", "同资产", "沿用上段"]
# Archive record IDs (LOOK-1, STATE-BASE, CHAR-ZHOUWEN, EP01-SC02) mean nothing to a generator.
RECORD_ID = re.compile(r"(?<![A-Za-z0-9_])(?:(?:LOOK|STATE|CHAR|SCENE|PROP)(?:[-_][A-Z0-9]|\d)[A-Z0-9_-]*"
                       r"|EP\d+[-_]?SC\d+)(?![a-z])")
PROCESS_TITLES = ["第七步", "正式输出", "FORMAL_", "RUN_STATE", "next_required", "state_seq",
                  "prompt_version", "budget_version", "coverage_ledger"]
VIDEO_META = ["独立生成单元", "生成单元", "文件边界", "生成边界", "段界", "上一段", "前段", "下一段",
              "后段", "原台词", "原文", "剧本", "预算", "覆盖账本", "覆盖记录", "本段覆盖", "游标", "返修",
              "提示词", "上传", "绑定", "管理编号", "资产", "上文", "下文", "相位"]
# Pointers to other shots; "前镜" must not match 镜子／镜面, and 承接 only counts before 前／上／下／一段.
SHOT_POINTERS = ["上一镜", "下一镜", "前一镜", "后一镜", "前镜", "后镜", "承接"]
ASSET_META = ["上传", "绑定", "管理编号", "虚构", "提示词", "职责", "母图", "素材", "平台", "按下文", "上文", "下文",
              "人物档案", "继承ID", "身份继承", "身份定妆照", "数值不变", "适用集场", "适用场次",
              "只属于本状态", "状态时点", "状态版本", "恢复条件"]
PROCESS_NEGATION = ["复位", "重播", "重复起手", "回摆", "不提前", "预说", "重说", "第二遍"]
WORLD_DIRECTION = ["东南侧", "西南侧", "东北侧", "西北侧",
                   "东侧", "西侧", "南侧", "北侧", "东南", "西南", "东北", "西北", "北墙", "南墙",
                   "东墙", "西墙", "朝北", "朝南", "朝东", "朝西", "向北", "向南", "向东", "向西"]
DRIFT_WORDS = ("真实质感", "皮肤纹理", "毛孔")
NEGATED_REAL = re.compile(r"不(?:要|能|得)?(?:转|转为|改为|变成|是)真人")
# "不添加写实毛孔" asks for the absence, "不要失去真实质感" asks for the presence, so the verb matters.
NEGATION = re.compile(r"不(?:要|能|得|再)?(?:添加|使用|出现|有|带|留|做|画|呈现|表现|保留|显得)|不要|没有|无|勿|别|避免|禁止|去掉|去除")
LOSS = re.compile(r"(?:失去|缺少|丢失|缺乏|缺失)[^，。；：！？\n]{0,6}$")
COORDINATE = re.compile(r"^[\s和与及或]+$")  # "、" can separate a new predicate, so it resets the negation
CLAUSE_BREAK = re.compile(r"[，。；：！？\n]")
SEX_WORDS = ("女性", "男性", "女孩", "男孩", "女人", "男人", "少女", "少年", "女子", "男子")
ANIMATED = ("动画", "卡通", "二维", "插画", "动漫")


class Report:
    def __init__(self, kind, path):
        self.kind, self.path = kind, str(path)
        self.errors, self.warnings, self.metrics = [], [], {}

    def error(self, code, message, **where):
        self.errors.append({"code": code, "message": message, **where})

    def warn(self, code, message, **where):
        self.warnings.append({"code": code, "message": message, **where})

    def result(self, strict):
        ok = not self.errors and not (strict and self.warnings)
        return {"ok": ok, "kind": self.kind, "file": self.path, "errors": self.errors,
                "warnings": self.warnings, "metrics": self.metrics}


def sections(text):
    marks = ["【角色锚定】", "【全片风格】", "【整体描述】", "【禁止项】"]
    found = sorted((text.find(m), m) for m in marks if m in text)
    first_shot = SHOT.search(text)
    parts = {"header": text[: found[0][0]] if found else text}
    for index, (position, mark) in enumerate(found):
        end = found[index + 1][0] if index + 1 < len(found) else len(text)
        if mark == "【整体描述】" and first_shot and first_shot.start() > position:
            end = min(end, first_shot.start())
        parts[mark] = text[position + len(mark):end]
    return parts


def line_of(text, index):
    return text.count("\n", 0, index) + 1


def masked(text):
    """Blank out quoted dialogue and on-screen text so wording checks do not flag protected lines."""
    return QUOTE.sub(lambda m: m.group(0)[0] + "\u3000" * (len(m.group(0)) - 2) + m.group(0)[-1], text)


def find_terms(scan, words, pattern=None, start=0, end=None):
    """Matches of words in scan[start:end], longest first; a shorter word inside a longer match is not repeated."""
    end = len(scan) if end is None else end
    taken, found = [], []
    for word in sorted(words, key=len, reverse=True):
        for match in re.finditer(pattern(word) if pattern else re.escape(word), scan[start:end]):
            left, right = start + match.start(), start + match.end()
            if any(left < b and a < right for a, b in taken):
                continue
            taken.append((left, right))
            found.append((left, word))
    return sorted(found)


def terms(report, text, words, code, message, skip=(), pattern=None):
    """Warn on each match; matches inside a skip span are returned instead of reported."""
    label = re.match(r"【[^】\n]+】\s*\n", text)
    skipped = []
    for position, word in find_terms(masked(text), words, pattern):
        if label and position < label.end():
            continue
        if any(a <= position < b for a, b in skip):
            skipped.append(word)
            continue
        report.warn(code, message, term=word, line=line_of(text, position))
    return skipped


def drift_terms(text):
    """Photographic surface words in an animated project. A negation governs the words that follow it up to a
    contrast word, so "不添加颗粒和毛孔" hides both, while "不要失去真实质感" still counts."""
    scan = NEGATED_REAL.sub("", masked(text))
    found = []
    for clause in CLAUSE_BREAK.split(scan):
        hits = sorted((match.start(), word) for word in (*DRIFT_WORDS, "真人")
                      for match in re.finditer(re.escape(word), clause))
        previous, negated = 0, False
        for position, word in hits:
            if position < 0:
                continue
            lead = clause[previous:position]
            if re.search(r"[但而却]", lead):
                negated = False
            if NEGATION.search(lead):
                negated = not LOSS.search(lead)
            elif lead.strip() and not COORDINATE.match(lead):
                negated = False
            if not negated:
                found.append(word)
            previous = position + len(word)
    return list(dict.fromkeys(found))


def common(report, text):
    scan = masked(text)
    for match in re.finditer(r"\[[^\]\n]*[\u4e00-\u9fff][^\]\n]*\]", text):
        report.error("TEMPLATE_PLACEHOLDER", "Bracketed template instruction left in the prompt",
                     line=line_of(text, match.start()), text=match.group(0)[:40])
    for marker in ("【完整视频模板开始】", "【完整视频模板结束】"):
        if marker in text:
            report.error("TEMPLATE_MARKER", "Template boundary marker left in the prompt", term=marker)
    for word in SHORTHAND:
        if word in scan:
            report.error("SHORTHAND", "Shorthand replaces content that must be written out", term=word,
                         line=line_of(text, scan.find(word)))
    for match in re.finditer(r"(?<![\u4e00-\u9fff])略(?![\u4e00-\u9fff])", scan):
        report.error("SHORTHAND", "Standalone 略 replaces content", line=line_of(text, match.start()))
    for word in PROCESS_TITLES:
        if word in scan:
            report.error("STATE_LEAK", "Process title or state key inside generator-facing text", term=word,
                         line=line_of(text, scan.find(word)))
    for match in RECORD_ID.finditer(scan):
        report.error("RECORD_ID", "Archive record ID inside generator-facing text; write out the look, state or "
                     "reference it stands for", term=match.group(0), line=line_of(text, match.start()))
    report.metrics["chars"] = len(text)


def style_text(state):
    value = state.get("visual_style")
    if isinstance(value, dict):
        value = value.get("text") or value.get("full_text")
    return value if isinstance(value, str) and value not in ("UNSET", "NONE", "") else None


def profiles(state):
    raw = state.get("character_profiles") or []
    items = raw.values() if isinstance(raw, dict) else raw
    return [p for p in items if isinstance(p, dict) and (p.get("name") or p.get("display_name")) and p.get("height_cm")]


def check_heights(report, anchor_text, state):
    blocks = [b.strip() for b in re.split(r"\n\s*\n", anchor_text) if b.strip()]
    for profile in profiles(state):
        name = profile.get("name") or profile.get("display_name")
        paragraph = None
        for index, block in enumerate(blocks):
            if block.splitlines()[0].strip() == name:
                rest = "\n".join(block.splitlines()[1:]).strip()
                paragraph = rest or (blocks[index + 1] if index + 1 < len(blocks) else "")
                break
            if block.startswith(name):
                paragraph = block
                break
        if paragraph is None:
            continue
        heights = {int(h) for h in HEIGHT.findall(paragraph)}
        if int(profile["height_cm"]) not in heights:
            report.error("HEIGHT_MISSING", f"{name} anchor lacks the profile height {profile['height_cm']}厘米")
        for height in sorted(heights - {int(profile["height_cm"])}):
            report.error("HEIGHT_MISMATCH", f"{name} anchor states {height}厘米, profile has {profile['height_cm']}")


def load_checks():
    spec = importlib.util.spec_from_file_location("storyboard_checks", Path(__file__).with_name("storyboard_checks.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def quotes_in(text):
    return [next(group for group in match if group) for match in QUOTE.findall(text)]


def source_quotes(source_path, state=None, formal_id=None, lines=None):
    """Return (required, partial, unchecked) quotes for the source lines this segment covers.

    unchecked lists chains (or the explicit line range) whose dialogue could not be checked:
    no source_lines recorded, or no quoted text on those lines.
    """
    source_lines = Path(source_path).read_text(encoding="utf-8-sig").splitlines()

    def quotes_for(numbers):
        found = []
        for number in numbers:
            if 1 <= number <= len(source_lines):
                found.extend(quotes_in(source_lines[number - 1]))
        return found

    if lines:
        found = quotes_for(lines)
        return found, [], [] if found else [f"lines {lines[0]}-{lines[-1]}: no quoted text"]
    checks = load_checks()
    index = checks.SourceIndex(state["chain_registry"], state["source_script_ref"]["version"],
                               [v.get("version") if isinstance(v, dict) else v
                                for v in state["source_script_ref"].get("previous_versions", [])])
    plan = next((p for p in state["segment_plan"] if p["formal_id"] == formal_id), None)
    if plan is None:
        raise SystemExit(f"{formal_id} has no segment_plan entry")
    start, end = index.interval(plan, "segment_plan")
    required, partial, unchecked = [], [], []
    for left, right, chain in index.ranges:
        if left < end and right > start:
            numbers = chain.get("source_lines") or []
            if not numbers:
                unchecked.append(f"{chain['id']}: no source_lines")
            (required if start <= left and right <= end else partial).extend(quotes_for(numbers))
    return required, partial, unchecked


class Shot:
    def __init__(self, name, start, end, body_start, start_s, stop_s):
        self.name, self.start, self.end, self.body_start = name, start, end, body_start
        self.start_s, self.stop_s = start_s, stop_s


def parse_shots(text):
    """Master blocks `镜头一 {…}` with a 时间： line, and adapter headings `镜头一（0–3秒）：…`."""
    shots = []
    for match in SHOT.finditer(text):
        body = match.group(2)
        when = re.search(r"时间：\s*" + NUM + DASH + NUM + r"\s*秒", body)
        start_s = float(when.group(1)) if when else None
        stop_s = float(when.group(2)) if when else None
        body_start = match.start(2) + (when.end() if when else 0)
        shots.append(Shot(match.group(1), match.start(), match.end(), body_start, start_s, stop_s))
    if shots:
        return shots
    for match in ADAPTER_SHOT.finditer(text):
        shots.append(Shot(match.group(1), match.start(), match.end(), match.start(4),
                          float(match.group(2)), float(match.group(3))))
    return shots


def lint_master(report, text, state, budget, quotes, partial, max_chars, adapter, mapped=False, unchecked=()):
    common(report, text)
    parts = sections(text)
    shots = parse_shots(text)
    if not adapter:
        if not text.startswith("场《"):
            report.error("START", "Copyable master text must start with 场《…》·段《…》")
        for label in MASTER_LABELS:
            if label not in text:
                report.error("MISSING_LABEL", "Required template label is missing", term=label)
        if "开场状态与本段范围：" not in text and "本段为独立生成单元：" not in text:
            report.error("MISSING_LABEL", "Opening-state section is missing", term="开场状态与本段范围：")
        if "本段为独立生成单元：" in text:
            report.warn("LEGACY_LABEL", "Rename 本段为独立生成单元： to 开场状态与本段范围：")
        if not shots:
            report.error("NO_SHOTS", "No 镜头…{ } blocks found")
        for shot in shots:
            for label in SHOT_LABELS:
                if label not in text[shot.start:shot.end]:
                    report.error("MISSING_LABEL", f"镜头{shot.name} lacks {label}", term=label)
    elif not shots:
        report.warn("NO_SHOTS_PARSED", "No 镜头X（a–b秒）： headings found; time, direction and per-shot checks did not run")
    # The confirmed style block is copied verbatim from the user's decision, so wording found there is
    # listed for a style revision instead of failing --strict on text the prompt may not change.
    style, skip = style_text(state) if state is not None else None, []
    if style and "【全片风格】" in parts:
        begin = text.find("【全片风格】") + len("【全片风格】")
        if re.sub(r"\s+", "", parts["【全片风格】"]) == re.sub(r"\s+", "", style):
            skip.append((begin, begin + len(parts["【全片风格】"])))
    confirmed = terms(report, text, VIDEO_META, "META_LANGUAGE",
                      "Production wording a video model cannot act on; describe the visible state instead", skip)
    confirmed += terms(report, text, SHOT_POINTERS, "META_LANGUAGE",
                       "Refers to another shot the model cannot see; describe this shot's own start state", skip,
                       lambda word: (r"承接(?!(?:上一镜|下一镜|前一镜|后一镜|前镜|后镜|上一段|下一段|前段|后段))"
                                     r"(?=(?:前|上|下)(?:一)?(?:个)?(?:段|场|动作|镜头|画面|过程))")
                       if word == "承接" else re.escape(word) + r"(?![子面片框])")
    confirmed += terms(report, text, PROCESS_NEGATION, "PROCESS_NEGATION",
                       "Names an unwanted process; state the intended continuous action instead", skip)
    if confirmed:
        report.metrics["confirmed_style_terms"] = confirmed
    if style and any(word in style for word in ANIMATED):
        # The adapter is the text the video model actually receives, so it carries the same drift risk as
        # asset prompts. Confirmed style wording is the user's decision, not the executor's choice.
        body = text
        for begin, end in reversed(skip):
            body = body[:begin] + " " * (end - begin) + body[end:]
        drift = drift_terms(body)
        if drift:
            report.warn("STYLE_DRIFT_RISK", "Photographic wording in an animated project pulled renders toward photoreal "
                        "in the pilot; describe the medium's own surface treatment", terms=drift)
    scan = masked(text)
    for shot in shots:
        for position, word in find_terms(scan, WORLD_DIRECTION, lambda w: re.escape(w) + r"(?!亚|欧)",
                                         shot.start, shot.end):
            report.warn("WORLD_DIRECTION", "Compass direction inside a shot; use screen-relative position",
                        term=word, line=line_of(text, position))
    header_end = min([shots[0].start] if shots else [len(text)])
    total = re.search(r"总时长：\s*" + NUM + r"\s*秒", text) or re.search(r"，\s*" + NUM + r"\s*秒(?=[，。\n])", text[:header_end])
    timeline, cursor = [], 0.0
    for shot in shots:
        if shot.start_s is None:
            report.error("SHOT_TIME", f"镜头{shot.name} lacks a parsable 时间：a–b秒 line")
            continue
        start, stop = shot.start_s, shot.stop_s
        if abs(start - cursor) > 1e-6 or stop <= start:
            report.error("SHOT_TIME", f"镜头{shot.name} {start:g}–{stop:g}秒 does not continue from {cursor:g}秒")
        for inner in RANGE.finditer(text, shot.body_start, shot.end):
            a, b = float(inner.group(1)), float(inner.group(2))
            if a < start - 1e-6 or b > stop + 1e-6:
                report.error("INNER_TIME", f"镜头{shot.name} mentions {a:g}–{b:g}秒 outside {start:g}–{stop:g}秒",
                             line=line_of(text, inner.start()))
        timeline.append((start, stop))
        cursor = stop
    if total and timeline and abs(float(total.group(1)) - cursor) > 1e-6:
        report.error("TOTAL_TIME", f"总时长 {total.group(1)}秒 differs from last shot end {cursor:g}秒")
    report.metrics["shots"] = len(timeline)
    if budget is not None:
        budget_shots = [(float(s["start_s"]), float(s["end_s"])) for s in budget.get("shots", [])]
        if budget_shots != timeline:
            report.error("BUDGET_TIMELINE", f"Shot timeline {timeline} differs from budget {budget_shots}")
        if total and abs(float(total.group(1)) - float(budget.get("duration_s", -1))) > 1e-6:
            report.error("BUDGET_TOTAL", "总时长 differs from budget duration_s")
    if state is not None:
        block = parts.get("【全片风格】")
        if style and block is not None and not adapter:
            if re.sub(r"\s+", "", block) != re.sub(r"\s+", "", style):
                report.error("STYLE_MISMATCH", "【全片风格】 differs from the confirmed visual_style text")
        aspect = state.get("video_aspect_ratio")
        if isinstance(aspect, str) and aspect not in ("UNSET", "") and aspect not in parts["header"]:
            report.error("ASPECT_MISSING", f"Header lacks the confirmed aspect ratio {aspect}")
        if "【角色锚定】" in parts:
            check_heights(report, parts["【角色锚定】"], state)
    master_quotes = quotes_in(text)
    for item in unchecked:
        report.warn("DIALOGUE_UNCHECKED", "Original lines could not be checked; record chain source_lines and quote "
                    "dialogue in the source", scope=item)
    for quote in quotes:
        if quote not in master_quotes:
            report.error("DIALOGUE_MISSING", "Original line is not present verbatim", quote=quote)
    allowed = set(quotes) | set(partial)
    if mapped:
        for quote in master_quotes:
            if quote not in allowed:
                report.warn("DIALOGUE_UNMAPPED", "Quoted text is not one of this segment's source lines; a model with "
                            "native audio may read quoted text as speech, so quote only dialogue and on-screen text",
                            quote=quote)
    for quote in partial:
        report.warn("DIALOGUE_PARTIAL_CHAIN", "Line belongs to a partly covered chain; check its segment by speech_id",
                    quote=quote)
    report.metrics["dialogue_required"] = len(quotes)
    report.metrics.update({f"chars{key}": len(value) for key, value in parts.items() if key.startswith("【")})
    if max_chars and len(text) > max_chars:
        report.error("LENGTH", f"{len(text)} characters exceed the stated limit {max_chars}")


def lint_asset(report, text, state):
    common(report, text)
    terms(report, text, ASSET_META, "META_LANGUAGE",
          "Production wording an image model cannot act on; describe the visible content instead")
    if "人物" in text[:40]:
        if not any(word in text for word in SEX_WORDS):
            report.warn("IDENTITY_SEX_MISSING", "Character prompt does not state the character's sex; a separate "
                        "generation may change it (pilot IMG-02 rendered a man)")
        if not re.search(r"\d{1,3}\s*岁", text):
            report.warn("IDENTITY_AGE_MISSING", "Character prompt does not state an age")
    if state is not None:
        style = style_text(state) or ""
        drift = drift_terms(text)
        if any(word in style for word in ANIMATED) and drift:
            report.warn("STYLE_DRIFT_RISK", "Photographic wording in an animated project pulled renders toward photoreal "
                        "in the pilot; describe the medium's own surface treatment", terms=drift)
        for profile in profiles(state):
            name = profile.get("name") or profile.get("display_name")
            if name in text:
                heights = {int(h) for h in HEIGHT.findall(text)}
                if heights and int(profile["height_cm"]) not in heights:
                    report.error("HEIGHT_MISMATCH", f"{name} height differs from profile {profile['height_cm']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=("master", "adapter", "asset"))
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--budget", type=Path)
    parser.add_argument("--source", type=Path, help="Source script for verbatim dialogue checks")
    parser.add_argument("--formal-id", help="Use segment_plan and chain source_lines to pick the source lines")
    parser.add_argument("--lines", help="Explicit 1-based source lines, e.g. 7 or 5-8")
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    args = parser.parse_args()
    # JSON goes out as UTF-8 even under `python -I`, which ignores PYTHONIOENCODING on Windows pipes.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    text = args.prompt.read_text(encoding="utf-8-sig").strip()
    checks = load_checks()
    try:
        state = checks.load_json(args.state) if args.state else None
        budget = checks.load_json(args.budget) if args.budget else None
    except checks.CheckError as exc:
        print(json.dumps({"ok": False, "errors": [exc.detail]}, ensure_ascii=False, indent=2))
        return 2
    report = Report(args.kind, args.prompt)
    if args.kind == "asset":
        lint_asset(report, text, state)
    else:
        quotes, partial, unchecked = [], [], []
        mapped = bool(args.source and (args.lines or (args.formal_id and state)))
        if mapped:
            numbers = None
            if args.lines:
                first, last = (re.split(r"\s*[-–—~～至到]\s*", args.lines.strip()) + [""])[:2]
                numbers = list(range(int(first), int(last or first) + 1))
            quotes, partial, unchecked = source_quotes(args.source, state, args.formal_id, numbers)
        lint_master(report, text, state, budget, quotes, partial, args.max_chars, args.kind == "adapter", mapped,
                    unchecked)
    result = report.result(args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
