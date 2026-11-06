"""Validate storyboard JSON records; no creation, media, or network operations."""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid


STATE_VERSION = "1.9"
WORKFLOW_SCHEMA = "SINGLE_TEXT_CONFIRMED_ASSET_STAGES_V4"
STATE_FIELDS = """state_seq state_version workflow_schema transaction_id phase project_id
project_status project_analysis_status production_settings_status production_settings
video_aspect_ratio visual_style source_script_ref visual_reference_status visual_reference
visual_baseline project_decisions asset_status asset_substage character_asset_status
scene_asset_status prop_asset_status scene_prop_asset_status asset_queue character_assets
character_profiles scene_assets prop_assets episode_id episode_status scene_id scene_wide_status
prep_scene prep_step prep_batch prep_status last_completed_formal last_output next_required
script_cursor next_chain_unstarted chain_registry coverage_ledger prompt_versions segment_max_s
segment_delivery segment_plan budget_status budget_ref plan_ref transition_plan transition_review
characters_state viewing_state weapons_props_state environment_state ongoing_effects_state
voice_profile prop_ledger last_frame_snapshot execution_mode step_policy performance_mode
awaiting_continue step_ledger blocking_items edit_lock edit_context invalidated_from return_to
delivery_mode delivery_channel state_storage state_ref recovery_evidence""".split()
PHASES = {"PROJECT_SETUP", "ASSET_RUNNING", "EPISODE_PLANNING", "SCENE_PREP",
          "FORMAL_RUNNING", "EDIT_LOCK", "COMPLETE"}
MANUAL_SCOPE = ["source anchors and delivery references must be checked against actual content",
                "story, dependency meaning, performance, platform capability and media are not verified",
                "derive reports coverage only; the next production step still requires predecessor evidence"]
CHECK_KINDS = ("TEXT", "INPUT", "CAPABILITY", "MEDIA")
CHECK_STATUS = ("PENDING", "PASS", "FAIL", "UNKNOWN", "NOT_RUN", "NOT_APPLICABLE", "BLOCKED", "INVALID")
ASSET_KINDS = ("CHARACTER", "SCENE", "PROP")
ASSET_STATUS = ("PENDING", "IN_PROGRESS", "DONE", "REUSED", "INVALID")
OPEN_ASSET = ("PENDING", "IN_PROGRESS")
FINISHED = ("DONE", "REUSED")
REVIEW_TARGETS = {"CHARACTER_ASSET_REVIEW": ("CHARACTER",), "SCENE_PROP_ASSET_REVIEW": ("SCENE", "PROP")}
SCOPE_PATTERN = re.compile(r"EP\d+-SC\d+")


class CheckError(ValueError):
    def __init__(self, code, path, message):
        super().__init__(message)
        self.detail = {"code": code, "path": path, "message": message}


def require(condition, code, path, message):
    if not condition:
        raise CheckError(code, path, message)


def obj(value, path):
    require(isinstance(value, dict), "TYPE", path, "Expected an object")
    return value


def array(value, path):
    require(isinstance(value, list), "TYPE", path, "Expected an array")
    return value


def text(value, path):
    require(isinstance(value, str) and bool(value.strip()), "TYPE", path, "Expected nonempty text")
    return value


def number(value, path, positive=False):
    valid = type(value) in (int, float)
    try:
        valid = valid and math.isfinite(value) and (value > 0 if positive else value >= 0)
    except (OverflowError, ValueError):
        valid = False
    require(valid, "NUMBER", path, "Expected a finite positive number" if positive else "Expected a finite nonnegative number")
    return value


def integer(value, path):
    require(type(value) is int and value >= 0, "TYPE", path, "Expected a nonnegative integer")
    return value


def present(value):
    return value is not None and value not in ("", "NONE", "UNKNOWN", "UNSET")


def finite_tree(value, path="$"):
    if isinstance(value, float):
        require(math.isfinite(value), "NUMBER", path, "Non-finite JSON number")
    elif isinstance(value, dict):
        for key, item in value.items():
            finite_tree(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            finite_tree(item, f"{path}[{index}]")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_KEY", key, "Duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise CheckError("NUMBER", "$", f"Nonstandard JSON constant: {value}")


def parse_json(data):
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, CheckError):
            raise
        raise CheckError("JSON", "$", str(exc)) from exc
    finite_tree(value)
    return value


def load_json(path):
    return parse_json(Path(path).read_text(encoding="utf-8-sig"))


def formal_number(value, path):
    require(isinstance(value, str) and re.fullmatch(r"FORMAL_[1-9]\d*", value) is not None,
            "FORMAL_ID", path, "Expected FORMAL_n with positive n")
    return int(value.split("_")[1])


class SourceIndex:
    def __init__(self, chains, source_version, previous_versions=()):
        self.chains = array(chains, "chain_registry")
        self.positions = {}
        self.ranges = []
        self.start = "END"
        self.end = 0
        allowed = {source_version, *previous_versions}
        ids = set()
        for i, chain in enumerate(self.chains):
            path = f"chain_registry[{i}]"
            obj(chain, path)
            cid = text(chain.get("id"), path + ".id")
            require(cid not in ids, "DUPLICATE_CHAIN", path, "Duplicate chain id")
            ids.add(cid)
            version = text(chain.get("source_version"), path + ".source_version")
            require(version in allowed, "SOURCE_MAPPING_UNSUPPORTED", path,
                    "Use the current source version, or a declared previous version for fully delivered chains")
            for field in ("episode_id", "scene_id"):
                text(chain.get(field), path + "." + field)
            anchors = array(chain.get("anchors"), path + ".anchors")
            require(len(anchors) >= 2, "ANCHORS", path, "START and END are required")
            anchor_ids = []
            start = self.end
            for j, anchor in enumerate(anchors):
                ap = f"{path}.anchors[{j}]"
                obj(anchor, ap)
                aid = text(anchor.get("id"), ap + ".id")
                require(aid not in anchor_ids, "DUPLICATE_ANCHOR", ap, "Duplicate anchor id")
                anchor_ids.append(aid)
                loc = text(anchor.get("source_anchor"), ap + ".source_anchor")
                text(anchor.get("action_phase"), ap + ".action_phase")
                require(re.fullmatch(r"\s*(?:第)?\d+(?:\.\d+)?\s*(?:s|秒)?\s*", loc, re.I) is None,
                        "SOURCE_ANCHOR", ap, "A generation timestamp is not a source anchor")
                self.positions[(version, cid, aid)] = start + j
            require(anchor_ids[0] == "START" and anchor_ids[-1] == "END", "ANCHORS", path,
                    "Anchors must start at START and finish at END")
            self.end = start + len(anchors) - 1
            self.ranges.append((start, self.end, chain))
            if i == 0:
                self.start = {"source_version": version, "chain_id": cid, "anchor_id": "START"}

    def rank(self, cursor, path):
        if cursor == "END":
            return self.end
        obj(cursor, path)
        require(set(cursor) == {"source_version", "chain_id", "anchor_id"}, "CURSOR", path,
                "Cursor needs exactly source_version, chain_id and anchor_id")
        values = tuple(text(cursor[k], path + "." + k) for k in ("source_version", "chain_id", "anchor_id"))
        require(values in self.positions, "CURSOR", path, "Unknown source, chain or anchor")
        require(cursor["anchor_id"] != "END", "CURSOR_CANONICAL", path,
                "Normalize chain END to the next chain START or global END")
        return self.positions[values]

    def interval(self, record, path):
        start = self.rank(record.get("start_cursor"), path + ".start_cursor")
        end = self.rank(record.get("end_cursor"), path + ".end_cursor")
        require(start < end, "COVERAGE_RANGE", path, "Coverage must be a nonempty half-open interval")
        for left, right, chain in self.ranges:
            if left < end and right > start:
                for field in ("episode_id", "scene_id"):
                    require(record.get(field) == chain[field], "SCENE_SCOPE", path + "." + field,
                            "The range must belong to the declared episode and scene")
                require(record.get("source_script_version") == chain["source_version"],
                        "SOURCE_VERSION", path, "Range source version does not match registry")
        return start, end


def _text_check(checks, path):
    item = obj(obj(checks, path).get("TEXT"), path + ".TEXT")
    require(item.get("status") == "PASS", "TEXT_EVIDENCE", path, "DONE needs a recorded TEXT PASS")
    evidence = item.get("evidence")
    require(isinstance(evidence, str) and present(evidence.strip()), "TEXT_EVIDENCE", path,
            "TEXT PASS needs a nonempty evidence reference, not a placeholder or another JSON type")


def _check_records(checks, path):
    """Every recorded TEXT/INPUT/CAPABILITY/MEDIA PASS must cite its own evidence."""
    if checks is None:
        return
    obj(checks, path)
    for kind in CHECK_KINDS:
        if kind not in checks:
            continue
        item = obj(checks[kind], f"{path}.{kind}")
        status = item.get("status")
        require(status in CHECK_STATUS, "ENUM", f"{path}.{kind}.status", f"Expected one of {CHECK_STATUS}")
        if status == "PASS":
            evidence = item.get("evidence")
            require(isinstance(evidence, str) and present(evidence.strip()), "CHECK_EVIDENCE",
                    f"{path}.{kind}", f"{kind} PASS needs its own evidence reference, not only a scope description")


def _asset_units(state, scene_assets):
    units = {}
    for i, unit in enumerate(array(state["asset_queue"], "asset_queue")):
        path = f"asset_queue[{i}]"
        obj(unit, path)
        uid = text(unit.get("id"), path + ".id")
        require(uid not in units, "DUPLICATE_ASSET", path, "Duplicate asset unit id")
        require(unit.get("kind") in ASSET_KINDS, "ENUM", path + ".kind", f"Expected one of {ASSET_KINDS}")
        require(unit.get("status") in ASSET_STATUS, "ENUM", path + ".status", f"Expected one of {ASSET_STATUS}")
        needed = unit.get("needed_by", [])
        for j, scope in enumerate(array(needed, path + ".needed_by")):
            require(isinstance(scope, str) and SCOPE_PATTERN.fullmatch(scope) is not None, "SCENE_SCOPE",
                    f"{path}.needed_by[{j}]", "Use full EPxx-SCxx scene scopes")
        require(not scene_assets or bool(needed), "ASSET_SCOPE", path,
                "SCENE_ASSETS needs needed_by scopes on every asset unit")
        units[uid] = unit
    return units


def _unit_evidence(units, steps):
    """DONE asset units need their own step; REUSED units need it or the matching review step."""
    done = {s["step_id"] for s in steps if s["status"] in FINISHED}
    for uid, unit in units.items():
        if unit["status"] == "DONE":
            require(uid in done, "PREDECESSOR", f"asset_queue.{uid}", f"Asset unit {uid} is DONE without a DONE/REUSED step")
        elif unit["status"] == "REUSED":
            review = "CHARACTER_ASSET_REVIEW" if unit["kind"] == "CHARACTER" else "SCENE_PROP_ASSET_REVIEW"
            require(uid in done or review in done, "PREDECESSOR", f"asset_queue.{uid}",
                    f"Asset unit {uid} is REUSED without reuse evidence")


def _gate(state, target, phase, steps, units, plans, derived):
    """Mechanical predecessor evidence for the single current target."""
    done = {s["step_id"] for s in steps if s["status"] in FINISHED}
    scene_assets = state["step_policy"] == "SCENE_ASSETS"
    frontier = plans.get(derived["last_completed_formal"] + 1) if derived["frontier"] else None
    frontier = frontier[0] if frontier else None

    def need(condition, message):
        require(condition, "PREDECESSOR", target, message)

    def need_steps(*ids):
        missing = [step_id for step_id in ids if step_id not in done]
        need(not missing, f"Missing DONE/REUSED step_ledger evidence for {missing}")

    def open_units(kinds, scope=None):
        return [u["id"] for u in units.values() if u["kind"] in kinds and u["status"] in OPEN_ASSET
                and (scope is None or scope in u.get("needed_by", []))]

    def need_episode_plan():
        need(re.fullmatch(r"EP\d+", state["episode_id"]) is not None,
             "SCENE_ASSETS prepares assets after the episode plan; set next_required to EPxx_PLAN first")
        need_steps(state["episode_id"] + "_PLAN")

    if phase == "PROJECT_SETUP":
        return
    need(state["project_status"] == "DONE" and state["project_analysis_status"] == "DONE",
         "PROJECT_BASELINE analysis and confirmation are not DONE")
    need_steps("PROJECT_BASELINE")
    if phase == "ASSET_RUNNING":
        if target in REVIEW_TARGETS:
            pending = open_units(REVIEW_TARGETS[target])
            need(not pending, f"Deliver queued units before {target}: {pending}")
            if target == "SCENE_PROP_ASSET_REVIEW" and not scene_assets:
                need(not open_units(("CHARACTER",)) and state["character_asset_status"] == "DONE",
                     "Characters come first: finish the character step before SCENE_PROP_ASSET_REVIEW")
            return
        unit = units.get(target)
        require(unit is not None and unit["status"] in OPEN_ASSET, "UNKNOWN_TARGET", target,
                "Asset target must be an open asset_queue unit or a review target")
        require(state["asset_substage"] == unit["kind"], "PHASE", "asset_substage",
                f"Asset substage must be {unit['kind']} for {target}")
        scope = None
        if scene_assets:
            need_episode_plan()
            scope = state["episode_id"] + "-" + state["scene_id"]
            need(scope in unit.get("needed_by", []),
                 f"{target} is not needed by the scene being prepared ({scope}); under SCENE_ASSETS set "
                 "episode_id/scene_id to the scene whose assets are prepared, and prepare later scenes later")
        if unit["kind"] in ("SCENE", "PROP"):
            blocked = open_units(("CHARACTER",), scope)
            need(not blocked, f"Characters come first: {blocked}")
            need(scene_assets or state["character_asset_status"] == "DONE",
                 "Characters come first: character_asset_status is not DONE")
        if unit["kind"] == "PROP":
            blocked = open_units(("SCENE",), scope)
            need(not blocked, f"Scenes come before props: {blocked}")
        return
    if phase == "EPISODE_PLANNING":
        need(frontier is None or frontier["episode_id"] == target.split("_", 1)[0],
             f"{derived['frontier']} of {frontier and frontier['episode_id']} is planned but not delivered")
        if not scene_assets:
            need(state["asset_status"] == "DONE", "Asset steps are not DONE")
            need(not open_units(ASSET_KINDS), f"Open asset units remain: {open_units(ASSET_KINDS)}")
        return
    if phase == "COMPLETE":
        need(not open_units(ASSET_KINDS), f"Open asset units remain: {open_units(ASSET_KINDS)}")
        if not scene_assets:
            need(state["asset_status"] == "DONE", "Asset steps are not DONE")
        return
    if phase == "SCENE_PREP":
        episode, scope = target.split("-", 1)[0], target.split("_", 1)[0]
        planned = frontier and frontier["episode_id"] + "-" + frontier["scene_id"]
        need(frontier is None or planned == scope,
             f"{derived['frontier']} of {planned} is planned but not delivered; finish it before {target}")
    else:
        plan = plans.get(formal_number(target, "next_required"))
        if plan is None:
            return
        episode, scope = plan[0]["episode_id"], plan[0]["episode_id"] + "-" + plan[0]["scene_id"]
    if scene_assets:
        pending = open_units(ASSET_KINDS, scope)
        need(not pending, f"Assets needed by {scope} are not finished: {pending}")
    else:
        need(state["asset_status"] == "DONE", "Asset steps are not DONE")
        need(not open_units(ASSET_KINDS), f"Open asset units remain: {open_units(ASSET_KINDS)}")
    need_steps(episode + "_PLAN")
    if target.endswith("_BUDGET_SEGMENT"):
        need_steps(scope + "_ANALYSIS")
        need(state["scene_wide_status"] == "ESTABLISHED" and state["prep_step"] in ("ANALYSIS_DONE", "BUDGET_SEGMENT"),
             "Scene analysis is not recorded as finished in scene_wide_status/prep_step")
    elif phase == "FORMAL_RUNNING":
        need_steps(scope + "_ANALYSIS", scope + "_BUDGET_SEGMENT")
        require(scope == state["episode_id"] + "-" + state["scene_id"], "SCENE_SCOPE", target,
                "Formal target must belong to the current episode and scene")
        need(state["prep_step"] == "DONE" and state["prep_status"] == "DONE" and state["scene_wide_status"] == "ESTABLISHED",
             "Scene preparation is not DONE for the formal target")


def _inspect_state(state, compare_derived=True):
    obj(state, "$")
    finite_tree(state)
    require(set(state) == set(STATE_FIELDS), "STATE_FIELDS", "$",
            f"Missing={sorted(set(STATE_FIELDS)-set(state))}; unknown={sorted(set(state)-set(STATE_FIELDS))}")
    require(state["state_version"] == STATE_VERSION and state["workflow_schema"] == WORKFLOW_SCHEMA,
            "STATE_VERSION", "$", "Expected state 1.9 / V4; migrate with source evidence first")
    integer(state["state_seq"], "state_seq")
    integer(state["last_completed_formal"], "last_completed_formal")
    integer(state["prep_batch"], "prep_batch")
    enums = {
        "project_status": ("UNSET", "IN_PROGRESS", "DONE"),
        "project_analysis_status": ("UNSET", "IN_PROGRESS", "DONE"),
        "production_settings_status": ("UNSET", "WAIT_CONFIRM", "CONFIRMED"),
        "visual_reference_status": ("UNSET", "IMAGE_READY", "TEXT_READY"),
        "asset_status": ("UNSET", "RUNNING", "DONE"),
        "asset_substage": ("CHARACTER", "SCENE", "PROP", "COMPLETE"),
        "episode_status": ("UNSET", "IN_PROGRESS", "DONE"),
        "scene_wide_status": ("UNSET", "ESTABLISHED", "REBUILD_REQUIRED"),
        "prep_status": ("UNSET", "IN_PROGRESS", "DONE"),
        "budget_status": ("UNSET", "DRAFT", "CHECKED", "FROZEN", "INVALID"),
        "delivery_mode": ("PROMPT_CLEAN", "AUDIT"),
        "execution_mode": ("REVIEW", "BATCH_PREP"), "step_policy": ("STRICT", "SCENE_ASSETS"),
        "segment_delivery": ("ONE_AT_A_TIME",), "performance_mode": ("NORMAL", "PRECISE"),
    }
    for field in ("character_asset_status", "scene_asset_status", "prop_asset_status", "scene_prop_asset_status"):
        enums[field] = ("UNSET", "RUNNING", "DONE")
    for field, allowed in enums.items():
        require(isinstance(state[field], str) and state[field] in allowed,
                "ENUM", field, f"Expected one of {allowed}")
    require((type(state["prep_step"]) is int and state["prep_step"] == 0)
            or (isinstance(state["prep_step"], str) and state["prep_step"] in ("ANALYSIS", "ANALYSIS_DONE", "BUDGET_SEGMENT", "DONE")),
            "ENUM", "prep_step", "Invalid preparation step")
    for field in ("transaction_id", "project_id", "episode_id", "scene_id", "next_required"):
        text(state[field], field)
    require(isinstance(state["phase"], str) and state["phase"] in PHASES, "PHASE", "phase", "Unknown phase")
    require(type(state["awaiting_continue"]) is bool, "TYPE", "awaiting_continue", "Expected boolean")
    require(state["state_storage"] in ("FILE", "CONVERSATION"), "ENUM", "state_storage", "Invalid storage")
    require(state["delivery_channel"] in ("FILE", "CHAT"), "ENUM", "delivery_channel", "Invalid channel")
    source = obj(state["source_script_ref"], "source_script_ref")
    source_version = text(source.get("version"), "source_script_ref.version")
    previous_versions = []
    for i, item in enumerate(array(source.get("previous_versions", []), "source_script_ref.previous_versions")):
        value = item.get("version") if isinstance(item, dict) else item
        previous_versions.append(text(value, f"source_script_ref.previous_versions[{i}]"))
    idx = SourceIndex(state["chain_registry"], source_version, previous_versions)
    # 0.5.0 record rules (asset units, check evidence, gates) apply to full validation only, so that
    # derive, summary and commit can still read a legacy snapshot that needs migration.
    units = _asset_units(state, state["step_policy"] == "SCENE_ASSETS") if compare_derived else {}
    plans = {}
    for i, plan in enumerate(array(state["segment_plan"], "segment_plan")):
        path = f"segment_plan[{i}]"
        obj(plan, path)
        n = formal_number(plan.get("formal_id"), path)
        require(n not in plans, "DUPLICATE_PLAN", path, "Duplicate formal plan")
        interval = idx.interval(plan, path)
        plans[n] = (plan, interval)
    previous = 0
    for expected, n in enumerate(sorted(plans), 1):
        plan, (start, end) = plans[n]
        require(n == expected and start == previous, "PLAN_GAP", "segment_plan",
                "Retained plans must start at FORMAL_1 and cover adjacent source intervals")
        previous = end
    versions = {}
    request_ids = set()
    for i, prompt in enumerate(array(state["prompt_versions"], "prompt_versions")):
        path = f"prompt_versions[{i}]"
        obj(prompt, path)
        fid = prompt.get("formal_id")
        formal_number(fid, path)
        version = text(prompt.get("prompt_version"), path + ".prompt_version")
        text(prompt.get("budget_version"), path + ".budget_version")
        require(prompt.get("status") in ("DRAFT", "DONE", "INVALID"), "ENUM", path, "Invalid prompt status")
        key = (fid, version)
        require(key not in versions, "DUPLICATE_VERSION", path, "Duplicate prompt version")
        versions[key] = prompt
        for j, adapter in enumerate(array(prompt.get("adapters", []), path + ".adapters")):
            ap = f"{path}.adapters[{j}]"
            obj(adapter, ap)
            rid = text(adapter.get("request_id"), ap + ".request_id")
            require(rid not in request_ids, "DUPLICATE_REQUEST", ap, "Request id must be unique")
            request_ids.add(rid)
            require(adapter.get("lifecycle") in ("ACTIVE", "CLOSED", "CANCELLED"), "ENUM", ap, "Invalid lifecycle")
            require(adapter.get("text_status") in ("DRAFT", "CHECKED", "BLOCKED", "INVALID"), "ENUM", ap, "Invalid text status")
            require(adapter.get("input_status") in ("NOT_REQUIRED", "PENDING", "AVAILABLE", "UNKNOWN"), "ENUM", ap, "Invalid input status")
            require(adapter.get("base_prompt_version") == version, "ADAPTER_VERSION", ap, "Adapter must name its owning prompt version")
            if adapter["lifecycle"] == "CANCELLED":
                text(adapter.get("decision_ref"), ap + ".decision_ref")
            if adapter["lifecycle"] == "CLOSED":
                require(adapter["text_status"] == "CHECKED" and present(adapter.get("delivery_ref")),
                        "ADAPTER_DELIVERY", ap, "CLOSED requires checked, delivered text")
    steps = array(state["step_ledger"], "step_ledger")
    for i, step in enumerate(steps):
        obj(step, f"step_ledger[{i}]")
        text(step.get("step_id"), f"step_ledger[{i}].step_id")
        require(step.get("status") in ("IN_PROGRESS", "DONE", "REUSED", "INVALID", "CANCELLED"),
                "ENUM", f"step_ledger[{i}]", "Invalid step status")
        if step["status"] in ("DONE", "REUSED"):
            require(present(step.get("delivery_ref")), "DELIVERY", f"step_ledger[{i}]", "Completed step needs delivery evidence")
        if compare_derived and step["status"] in ("IN_PROGRESS", "DONE", "REUSED"):
            _check_records(step.get("checks"), f"step_ledger[{i}].checks")
        require(not (step["status"] == "CANCELLED" and re.fullmatch(r"FORMAL_\d+", step["step_id"])),
                "CANCEL_SCOPE", f"step_ledger[{i}]", "Cancellation cannot close a mandatory formal step")
    coverage = {}
    for i, record in enumerate(array(state["coverage_ledger"], "coverage_ledger")):
        path = f"coverage_ledger[{i}]"
        obj(record, path)
        n = formal_number(record.get("formal_id"), path)
        require(n not in coverage, "DUPLICATE_COVERAGE", path, "Only one current record per formal_id")
        require(record.get("status") in ("DONE", "INVALID"), "ENUM", path, "Coverage status must be DONE or INVALID")
        interval = idx.interval(record, path)
        require(n in plans and interval == plans[n][1], "COVERAGE_PLAN", path,
                "Current coverage must match its retained plan range")
        for field in ("prompt_version", "budget_version"):
            text(record.get(field), path + "." + field)
        if record["status"] == "DONE":
            key = (record["formal_id"], record["prompt_version"])
            require(key in versions, "PROMPT_MAPPING", path, "Missing referenced prompt version")
            prompt = versions[key]
            require(prompt["status"] == "DONE" and prompt["budget_version"] == record["budget_version"],
                    "VERSION_MAPPING", path, "Prompt or budget mapping is invalid")
            require(prompt.get("budget_status") in ("CHECKED", "FROZEN") and present(prompt.get("budget_ref")),
                    "BUDGET_EVIDENCE", path, "DONE needs a checked budget reference")
            require(present(record.get("delivery_ref")) and record.get("delivery_ref") == prompt.get("delivery_ref"),
                    "DELIVERY", path, "Coverage and prompt need the same delivery reference")
            _text_check(record.get("checks"), path + ".checks")
            if compare_derived:
                _check_records(record.get("checks"), path + ".checks")
            require(any(step["step_id"] == record["formal_id"] and step.get("prompt_version") == record["prompt_version"]
                        and step["status"] in ("DONE", "REUSED") for step in steps),
                    "STEP_EVIDENCE", path, "Missing matching completed formal step")
            require(present(record.get("end_state")), "END_STATE", path, "DONE needs an end-state record")
        coverage[n] = record
    cursor = copy.deepcopy(idx.start)
    prefix = 0
    while prefix + 1 in coverage and coverage[prefix + 1]["status"] == "DONE":
        record = coverage[prefix + 1]
        require(record["start_cursor"] == cursor, "COVERAGE_GAP", "coverage_ledger", "Non-adjacent valid prefix")
        cursor = copy.deepcopy(record["end_cursor"])
        prefix += 1
    reached = idx.rank(cursor, "derived.script_cursor")
    for left, right, chain in idx.ranges:
        require(chain["source_version"] == source_version or right <= reached, "SOURCE_MAPPING_UNSUPPORTED",
                f"chain_registry.{chain['id']}", "Undelivered ranges must be remapped to the current source version")
    next_chain = "END" if cursor == "END" else cursor["chain_id"]
    derived = {"last_completed_formal": prefix, "script_cursor": cursor,
               "next_chain_unstarted": next_chain,
               "frontier": f"FORMAL_{prefix + 1}" if cursor != "END" else None,
               "frontier_planned": prefix + 1 in plans,
               "registry_exhausted": bool(idx.chains) and cursor == "END",
               "end_state_source": copy.deepcopy(coverage[prefix].get("end_state")) if prefix else None,
               "end_state_formal_id": f"FORMAL_{prefix}" if prefix else None}
    idx.rank(state["script_cursor"], "script_cursor")
    if compare_derived:
        for key in ("last_completed_formal", "script_cursor", "next_chain_unstarted"):
            require(state[key] == derived[key], "DERIVED_MISMATCH", key, f"Expected {derived[key]!r}")
    settings = obj(state["production_settings"], "production_settings")
    for name in ("video_aspect_ratio", "visual_style", "segment_max_s"):
        setting = obj(settings.get(name), f"production_settings.{name}")
        require(setting.get("status") in ("PENDING", "CONFIRMED"), "ENUM", name, "Invalid setting status")
        if setting["status"] == "CONFIRMED":
            require(present(setting.get("selected")) and present(setting.get("decision_ref")), "SETTING_EVIDENCE", name, "Confirmed setting needs selection and decision")
            expected_value = state[name].get("value") if name == "segment_max_s" and isinstance(state[name], dict) else state[name]
            require(setting["selected"] == expected_value, "SETTING_MAPPING", name, "Selection differs from effective setting")
            if name == "segment_max_s":
                number(setting["selected"], name, positive=True)
    if state["production_settings_status"] == "CONFIRMED":
        require(all(value["status"] == "CONFIRMED" for value in (settings[k] for k in ("video_aspect_ratio", "visual_style", "segment_max_s"))),
                "SETTING_EVIDENCE", "production_settings_status", "Not all three settings are confirmed")
    blockers = array(state["blocking_items"], "blocking_items")
    for i, blocker in enumerate(blockers):
        path = f"blocking_items[{i}]"
        obj(blocker, path)
        text(blocker.get("step_id"), path + ".step_id")
        saved_phase = blocker.get("phase")
        require(isinstance(saved_phase, str) and saved_phase in PHASES, "PHASE", path, "Blocker needs its owning phase")
        text(blocker.get("gap"), path + ".gap")
        if "blocks" in blocker:
            for target in array(blocker["blocks"], path + ".blocks"):
                text(target, path + ".blocks")
    if compare_derived:
        _unit_evidence(units, steps)
    locked = present(state["edit_lock"])
    target = state["next_required"]
    if target == "WAIT_USER":
        require(bool(blockers) and not state["awaiting_continue"], "WAIT_USER", "next_required", "WAIT_USER requires blockers and no continue flag")
    if locked:
        text(state["edit_lock"], "edit_lock")
        require(state["phase"] == "EDIT_LOCK", "EDIT_LOCK", "phase", "Unfinished revision must retain EDIT_LOCK")
    elif target == "WAIT_USER":
        require(state["phase"] in {b["phase"] for b in blockers}, "PHASE", "phase", "WAIT_USER phase must match a blocker")
    else:
        expected_phase = ("COMPLETE" if target == "COMPLETE" else
                          "PROJECT_SETUP" if target == "PROJECT_BASELINE" else
                          "FORMAL_RUNNING" if re.fullmatch(r"FORMAL_[1-9]\d*", target) else
                          "EPISODE_PLANNING" if re.fullmatch(r"EP\d+_PLAN", target) else
                          "SCENE_PREP" if re.fullmatch(r"EP\d+-SC\d+_(?:ANALYSIS|BUDGET_SEGMENT)", target) else
                          "ASSET_RUNNING")
        require(state["phase"] == expected_phase, "PHASE", "phase", "Phase and next_required disagree")
        if expected_phase == "SCENE_PREP":
            scope = target.split("_", 1)[0]
            require(scope == state["episode_id"] + "-" + state["scene_id"], "SCENE_SCOPE", "next_required", "Scene target must include the current episode")
        if expected_phase == "EPISODE_PLANNING":
            require(target == state["episode_id"] + "_PLAN", "SCENE_SCOPE", "next_required", "Episode target mismatch")
        if target == "COMPLETE" and compare_derived:
            require(derived["registry_exhausted"] and not state["awaiting_continue"], "COMPLETE", target, "COMPLETE needs exhausted coverage and no continue flag")
        if expected_phase == "FORMAL_RUNNING" and compare_derived:
            require(target == derived["frontier"] and derived["frontier_planned"], "FRONTIER", target, "Formal target must be the first uncompleted planned segment")
        if expected_phase != "PROJECT_SETUP":
            require(state["production_settings_status"] == "CONFIRMED", "SETTINGS_GATE", target, "Production needs three confirmed settings")
        if compare_derived:
            _gate(state, target, expected_phase, steps, units, plans, derived)
        for blocker in blockers:
            require("blocks" in blocker, "BLOCK_SCOPE_UNKNOWN", "blocking_items", "Declare exact blocked targets before advancing")
            require("*" not in blocker["blocks"] and target not in blocker["blocks"], "BLOCKED_TARGET", target, "Current target is still blocked")
    return derived, versions


def derive(state):
    result, _ = _inspect_state(state, compare_derived=False)
    return result


def calculate_timing(timing, path="timing"):
    obj(timing, path)
    require(len(timing) == 1 and next(iter(timing)) in ("seconds", "sequence", "parallel"),
            "TIMING_SHAPE", path, "Use exactly one of seconds, sequence or parallel")
    if "seconds" in timing:
        return number(timing["seconds"], path + ".seconds")
    if "sequence" in timing:
        parts = array(timing["sequence"], path + ".sequence")
        require(bool(parts), "TIMING_SHAPE", path, "Sequence cannot be empty")
        total = sum(calculate_timing(part, f"{path}.sequence[{i}]") for i, part in enumerate(parts))
    else:
        parallel = obj(timing["parallel"], path + ".parallel")
        text(parallel.get("basis"), path + ".parallel.basis")
        tracks = array(parallel.get("tracks"), path + ".parallel.tracks")
        require(bool(tracks), "TIMING_SHAPE", path, "Parallel cannot be empty")
        durations = []
        for i, track in enumerate(tracks):
            tp = f"{path}.parallel.tracks[{i}]"
            obj(track, tp)
            offset = number(track.get("offset_s"), tp + ".offset_s")
            durations.append(offset + calculate_timing(track.get("timing"), tp + ".timing"))
        total = max(durations)
    return number(total, path)


def equal_time(actual, expected, path):
    require(math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7), "TIME_MISMATCH", path,
            f"Expected {expected}, got {actual}")


def check_budget(budget, state):
    obj(budget, "budget")
    finite_tree(budget)
    require(budget.get("time_basis") == "SEGMENT", "TIME_BASIS", "budget.time_basis", "All absolute times must use segment zero")
    fid = budget.get("formal_id")
    formal_number(fid, "budget.formal_id")
    version = text(budget.get("prompt_version"), "budget.prompt_version")
    bv = text(budget.get("budget_version"), "budget.budget_version")
    matches = [p for p in state["prompt_versions"] if p["formal_id"] == fid and p["prompt_version"] == version]
    require(len(matches) == 1 and matches[0]["status"] != "INVALID" and matches[0]["budget_version"] == bv,
            "VERSION_MAPPING", "budget", "Budget must map to a valid prompt version")
    current = [c for c in state["coverage_ledger"] if c["formal_id"] == fid and c["status"] == "DONE"]
    if current:
        require(current[0]["prompt_version"] == version and current[0]["budget_version"] == bv,
                "VERSION_MAPPING", "budget", "Budget is not the current effective version")
    duration = number(budget.get("duration_s"), "budget.duration_s", positive=True)
    limit = number(budget.get("target_max_s"), "budget.target_max_s", positive=True)
    user_limit = state["production_settings"]["segment_max_s"].get("selected")
    number(user_limit, "production_settings.segment_max_s.selected", positive=True)
    require(limit <= user_limit and duration <= limit, "TIME_LIMIT", "budget", "Duration or target exceeds confirmed limit")
    shots = array(budget.get("shots"), "budget.shots")
    require(bool(shots), "SHOTS", "budget.shots", "At least one shot is required")
    end = 0
    ids = set()
    for i, shot in enumerate(shots):
        path = f"budget.shots[{i}]"
        obj(shot, path)
        sid = text(shot.get("id"), path + ".id")
        require(sid not in ids, "DUPLICATE_SHOT", path, "Duplicate shot id")
        ids.add(sid)
        start = number(shot.get("start_s"), path + ".start_s")
        stop = number(shot.get("end_s"), path + ".end_s")
        length = number(shot.get("duration_s"), path + ".duration_s", positive=True)
        equal_time(start, end, path + ".start_s")
        equal_time(stop - start, length, path + ".duration_s")
        if "timing" in shot:
            equal_time(calculate_timing(shot["timing"], path + ".timing"), length, path + ".timing")
        if "phases" in shot:
            phases = array(shot["phases"], path + ".phases")
            require(bool(phases), "PHASES", path, "Explicit phases cannot be empty")
            phase_end = start
            for j, phase in enumerate(phases):
                pp = f"{path}.phases[{j}]"
                obj(phase, pp)
                ps = number(phase.get("start_s"), pp + ".start_s")
                pe = number(phase.get("end_s"), pp + ".end_s")
                require(pe > ps and ps >= start and pe <= stop, "PHASE_RANGE", pp, "Phase must stay within its shot using segment time")
                equal_time(ps, phase_end, pp + ".start_s")
                if "timing" in phase:
                    equal_time(calculate_timing(phase["timing"], pp + ".timing"), pe - ps, pp + ".timing")
                phase_end = pe
            equal_time(phase_end, stop, path + ".phases")
        end = stop
    equal_time(end, duration, "budget.duration_s")
    speech_count = 0
    speech_ids = set()
    for i, speech in enumerate(array(budget.get("speech_checks", []), "budget.speech_checks")):
        path = f"budget.speech_checks[{i}]"
        obj(speech, path)
        sid = text(speech.get("speech_id"), path + ".speech_id")
        require(sid not in speech_ids, "DUPLICATE_SPEECH", path, "Duplicate speech mapping")
        speech_ids.add(sid)
        source = text(speech.get("source_text"), path + ".source_text")
        rendered = text(speech.get("rendered_text"), path + ".rendered_text")
        require(source == rendered, "SPEECH_MISMATCH", path, "Mapped dialogue is not character-for-character identical")
        speech_count += 1
    return {"formal_id": fid, "duration_s": duration, "shots": len(shots),
            "speech_pairs_checked": speech_count,
            "speech_scope": "PROVIDED_PAIRS_ONLY" if speech_count else "MANUAL_SCOPE_ONLY"}


def validate(state, budgets=()):
    derived, _ = _inspect_state(state)
    checked = [check_budget(budget, state) for budget in budgets]
    return {"ok": True, "scope": "MECHANICAL_ONLY", "derived": derived,
            "budgets_checked": checked, "manual_scope": MANUAL_SCOPE}


def cancel_request(state, request_id, decision_ref):
    validate(state)
    text(request_id, "request_id")
    text(decision_ref, "decision_ref")
    context = obj(state["return_to"], "return_to")
    require(context.get("request_id") == request_id, "RETURN_CONTEXT", "return_to", "Request does not own the saved return context")
    require(not present(context.get("previous_return_to")), "NESTED_RETURN_UNSUPPORTED", "return_to", "Nested return contexts require manual recovery")
    for field in ("phase", "next_required", "episode_id", "scene_id"):
        text(context.get(field), "return_to." + field)
    require(context["phase"] in PHASES and context["next_required"] != "WAIT_USER"
            and type(context.get("awaiting_continue")) is bool,
            "RETURN_CONTEXT", "return_to", "Need a concrete original target, phase and waiting flag")
    candidate = copy.deepcopy(state)
    matches = [a for p in candidate["prompt_versions"] for a in p.get("adapters", []) if a["request_id"] == request_id]
    require(len(matches) == 1 and matches[0]["lifecycle"] == "ACTIVE", "REQUEST_NOT_ACTIVE", "request_id", "Request must exist and be active; repeated cancellation is rejected")
    adapter = matches[0]
    adapter["lifecycle"] = "CANCELLED"
    adapter["decision_ref"] = decision_ref
    candidate["state_seq"] += 1
    adapter["cancelled_at_state_seq"] = candidate["state_seq"]
    candidate["transaction_id"] = "cancel-" + uuid.uuid4().hex
    candidate["blocking_items"] = [b for b in candidate["blocking_items"] if b.get("request_id") != request_id]
    for step in candidate["step_ledger"]:
        if step.get("request_id") == request_id:
            require(re.fullmatch(r"FORMAL_\d+", step["step_id"]) is None, "CANCEL_SCOPE", "step_ledger", "Independent request cannot cancel formal delivery")
            step["status"] = "CANCELLED"
            step["decision_ref"] = decision_ref
    for field in ("phase", "next_required", "awaiting_continue", "episode_id", "scene_id"):
        candidate[field] = context[field]
    if present(candidate["edit_lock"]):
        candidate["phase"] = "EDIT_LOCK"
        candidate["next_required"] = candidate["edit_lock"]
        candidate["awaiting_continue"] = False
    pending = []
    for blocker in candidate["blocking_items"]:
        require("blocks" in blocker, "BLOCK_SCOPE_UNKNOWN", "blocking_items", "Cannot infer whether another blocker affects the return target")
        if "*" in blocker["blocks"] or candidate["next_required"] in blocker["blocks"]:
            pending.append(blocker)
    if present(candidate["edit_lock"]):
        candidate["return_to"] = {key: context[key] for key in ("phase", "next_required", "awaiting_continue", "episode_id", "scene_id")}
    else:
        candidate["return_to"] = None
    if pending:
        restored = {key: candidate[key] for key in ("phase", "next_required", "awaiting_continue", "episode_id", "scene_id")}
        if not present(candidate["edit_lock"]):
            phases = {b["phase"] for b in pending}
            require(len(phases) == 1, "RETURN_PHASE_AMBIGUOUS", "blocking_items", "Remaining blockers need an unambiguous owning phase")
            candidate["phase"] = next(iter(phases))
        candidate["next_required"] = "WAIT_USER"
        candidate["awaiting_continue"] = False
        candidate["return_to"] = restored
    validate(candidate)
    return candidate


def _cancelled_record_retained(previous, current, status_field):
    if previous[status_field] != "CANCELLED":
        return True
    return current[status_field] == "CANCELLED" and all(
        field in current and current[field] == previous[field]
        for field in ("decision_ref", "cancelled_at_state_seq") if field in previous)


def _retain_history(old, candidate):
    old_ids = {c["formal_id"] for c in old["coverage_ledger"]}
    require(old_ids <= {c["formal_id"] for c in candidate["coverage_ledger"]}, "HISTORY_LOSS", "coverage_ledger",
            "Retain existing coverage records, marking invalid records explicitly")
    versions = {(p["formal_id"], p["prompt_version"]): p for p in candidate["prompt_versions"]}
    for prompt in old["prompt_versions"]:
        key = (prompt["formal_id"], prompt["prompt_version"])
        require(key in versions, "HISTORY_LOSS", "prompt_versions", "Historical prompt mappings cannot disappear")
        adapters = {a["request_id"]: a for a in versions[key].get("adapters", [])}
        for adapter in prompt.get("adapters", []):
            rid = adapter["request_id"]
            require(rid in adapters, "HISTORY_LOSS", "prompt_versions.adapters",
                    "Existing requests must stay attached to their original prompt version")
            require(_cancelled_record_retained(adapter, adapters[rid], "lifecycle"),
                    "HISTORY_LOSS", "prompt_versions.adapters",
                    "Retain cancelled lifecycle and original cancellation evidence; reopen with a new request id")
    identity = ("step_id", "request_id", "prompt_version", "adapter_version")
    remaining = list(candidate["step_ledger"])
    previous_steps = sorted(old["step_ledger"], key=lambda step: (
        step["status"] == "CANCELLED", sum(field in step for field in identity)), reverse=True)
    for step in previous_steps:
        matches = [i for i, current in enumerate(remaining)
                   if all(field in current and current[field] == step[field] for field in identity if field in step)
                   and _cancelled_record_retained(step, current, "status")]
        require(bool(matches), "HISTORY_LOSS", "step_ledger",
                "Retain each started step, its recorded request/version and any cancellation evidence")
        index = min(matches, key=lambda i: sum(field in remaining[i] and field not in step for field in identity))
        remaining.pop(index)


def commit(state_path, candidate_path, expected_state_seq, budgets=()):
    state_path = Path(state_path).resolve()
    candidate_path = Path(candidate_path).resolve()
    require(state_path != candidate_path, "COMMIT_PATH", "candidate", "Candidate must be a separate file")
    integer(expected_state_seq, "expected_state_seq")
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_fd = None
    temporary = None
    warnings = []
    failure = None
    try:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise CheckError("WRITE_LOCK", str(lock_path), "Another writer or an unrecovered lock exists") from exc
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
        original = state_path.read_bytes()
        old = parse_json(original.decode("utf-8-sig"))
        _inspect_state(old, compare_derived=False)
        candidate = load_json(candidate_path)
        validate(candidate, budgets)
        require(old["state_seq"] == expected_state_seq, "STALE_STATE", "state_seq", "Expected sequence is stale")
        require(candidate["state_seq"] == expected_state_seq + 1, "STATE_SEQUENCE", "state_seq", "Candidate sequence must increase by exactly one")
        require(candidate["project_id"] == old["project_id"], "PROJECT_ID", "project_id", "Cannot replace another project's state")
        require(candidate["transaction_id"] != old["transaction_id"], "TRANSACTION", "transaction_id", "New commit needs a new transaction id")
        require(candidate["state_storage"] == "FILE" and isinstance(candidate["state_ref"], str),
                "STATE_REF", "state_ref", "A committed snapshot must declare FILE storage and its state path")
        ref = Path(candidate["state_ref"])
        require(ref.is_absolute() and ref.resolve() == state_path, "STATE_REF", "state_ref", "Candidate must name this authoritative file")
        _retain_history(old, candidate)
        payload = (json.dumps(candidate, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=state_path.parent, prefix=state_path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        require(temporary.read_bytes() == payload, "WRITE_VERIFY", str(temporary), "Temporary snapshot differs from candidate")
        require(state_path.read_bytes() == original, "STALE_STATE", str(state_path), "State changed during commit")
        os.replace(temporary, state_path)
        temporary = None
    except Exception as exc:
        failure = exc
        raise
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                warnings.append({"code": "CLEANUP_FAILED", "path": str(temporary),
                                 "operation": "remove_temporary", "message": str(exc)})
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError as exc:
                warnings.append({"code": "CLEANUP_FAILED", "path": str(lock_path),
                                 "operation": "close_lock", "message": str(exc)})
            else:
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError as exc:
                    warnings.append({"code": "CLEANUP_FAILED", "path": str(lock_path),
                                     "operation": "remove_lock", "message": str(exc)})
        if failure is not None and warnings:
            failure.cleanup_warnings = warnings
    return {"ok": True, "committed": True, "state_seq": candidate["state_seq"],
            "scope": "SINGLE_STATE_FILE", "state_ref": str(state_path),
            "cleanup_complete": not warnings, "warnings": warnings}


def initial_state(project_id, source_version, source_location, state_ref=None, step_policy="STRICT",
                  execution_mode="REVIEW"):
    """A valid new-project snapshot: PROJECT_SETUP, next_required=PROJECT_BASELINE, nothing confirmed."""
    pending = {"recommended": "UNSET", "selected": "UNSET", "status": "PENDING", "decision_ref": None}
    file_mode = state_ref is not None
    values = {
        "state_seq": 0, "state_version": STATE_VERSION, "workflow_schema": WORKFLOW_SCHEMA,
        "transaction_id": "init-" + uuid.uuid4().hex, "phase": "PROJECT_SETUP", "project_id": text(project_id, "project_id"),
        "project_status": "IN_PROGRESS", "project_analysis_status": "IN_PROGRESS", "production_settings_status": "UNSET",
        "production_settings": {name: dict(pending) for name in ("video_aspect_ratio", "visual_style", "segment_max_s")},
        "video_aspect_ratio": "UNSET", "visual_style": "UNSET",
        "source_script_ref": {"version": text(source_version, "source_version"), "location": text(source_location, "source_location")},
        "visual_reference_status": "UNSET", "asset_status": "UNSET", "asset_substage": "CHARACTER",
        "character_asset_status": "UNSET", "scene_asset_status": "UNSET", "prop_asset_status": "UNSET",
        "scene_prop_asset_status": "UNSET", "episode_id": "UNSET", "episode_status": "UNSET", "scene_id": "UNSET",
        "scene_wide_status": "UNSET", "prep_scene": "UNSET", "prep_step": 0, "prep_batch": 0, "prep_status": "UNSET",
        "last_completed_formal": 0, "last_output": "NONE", "next_required": "PROJECT_BASELINE", "script_cursor": "END",
        "next_chain_unstarted": "END", "segment_max_s": "UNSET", "segment_delivery": "ONE_AT_A_TIME",
        "budget_status": "UNSET", "execution_mode": execution_mode, "step_policy": step_policy,
        "performance_mode": "NORMAL", "awaiting_continue": False, "delivery_mode": "PROMPT_CLEAN",
        "delivery_channel": "FILE" if file_mode else "CHAT", "state_storage": "FILE" if file_mode else "CONVERSATION",
        "state_ref": str(state_ref) if file_mode else "conversation:initial-snapshot",
    }
    arrays = ("project_decisions", "asset_queue", "chain_registry", "coverage_ledger", "prompt_versions",
              "segment_plan", "transition_plan", "transition_review", "prop_ledger", "step_ledger", "blocking_items")
    objects = ("character_assets", "character_profiles", "scene_assets", "prop_assets", "characters_state",
               "viewing_state", "weapons_props_state", "environment_state", "voice_profile")
    state = {}
    for field in STATE_FIELDS:
        state[field] = values[field] if field in values else [] if field in arrays else {} if field in objects else None
    validate(state)
    return state


def receipt(state, delivered=None):
    """Short receipt derived from a valid state, so it cannot claim more than the state records.

    delivered: optional list of units delivered this round (e.g. several units under BATCH_PREP);
    each must have a DONE/REUSED step_ledger record.
    """
    validate(state)
    target = state["next_required"]
    blockers = state["blocking_items"]
    finished = {s["step_id"] for s in state["step_ledger"] if s["status"] in FINISHED}
    if delivered:
        missing = [unit for unit in delivered if unit not in finished]
        require(not missing, "DELIVERY", "delivered", f"No DONE/REUSED step_ledger record for {missing}")
        done_text = "本轮交付 " + "、".join(delivered)
    elif present(state["last_output"]):
        done_text = f"最近交付 {state['last_output']}"
    else:
        done_text = "尚未交付任何单元"
    if present(state["edit_lock"]):
        outcome = f"返修未完成：{state['edit_lock']} 仍在返修锁中，未推进新段"
    elif target == "WAIT_USER":
        gaps = "；".join(f"{b['step_id']}：{b['gap']}" for b in blockers)
        outcome = f"目标未完成（受阻，等待用户）：{gaps}"
    elif target == "COMPLETE":
        outcome = "已知制作范围的文字交付已全部完成；不代表媒体已生成"
    elif state["awaiting_continue"]:
        outcome = f"{done_text}；下一单元 {target} 尚未开始，等待“继续”"
    else:
        outcome = f"{done_text}；当前目标 {target}"
    fields = {key: state[key] for key in ("state_seq", "episode_id", "scene_id", "last_output", "last_completed_formal",
                                          "next_required", "awaiting_continue", "script_cursor", "state_ref", "plan_ref")}
    for key in ("blocking_items", "edit_lock", "invalidated_from"):
        if present(state[key]) and state[key] != []:
            fields[key] = state[key]
    lines = [f"【运行状态回执 不属于视频提示词】", f"结果：{outcome}"]
    lines += [f"{key}={json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}"
              for key, value in fields.items()]
    return {"outcome": outcome, "fields": fields, "text": "\n".join(lines)}


def summary(state):
    """Compact working view for resuming; the full snapshot stays authoritative."""
    try:
        derived = derive(state)
    except CheckError as exc:
        derived = {"error": exc.detail}
    try:
        validate(state)
        validation = {"ok": True}
    except CheckError as exc:
        validation = {"ok": False, "error": exc.detail}
    head = {key: state[key] for key in ("project_id", "state_seq", "phase", "next_required", "awaiting_continue",
                                        "episode_id", "scene_id", "prep_step", "last_output", "last_completed_formal",
                                        "script_cursor", "execution_mode", "step_policy", "edit_lock", "blocking_items",
                                        "return_to", "invalidated_from", "state_ref", "plan_ref", "budget_ref")}
    target = state["next_required"]
    current = [s for s in state["step_ledger"] if s["step_id"] in (target, state["last_output"])]
    plan = next((p for p in state["segment_plan"] if p["formal_id"] == target), None)
    continuity = {key: state[key] for key in ("characters_state", "weapons_props_state", "environment_state",
                                              "ongoing_effects_state", "viewing_state", "last_frame_snapshot")}
    counts = {key: len(state[key]) for key in ("step_ledger", "coverage_ledger", "prompt_versions", "segment_plan",
                                               "asset_queue", "chain_registry")}
    open_units = [u["id"] for u in state["asset_queue"] if u.get("status") in OPEN_ASSET]
    settings = {key: state[key] for key in ("production_settings", "video_aspect_ratio", "visual_style", "segment_max_s",
                                            "character_profiles", "project_decisions", "edit_context")}
    formal = plan["formal_id"] if plan else state["edit_lock"] if present(state["edit_lock"]) else None
    prompts = [p for p in state["prompt_versions"] if p.get("formal_id") == formal]
    chains = []
    if plan:
        ids = {c.get("chain_id") for c in (plan.get("start_cursor"), plan.get("end_cursor")) if isinstance(c, dict)}
        chains = [c for c in state["chain_registry"] if c.get("id") in ids]
    return {"validation": validation, "head": head, "derived": derived, "target_plan": plan, "target_chains": chains,
            "target_prompt_versions": prompts, "relevant_steps": current, "open_asset_units": open_units,
            "settings": settings, "continuity": continuity, "counts": counts,
            "full_state_bytes": len(json.dumps(state, ensure_ascii=False).encode("utf-8"))}


def _pointer(path):
    require(isinstance(path, str) and path.startswith("/") and path != "/", "PATCH_PATH", str(path),
            "Use a JSON Pointer such as /coverage_ledger/-")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _parent(document, parts, path):
    node = document
    for part in parts[:-1]:
        if isinstance(node, list):
            require(part.isdigit() and int(part) < len(node), "PATCH_PATH", path, "Array index out of range")
            node = node[int(part)]
        else:
            require(isinstance(node, dict) and part in node, "PATCH_PATH", path, "Missing parent member")
            node = node[part]
    return node


PATCH_RESERVED = ("state_seq", "transaction_id", "state_version", "workflow_schema", "project_id")
DERIVED_FIELDS = ("last_completed_formal", "script_cursor", "next_chain_unstarted")


def apply_patch(state, operations, sync_derived=True):
    """Apply add/replace/remove/test operations; bump state_seq and transaction_id; validate the result."""
    candidate = copy.deepcopy(state)
    for index, op in enumerate(array(operations, "patch")):
        where = f"patch[{index}]"
        obj(op, where)
        kind = op.get("op")
        require(kind in ("add", "replace", "remove", "test"), "PATCH_OP", where, "op must be add, replace, remove or test")
        parts = _pointer(op.get("path"))
        require(parts[0] in STATE_FIELDS, "PATCH_PATH", op["path"], "Unknown top-level field")
        require(parts[0] not in PATCH_RESERVED, "PATCH_RESERVED", op["path"], "This field is set by the tool")
        require(kind == "test" or not (sync_derived and parts[0] in DERIVED_FIELDS), "PATCH_RESERVED", op["path"],
                "Derived from coverage; pass --no-sync-derived to set it by hand")
        require(kind != "remove" or len(parts) > 1, "PATCH_PATH", op["path"], "Top-level fields cannot be removed")
        parent = _parent(candidate, parts, op["path"])
        key = parts[-1]
        require(kind not in ("add", "replace", "test") or "value" in op, "PATCH_OP", where, f"{kind} needs a value")
        if isinstance(parent, list):
            if kind == "add" and key == "-":
                parent.append(copy.deepcopy(op.get("value")))
                continue
            require(key.isdigit() and int(key) < len(parent) + (kind == "add"), "PATCH_PATH", op["path"], "Bad array index")
            position = int(key)
            if kind == "add":
                parent.insert(position, copy.deepcopy(op.get("value")))
            elif kind == "replace":
                parent[position] = copy.deepcopy(op.get("value"))
            elif kind == "remove":
                parent.pop(position)
            else:
                require(parent[position] == op.get("value"), "PATCH_TEST", op["path"], "Test value differs")
        else:
            require(isinstance(parent, dict), "PATCH_PATH", op["path"], "Parent is not a container")
            if kind in ("replace", "remove", "test"):
                require(key in parent, "PATCH_PATH", op["path"], "Member does not exist")
            if kind in ("add", "replace"):
                require("value" in op, "PATCH_OP", where, "add/replace need a value")
                parent[key] = copy.deepcopy(op["value"])
            elif kind == "remove":
                del parent[key]
            else:
                require(parent[key] == op.get("value"), "PATCH_TEST", op["path"], "Test value differs")
    if sync_derived:
        derived = derive(candidate)
        for field in DERIVED_FIELDS:
            candidate[field] = copy.deepcopy(derived[field])
    candidate["state_seq"] = state["state_seq"] + 1
    candidate["transaction_id"] = "patch-" + uuid.uuid4().hex
    validate(candidate)
    _retain_history(state, candidate)
    changed = sorted(field for field in STATE_FIELDS if candidate[field] != state[field])
    return candidate, changed


def main():
    # JSON goes out as UTF-8 even under `python -I`, which ignores PYTHONIOENCODING on Windows pipes.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--project-id", required=True)
    init.add_argument("--source-version", required=True)
    init.add_argument("--source-location", required=True)
    init.add_argument("--step-policy", choices=("STRICT", "SCENE_ASSETS"), default="STRICT")
    init.add_argument("--execution-mode", choices=("REVIEW", "BATCH_PREP"), default="REVIEW")
    target = init.add_mutually_exclusive_group(required=True)
    target.add_argument("--output", type=Path, help="New absolute run-state.json path; never overwrites")
    target.add_argument("--conversation", action="store_true", help="Print a CONVERSATION snapshot instead")
    for command in ("check", "derive", "cancel", "commit", "receipt", "summary", "patch"):
        p = sub.add_parser(command)
        p.add_argument("--state", type=Path, required=True)
        p.add_argument("--budget", type=Path, action="append", default=[])
        if command == "cancel":
            p.add_argument("--request-id", required=True)
            p.add_argument("--decision-ref", required=True)
            p.add_argument("--output", type=Path, help="New candidate file; never overwrites")
        if command == "commit":
            p.add_argument("--candidate", type=Path, required=True)
            p.add_argument("--expected-state-seq", type=int, required=True)
        if command == "receipt":
            p.add_argument("--json", action="store_true")
            p.add_argument("--delivered", nargs="*", help="Units delivered this round, e.g. under BATCH_PREP")
        if command == "patch":
            p.add_argument("--ops", type=Path, required=True, help="JSON array of add/replace/remove/test operations")
            p.add_argument("--output", type=Path, help="New candidate file; never overwrites")
            p.add_argument("--commit", action="store_true", help="Commit the written candidate in the same call")
            p.add_argument("--no-sync-derived", action="store_true")
    args = parser.parse_args()

    def write_new(path, value):
        with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")

    try:
        budgets = [load_json(path) for path in getattr(args, "budget", [])]
        if args.command == "init":
            ref = None
            if args.output is not None:
                require(args.output.is_absolute(), "STATE_REF", "--output", "Use an absolute path for the authoritative state")
                ref = args.output
            state = initial_state(args.project_id, args.source_version, args.source_location, ref,
                                  args.step_policy, args.execution_mode)
            if ref is None:
                result = state
            else:
                write_new(ref, state)
                result = {"ok": True, "state_ref": str(ref), "state_seq": 0, "next_required": "PROJECT_BASELINE"}
        elif args.command == "commit":
            result = commit(args.state, args.candidate, args.expected_state_seq, budgets)
        else:
            state = load_json(args.state)
            if args.command == "check":
                result = validate(state, budgets)
            elif args.command == "derive":
                result = {"ok": True, "scope": "COVERAGE_ONLY", "derived": derive(state), "manual_scope": MANUAL_SCOPE}
                result["budgets_checked"] = [check_budget(b, state) for b in budgets]
            elif args.command == "receipt":
                made = receipt(state, args.delivered)
                if not args.json:
                    print(made["text"])
                    return 0
                result = made
            elif args.command == "summary":
                result = summary(state)
            elif args.command == "patch":
                require(args.output is not None or not args.commit, "COMMIT_PATH", "--output",
                        "--commit needs --output for the separate candidate file")
                candidate, changed = apply_patch(state, load_json(args.ops), not args.no_sync_derived)
                validate(candidate, budgets)
                if args.output is None:
                    result = {"ok": True, "committed": False, "changed_fields": changed, "candidate": candidate}
                else:
                    write_new(args.output, candidate)
                    result = {"ok": True, "committed": False, "candidate_ref": str(args.output),
                              "changed_fields": changed, "state_seq": candidate["state_seq"]}
                    if args.commit:
                        result = commit(args.state, args.output, state["state_seq"], budgets)
                        result["changed_fields"] = changed
            else:
                result = cancel_request(state, args.request_id, args.decision_ref)
                validate(result, budgets)
                if args.output is not None:
                    write_new(args.output, result)
                    result = {"ok": True, "candidate_ref": str(args.output), "committed": False}
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (CheckError, OSError, UnicodeError, RecursionError) as exc:
        error = exc.detail if isinstance(exc, CheckError) else {"code": "IO_OR_DEPTH", "message": str(exc)}
        result = {"ok": False, "errors": [error]}
        if args.command == "commit" or (args.command == "patch" and args.commit):
            result["committed"] = False
        if getattr(exc, "cleanup_warnings", None):
            result.update(cleanup_complete=False, warnings=exc.cleanup_warnings)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(exc, CheckError) else 2


if __name__ == "__main__":
    raise SystemExit(main())
