"""Regression for 0.5.0: predecessor gates, check evidence, state commands, source revisions, prompt lint."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import test_state_budget as base

ROOT = base.ROOT
checks = base.checks
SPEC = importlib.util.spec_from_file_location("prompt_lint", ROOT / "scripts/prompt_lint.py")
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)
ARCHIVE = ROOT / "evals/runs/0.4.1-user-review/workflow"
PILOT = ROOT / "evals/runs/0.5.0-media-pilot"
PYTHON = [sys.executable, "-I", "-B", "-X", "utf8"]


def asset_state():
    state = base.fresh()
    state.update(phase="ASSET_RUNNING", next_required="CHAR_A", asset_status="RUNNING", asset_substage="CHARACTER",
                 character_asset_status="RUNNING", scene_asset_status="UNSET", prop_asset_status="UNSET",
                 scene_prop_asset_status="UNSET")
    state["asset_queue"] = [{"id": "CHAR_A", "kind": "CHARACTER", "status": "PENDING", "order": 1},
                            {"id": "SCENE_B", "kind": "SCENE", "status": "PENDING", "order": 2},
                            {"id": "PROP_C", "kind": "PROP", "status": "PENDING", "order": 3}]
    state["step_ledger"] = [s for s in state["step_ledger"] if s["step_id"] == "PROJECT_BASELINE"]
    return state


def scene_policy_state():
    state = base.fresh()
    state.update(step_policy="SCENE_ASSETS", asset_status="RUNNING", asset_substage="PROP",
                 character_asset_status="DONE", scene_asset_status="DONE", prop_asset_status="RUNNING",
                 scene_prop_asset_status="RUNNING")
    state["asset_queue"] = [
        {"id": "CHAR_A", "kind": "CHARACTER", "status": "DONE", "needed_by": ["EP01-SC01", "EP01-SC02"]},
        {"id": "PROP_LATER", "kind": "PROP", "status": "PENDING", "needed_by": ["EP01-SC02"]}]
    state["step_ledger"].append({"step_id": "CHAR_A", "status": "DONE", "delivery_ref": "assets/char-a.md"})
    return state


def first_delivery_ops(state):
    plan = copy.deepcopy(state["segment_plan"][0])
    plan.update(prompt_version="P1", budget_version="B1", delivery_ref="prompts.md#formal-1", status="DONE",
                checks={"TEXT": {"status": "PASS", "evidence": "prompts.md#formal-1"}}, end_state={"door": "half"})
    return [{"op": "test", "path": "/next_required", "value": "FORMAL_1"},
            {"op": "replace", "path": "/prompt_versions/0/status", "value": "DONE"},
            {"op": "add", "path": "/coverage_ledger/-", "value": plan},
            {"op": "add", "path": "/step_ledger/-", "value": {"step_id": "FORMAL_1", "status": "DONE",
                                                             "prompt_version": "P1", "delivery_ref": "prompts.md#formal-1"}},
            {"op": "replace", "path": "/next_required", "value": "FORMAL_2"},
            {"op": "replace", "path": "/last_output", "value": "FORMAL_1"}]


CLEAN_MASTER = """场《测试·夜》·段《推门》

总时长：6秒
时间码均相对本段0秒。
无字幕，无BGM
16:9

【角色锚定】

岑雨
岑雨是27岁的女性，身高168厘米，深蓝短外套，站在门内，右手握着唯一一把铜钥匙，左手贴着门板。

【全片风格】
克制写实，门内固定光源，保留推门手部和门缝细节。

【整体描述】

场景与环境：
夜里的值班室，画面右侧是一扇关着的木门。

本段光线、色彩与环境基调：
顶部一盏台灯照亮门板和她的双手。

开场状态与本段范围：
开场岑雨的左手贴着门板，右手握着钥匙；随后她把门推到半开。

镜头一 {
时间：0–6秒。

景别、机位：
中景（Medium Shot，MS），摄影机在岑雨右后方胸口高度。

运镜及拍摄主体：
静止镜头（Static Shot），主体是岑雨推门的左手。

构图：
三分法（Rule of Thirds），门在画面右侧三分线。

画面内容：
0–3秒，岑雨用左手把门推开一条缝。3–6秒，门继续转到半开，她低声说：
岑雨（低声）：“我等你。”

声效：
门轴的轻微摩擦声。
}

【禁止项】

无水印。"""


class GateTests(unittest.TestCase):
    assert_error = base.StateBudgetTests.assert_error

    def test_formal_target_needs_assets_and_scene_preparation(self):
        for change in ("assets", "analysis_step", "prep_fields", "plan_step"):
            state = base.fresh()
            if change == "assets":
                state.update(asset_status="RUNNING", character_asset_status="RUNNING")
            elif change == "analysis_step":
                state["step_ledger"] = [s for s in state["step_ledger"] if s["step_id"] != "EP01-SC01_ANALYSIS"]
            elif change == "prep_fields":
                state.update(prep_step="ANALYSIS", prep_status="IN_PROGRESS")
            else:
                state["step_ledger"] = [s for s in state["step_ledger"] if s["step_id"] != "EP01_PLAN"]
            with self.subTest(change=change):
                self.assert_error("PREDECESSOR", checks.validate, state)

    def test_asset_targets_follow_the_queue_and_order(self):
        self.assertTrue(checks.validate(asset_state())["ok"])
        state = asset_state()
        state["next_required"] = "CHAR_TYPO"
        self.assert_error("UNKNOWN_TARGET", checks.validate, state)
        state = asset_state()
        state.update(next_required="SCENE_B", asset_substage="SCENE")
        self.assert_error("PREDECESSOR", checks.validate, state)
        state = asset_state()
        state["asset_substage"] = "SCENE"
        self.assert_error("PHASE", checks.validate, state)
        state = asset_state()
        state["asset_queue"][0]["status"] = "DONE"
        state["step_ledger"].append({"step_id": "CHAR_A", "status": "DONE", "delivery_ref": "assets/char-a.md"})
        state.update(next_required="PROP_C", asset_substage="PROP", character_asset_status="DONE")
        self.assert_error("PREDECESSOR", checks.validate, state)

    def test_done_asset_unit_needs_its_step(self):
        state = asset_state()
        state["asset_queue"][0]["status"] = "DONE"
        state.update(next_required="SCENE_B", asset_substage="SCENE", character_asset_status="DONE")
        self.assert_error("PREDECESSOR", checks.validate, state)

    def test_scene_assets_policy_only_needs_the_current_scene(self):
        self.assertTrue(checks.validate(scene_policy_state())["ok"])
        state = scene_policy_state()
        state["asset_queue"][1]["needed_by"].append("EP01-SC01")
        self.assert_error("PREDECESSOR", checks.validate, state)
        state = scene_policy_state()
        del state["asset_queue"][1]["needed_by"]
        self.assert_error("ASSET_SCOPE", checks.validate, state)
        state = scene_policy_state()
        state["step_policy"] = "STRICT"
        self.assert_error("PREDECESSOR", checks.validate, state)

    def test_complete_needs_no_open_asset_units(self):
        state = base.completed()
        state["asset_queue"] = [{"id": "PROP_X", "kind": "PROP", "status": "PENDING"}]
        self.assert_error("PREDECESSOR", checks.validate, state)

    def test_every_pass_needs_its_own_evidence(self):
        state = base.fresh()
        state["step_ledger"][0]["checks"] = {"TEXT": {"status": "PASS", "evidence": "analysis.md#text"},
                                             "INPUT": {"status": "PASS", "scope": "已读原文"}}
        self.assert_error("CHECK_EVIDENCE", checks.validate, state)
        state["step_ledger"][0]["checks"]["INPUT"]["evidence"] = "source.md#L1-L8"
        self.assertTrue(checks.validate(state)["ok"])
        for status in ("BLOCKED", "UNKNOWN", "NOT_RUN", "INVALID"):
            state["step_ledger"][0]["checks"]["INPUT"] = {"status": status, "scope": "no evidence needed"}
            with self.subTest(status=status):
                self.assertTrue(checks.validate(state)["ok"])
        state["step_ledger"][0]["checks"]["MEDIA"] = {"status": "MAYBE"}
        self.assert_error("ENUM", checks.validate, state)
        state = base.completed()
        state["coverage_ledger"][0]["checks"]["INPUT"] = {"status": "PASS", "scope": "assets read"}
        self.assert_error("CHECK_EVIDENCE", checks.validate, state)

    @unittest.skipUnless(ARCHIVE.is_dir(), "0.4.1 archive not present")
    def test_archived_run_fails_only_on_the_known_evidence_gap(self):
        for path in sorted(ARCHIVE.glob("turn-*/after-state.json")):
            state = checks.load_json(path)
            with self.subTest(turn=path.parent.name):
                self.assert_error("CHECK_EVIDENCE", checks.validate, copy.deepcopy(state))
                patched = 0
                for record in state["step_ledger"] + state["coverage_ledger"]:
                    for item in (record.get("checks") or {}).values():
                        evidence = item.get("evidence") if isinstance(item, dict) else None
                        if isinstance(item, dict) and item.get("status") == "PASS" and not (isinstance(evidence, str) and evidence.strip()):
                            item["evidence"] = "patched-for-regression"
                            patched += 1
                self.assertGreater(patched, 0)
                self.assertTrue(checks.validate(state)["ok"])

    def test_previous_source_version_only_for_delivered_chains(self):
        state = base.completed()
        state["source_script_ref"].update(version="SRC-2", previous_versions=["SRC-1"])
        self.assertTrue(checks.validate(state)["ok"])
        partial = base.populate(base.fresh(), 1)
        partial["source_script_ref"].update(version="SRC-2", previous_versions=[{"version": "SRC-1"}])
        self.assert_error("SOURCE_MAPPING_UNSUPPORTED", checks.validate, partial)
        unlisted = base.completed()
        unlisted["source_script_ref"]["version"] = "SRC-2"
        self.assert_error("SOURCE_MAPPING_UNSUPPORTED", checks.validate, unlisted)


class StateCommandTests(unittest.TestCase):
    assert_error = base.StateBudgetTests.assert_error

    def run_cli(self, *arguments):
        return subprocess.run(PYTHON + [str(ROOT / "scripts/storyboard_checks.py"), *arguments],
                              capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_init_is_valid_and_never_overwrites(self):
        state = checks.initial_state("P1", "SRC-1", "source.md")
        self.assertEqual(75, len(state))
        self.assertEqual(("PROJECT_SETUP", "PROJECT_BASELINE", "CONVERSATION"),
                         (state["phase"], state["next_required"], state["state_storage"]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run-state.json"
            arguments = ("init", "--project-id", "P1", "--source-version", "SRC-1", "--source-location", "source.md",
                         "--output", str(path))
            first = self.run_cli(*arguments)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            before = path.read_bytes()
            self.assertNotEqual(0, self.run_cli(*arguments).returncode)
            self.assertEqual(before, path.read_bytes())
            saved = checks.load_json(path)
            self.assertEqual(("FILE", str(path)), (saved["state_storage"], saved["state_ref"]))

    def test_receipt_never_reports_a_blocked_target_as_done(self):
        made = checks.receipt(base.blocked())
        self.assertIn("目标未完成", made["outcome"])
        self.assertNotIn("已完成", made["text"])
        self.assertIn("blocking_items", made["fields"])
        self.assertIn("全部完成", checks.receipt(base.completed())["outcome"])
        broken = base.completed()
        broken["last_completed_formal"] = 1
        self.assert_error("DERIVED_MISMATCH", checks.receipt, broken)

    def test_summary_reports_head_and_tolerates_stale_state(self):
        view = checks.summary(base.completed())
        self.assertTrue(view["validation"]["ok"])
        self.assertEqual("COMPLETE", view["head"]["next_required"])
        self.assertEqual(3, view["counts"]["coverage_ledger"])
        stale = base.completed()
        stale["last_completed_formal"] = 1
        view = checks.summary(stale)
        self.assertEqual("DERIVED_MISMATCH", view["validation"]["error"]["code"])
        self.assertEqual(3, view["derived"]["last_completed_formal"])

    def test_patch_applies_operations_and_syncs_derived_fields(self):
        state = base.fresh()
        candidate, changed = checks.apply_patch(state, first_delivery_ops(state))
        self.assertEqual((1, 1, "A01"), (candidate["state_seq"], candidate["last_completed_formal"],
                                         candidate["script_cursor"]["anchor_id"]))
        self.assertIn("coverage_ledger", changed)
        self.assertEqual(base.fresh(), state)

    def test_patch_rejections(self):
        state = base.fresh()
        cases = (([{"op": "replace", "path": "/state_seq", "value": 5}], "PATCH_RESERVED"),
                 ([{"op": "replace", "path": "/last_completed_formal", "value": 3}], "PATCH_RESERVED"),
                 ([{"op": "remove", "path": "/coverage_ledger"}], "PATCH_PATH"),
                 ([{"op": "test", "path": "/next_required", "value": "FORMAL_9"}], "PATCH_TEST"),
                 ([{"op": "move", "path": "/phase"}], "PATCH_OP"),
                 ([{"op": "replace", "path": "/next_required", "value": "FORMAL_3"}], "FRONTIER"))
        for operations, code in cases:
            with self.subTest(code=code):
                self.assert_error(code, checks.apply_patch, state, operations)

    def test_patch_cli_commits_once(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "state.json"
            state = base.fresh()
            state.update(state_storage="FILE", delivery_channel="FILE", state_ref=str(path.resolve()))
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            ops = folder / "ops.json"
            ops.write_text(json.dumps(first_delivery_ops(state), ensure_ascii=False), encoding="utf-8")
            arguments = ("patch", "--state", str(path), "--ops", str(ops), "--output", str(folder / "candidate.json"), "--commit")
            result = self.run_cli(*arguments)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)["committed"])
            self.assertEqual(1, checks.load_json(path)["state_seq"])
            self.assertNotEqual(0, self.run_cli(*arguments).returncode)
            self.assertEqual(1, checks.load_json(path)["state_seq"])
            self.assertFalse(path.with_name(path.name + ".lock").exists())


class PromptLintTests(unittest.TestCase):
    def lint_text(self, text, state=None, quotes=(), mapped=False, adapter=False):
        report = lint.Report("adapter" if adapter else "master", "inline")
        lint.lint_master(report, text, state, None, list(quotes), [], None, adapter, mapped)
        return report

    def state(self):
        state = base.fresh()
        state["character_profiles"] = [{"name": "岑雨", "height_cm": 168}]
        return state

    def test_clean_master_passes_without_warnings(self):
        report = self.lint_text(CLEAN_MASTER, self.state(), ["我等你。"], mapped=True)
        self.assertEqual([], report.errors)
        self.assertEqual([], report.warnings)
        self.assertEqual(1, report.metrics["shots"])

    def test_pilot_failure_patterns_are_reported(self):
        dirty = (CLEAN_MASTER.replace("开场状态与本段范围：", "本段为独立生成单元：")
                 .replace("摄影机在岑雨右后方", "摄影机在门内西南侧、岑雨右后方")
                 .replace("门继续转到半开", "门继续转到半开，不复位、不重播前半")
                 .replace("身高168厘米", "身高170厘米")
                 .replace("保留推门手部和门缝细节。", "保留门缝细节。")
                 .replace("时间：0–6秒。", "时间：0–5秒。")
                 .replace("门轴的轻微摩擦声。", "门轴的轻微摩擦声，结束前不预说“灯还亮着。”[待填]"))
        report = self.lint_text(dirty, self.state(), ["我等你。"], mapped=True)
        errors = {e["code"] for e in report.errors}
        warnings = {w["code"] for w in report.warnings}
        self.assertTrue({"HEIGHT_MISSING", "HEIGHT_MISMATCH", "STYLE_MISMATCH", "TOTAL_TIME", "INNER_TIME",
                         "TEMPLATE_PLACEHOLDER"} <= errors, errors)
        self.assertTrue({"LEGACY_LABEL", "META_LANGUAGE", "WORLD_DIRECTION", "PROCESS_NEGATION",
                         "DIALOGUE_UNMAPPED"} <= warnings, warnings)

    def test_missing_dialogue_is_an_error(self):
        report = self.lint_text(CLEAN_MASTER.replace("“我等你。”", "“我等着。”"), self.state(), ["我等你。"], mapped=True)
        self.assertIn("DIALOGUE_MISSING", {e["code"] for e in report.errors})

    def test_asset_identity_and_style_wording(self):
        state = base.fresh()
        state["visual_style"] = "三维动画，哑光材质"
        state["production_settings"]["visual_style"]["selected"] = state["visual_style"]
        text = "【人物视频优化四视图提示词】\n人物身份依据：许宁，24岁，身高168厘米。\n皮肤与真实质感：浅暖肤色。"
        report = lint.Report("asset", "inline")
        lint.lint_asset(report, text, state)
        self.assertTrue({"IDENTITY_SEX_MISSING", "STYLE_DRIFT_RISK"} <= {w["code"] for w in report.warnings})
        report = lint.Report("asset", "inline")
        lint.lint_asset(report, text.replace("24岁", "24岁女性").replace("真实质感", "表面质感"), state)
        self.assertEqual([], report.warnings)

    def test_adapter_carries_the_drift_check(self):
        state = base.fresh()
        state["visual_style"] = "三维动画，哑光材质"
        state["production_settings"]["visual_style"]["selected"] = state["visual_style"]
        text = "开场状态与本段范围：房间空着。\n镜头A（0–4秒）：墙面有明显皮肤纹理。\n"
        report = lint.Report("adapter", "inline")
        lint.lint_master(report, text, state, None, [], [], None, True)
        self.assertEqual([["皮肤纹理"]],
                         [w["terms"] for w in report.warnings if w["code"] == "STYLE_DRIFT_RISK"])
        # The adapter's own instruction not to add pores asks for their absence, so it is not drift.
        report = lint.Report("adapter", "inline")
        lint.lint_master(report, text.replace("墙面有明显皮肤纹理。", "成像干净，不添加胶片颗粒和写实毛孔；墙面平整。"),
                         state, None, [], [], None, True)
        self.assertEqual([], [w for w in report.warnings if w["code"] == "STYLE_DRIFT_RISK"])
        # "不要失去真实质感" asks for the presence; negation governs coordinated objects, not contrast clauses.
        self.assertEqual(["真实质感"], lint.drift_terms("皮肤保留哑光，不要失去真实质感。"))
        self.assertEqual(["毛孔"], lint.drift_terms("不要失去皮肤的毛孔。"))
        self.assertEqual(["皮肤纹理"], lint.drift_terms("无毛孔但皮肤纹理清晰。"))
        self.assertEqual(["皮肤纹理"], lint.drift_terms("无毛孔、皮肤纹理清晰。"))
        self.assertEqual(["皮肤纹理", "毛孔"], lint.drift_terms("无毛孔、皮肤纹理清晰、但保留毛孔。"))
        for negated in ("不能有真实质感", "不呈现真实质感", "不保留毛孔", "不添加毛孔和皮肤纹理"):
            self.assertEqual([], lint.drift_terms(negated), negated)

    def test_format_examples_pass_strict_lint(self):
        text = (ROOT / "references/examples.md").read_text(encoding="utf-8")
        blocks = re.findall(r"<!-- lint:(\w+) -->\s*```text\n(.*?)\n```", text, re.S)
        self.assertEqual(["asset", "asset", "master"], [kind for kind, _ in blocks])
        lines = ["“末班船走了吗？”", "“走了，明早六点还有。”"]
        for kind, body in blocks:
            report = lint.Report(kind, "examples.md")
            if kind == "asset":
                lint.lint_asset(report, body, None)
            else:
                lint.lint_master(report, body, None, None, [l.strip("“”") for l in lines], [], None, False, True)
            with self.subTest(kind=kind):
                self.assertEqual(([], []), (report.errors, report.warnings))

    @unittest.skipUnless((PILOT / "prompts").is_dir() and ARCHIVE.is_dir(), "media pilot records not present")
    def test_pilot_prompts_baseline_vs_optimized(self):
        project = ARCHIVE / "project"

        def run(kind, name):
            result = subprocess.run(PYTHON + [str(ROOT / "scripts/prompt_lint.py"), kind, "--prompt", str(PILOT / "prompts" / name),
                                              "--state", str(project / "run-state.json"), "--source",
                                              str(project / "source/source.md.txt"), "--formal-id", "FORMAL_1"],
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            return {w["code"] for w in json.loads(result.stdout)["warnings"]}

        baseline = run("master", "V1-A-formal1-master-baseline.txt")
        self.assertTrue({"META_LANGUAGE", "PROCESS_NEGATION", "WORLD_DIRECTION", "DIALOGUE_UNMAPPED"} <= baseline)
        self.assertEqual(set(), run("adapter", "V2-A-formal1-optimized.txt"))


def two_scene_state():
    state = base.fresh()
    state["chain_registry"][1]["scene_id"] = "SC02"
    state["segment_plan"][2]["scene_id"] = "SC02"
    return state


class ReviewFixTests(unittest.TestCase):
    """Cases from the 0.5.0 code review and the legacy-project simulation."""
    assert_error = base.StateBudgetTests.assert_error

    def test_seven_recorded_probe_states(self):
        probes = {
            "assets_not_done": (lambda s: s.update(asset_status="UNSET", character_asset_status="UNSET"), "PREDECESSOR"),
            "empty_step_ledger": (lambda s: s.update(step_ledger=[]), "PREDECESSOR"),
            "misspelled_target": (lambda s: s.update(next_required="CHAR_TYPO_??", phase="ASSET_RUNNING"), "UNKNOWN_TARGET"),
            "scene_prep_unfinished": (lambda s: s.update(prep_step="ANALYSIS", prep_status="IN_PROGRESS"), "PREDECESSOR"),
            "baseline_unfinished": (lambda s: s.update(project_status="IN_PROGRESS"), "PREDECESSOR"),
            "input_pass_without_evidence": (lambda s: s["step_ledger"][1].update(
                checks={"INPUT": {"status": "PASS", "scope": "已读原文"}}), "CHECK_EVIDENCE"),
        }
        for name, (mutate, code) in probes.items():
            state = base.fresh()
            mutate(state)
            with self.subTest(probe=name):
                self.assert_error(code, checks.validate, state)
        state = base.fresh()
        state["visual_baseline"]["text"] = "另一套风格文字"
        self.assertTrue(checks.validate(state)["ok"], "semantic difference is left to human review")

    def test_legacy_state_migrates_through_commit(self):
        legacy = base.fresh()
        legacy["step_ledger"][0]["checks"] = {"INPUT": {"status": "PASS", "scope": "已读原文"}}
        self.assert_error("CHECK_EVIDENCE", checks.validate, legacy)
        self.assertEqual("FORMAL_1", checks.derive(legacy)["frontier"])
        self.assertEqual("CHECK_EVIDENCE", checks.summary(legacy)["validation"]["error"]["code"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            legacy.update(state_storage="FILE", delivery_channel="FILE", state_ref=str(path.resolve()))
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            candidate = copy.deepcopy(legacy)
            candidate["step_ledger"][0]["checks"]["INPUT"]["evidence"] = "source.md#L1-L2"
            candidate.update(state_seq=1, transaction_id="migrate-evidence", last_output="STATE_RECOVERY")
            candidate_path = Path(directory) / "candidate.json"
            candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(checks.commit(path, candidate_path, 0)["committed"])
            self.assertTrue(checks.validate(checks.load_json(path))["ok"])

    def test_scene_assets_shared_unit_uses_the_scene_being_prepared(self):
        state = scene_policy_state()
        state["asset_queue"] = [
            {"id": "CHAR_A", "kind": "CHARACTER", "status": "DONE", "needed_by": ["EP01-SC01", "EP01-SC02"]},
            {"id": "SCENE_S", "kind": "SCENE", "status": "PENDING", "needed_by": ["EP01-SC01", "EP01-SC02"]},
            {"id": "CHAR_B", "kind": "CHARACTER", "status": "PENDING", "needed_by": ["EP01-SC02"]},
            {"id": "PROP_C", "kind": "PROP", "status": "PENDING", "needed_by": ["EP01-SC02"]}]
        state.update(phase="ASSET_RUNNING", next_required="SCENE_S", asset_substage="SCENE")
        self.assertTrue(checks.validate(state)["ok"])
        state.update(next_required="PROP_C", asset_substage="PROP")
        self.assert_error("PREDECESSOR", checks.validate, state)

    def test_next_scene_waits_for_planned_segments(self):
        state = base.populate(two_scene_state(), 1)
        state.update(phase="SCENE_PREP", next_required="EP01-SC02_ANALYSIS", scene_id="SC02", awaiting_continue=True)
        self.assert_error("PREDECESSOR", checks.validate, state)
        state = base.populate(two_scene_state(), 2)
        state.update(phase="SCENE_PREP", next_required="EP01-SC02_ANALYSIS", scene_id="SC02", awaiting_continue=True)
        self.assertTrue(checks.validate(state)["ok"])

    def test_strict_formal_waits_for_open_incremental_units(self):
        state = base.fresh()
        state["asset_queue"] = [{"id": "PROP_NEW", "kind": "PROP", "status": "PENDING"}]
        self.assert_error("PREDECESSOR", checks.validate, state)

    def test_receipt_wording_and_patch_safety(self):
        initial = checks.receipt(checks.initial_state("P1", "SRC-1", "source.md"))["outcome"]
        self.assertIn("尚未交付任何单元", initial)
        self.assertNotIn("等待“继续”", initial)
        self.assertIn("本轮交付 EP01_PLAN、EP01-SC01_ANALYSIS",
                      checks.receipt(base.fresh(), ["EP01_PLAN", "EP01-SC01_ANALYSIS"])["outcome"])
        self.assert_error("DELIVERY", checks.receipt, base.fresh(), ["CHAR_NOT_DONE"])
        state = base.fresh()
        self.assert_error("HISTORY_LOSS", checks.apply_patch, state, [{"op": "remove", "path": "/step_ledger/1"},
                                                                       {"op": "remove", "path": "/step_ledger/1"}])
        self.assert_error("PATCH_OP", checks.apply_patch, state, [{"op": "add", "path": "/transition_plan/-"}])

    def test_summary_reports_settings_and_survives_phase_errors(self):
        view = checks.summary(base.fresh())
        self.assertIn("visual_style", view["settings"])
        self.assertEqual("FORMAL_1", view["target_plan"]["formal_id"])
        self.assertEqual(["FORMAL_1"], [p["formal_id"] for p in view["target_prompt_versions"]])
        broken = base.completed()
        broken["phase"] = "FORMAL_RUNNING"
        view = checks.summary(broken)
        self.assertEqual("PHASE", view["derived"]["error"]["code"])
        self.assertFalse(view["validation"]["ok"])


ADAPTER = """风格化三维动画电影。16:9，6秒，无字幕，无BGM。

镜头一（0–3秒）：岑雨站在门前，左手贴着门板。0–3秒，门开始转开，尾音持续1到2秒。
镜头二（3–6秒）：摄影机在岑雨右后方。3–6秒，门转到半开。
声音：0到6秒有轻微门轴声。"""


class LintFixTests(unittest.TestCase):
    def run_lint(self, text, adapter=True, quotes=(), mapped=False, unchecked=()):
        report = lint.Report("adapter" if adapter else "master", "inline")
        lint.lint_master(report, text, None, None, list(quotes), [], None, adapter, mapped, list(unchecked))
        return {e["code"] for e in report.errors}, {w["code"] for w in report.warnings}

    def test_adapter_shots_are_parsed_and_durations_are_not_timecodes(self):
        self.assertEqual((set(), set()), self.run_lint(ADAPTER))
        errors, warnings = self.run_lint(ADAPTER.replace("镜头二（3–6秒）", "镜头二（4–6秒）")
                                         .replace("摄影机在岑雨右后方", "摄影机在北墙前"))
        self.assertIn("SHOT_TIME", errors)
        self.assertIn("WORLD_DIRECTION", warnings)
        self.assertEqual(({"NO_SHOTS_PARSED"}), self.run_lint("风格化三维动画电影。全程一个固定镜头。")[1])

    def test_quotes_heights_and_unchecked_dialogue(self):
        text = CLEAN_MASTER.replace("“我等你。”", "\"前段的原文同上，我等你。\"")
        state = PromptLintTests().state()
        report = lint.Report("master", "inline")
        lint.lint_master(report, text, state, None, ["前段的原文同上，我等你。"], [], None, False, True)
        self.assertEqual(([], []), (report.errors, report.warnings))
        relative = CLEAN_MASTER.replace("身高168厘米，", "身高168厘米，比许舟矮约10厘米，")
        report = lint.Report("master", "inline")
        lint.lint_master(report, relative, state, None, [], [], None, False)
        self.assertEqual([], report.errors)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.md"
            source.write_text("没有引号的一行\n", encoding="utf-8")
            _, _, unchecked = lint.source_quotes(source, base.fresh(), "FORMAL_1")
            self.assertEqual(["EP01-SC01-C01: no source_lines"], unchecked)
        self.assertIn("DIALOGUE_UNCHECKED", self.run_lint(CLEAN_MASTER, False, [], True, unchecked)[1])

    def test_overlaps_pointers_and_confirmed_style(self):
        shot = "摄影机在岑雨右后方胸口高度。"
        report = lint.Report("master", "inline")
        lint.lint_master(report, CLEAN_MASTER.replace(shot, "摄影机在门内西南侧，与前镜动作相接。"), None, None,
                         [], [], None, False)
        directions = [w["term"] for w in report.warnings if w["code"] == "WORLD_DIRECTION"]
        self.assertEqual(["西南侧"], directions)
        self.assertIn("前镜", [w["term"] for w in report.warnings if w["code"] == "META_LANGUAGE"])
        self.assertEqual((set(), set()), self.run_lint(CLEAN_MASTER.replace(shot, shot + "她眼前镜子里映出门缝。"), False))
        report = lint.Report("master", "inline")
        lint.lint_master(report, CLEAN_MASTER.replace(shot, "摄影机承接前一动作，随即停住。"), None, None,
                         [], [], None, False)
        self.assertEqual(["承接"], [w["term"] for w in report.warnings if w["code"] == "META_LANGUAGE"])
        report = lint.Report("master", "inline")
        lint.lint_master(report, CLEAN_MASTER.replace(shot, "摄影机承接上一个镜头停住。"), None, None,
                         [], [], None, False)
        self.assertEqual(["承接"], [w["term"] for w in report.warnings if w["code"] == "META_LANGUAGE"])
        for fine in ("脚步停住，身体承接重量。", "他承接前一位客人的行李。"):
            report = lint.Report("master", "inline")
            lint.lint_master(report, CLEAN_MASTER.replace(shot, fine), None, None, [], [], None, False)
            self.assertEqual([], [w for w in report.warnings if w["code"] == "META_LANGUAGE"], fine)
        style = "克制写实，门内固定光源，不增加原文以外的人物。"
        text = CLEAN_MASTER.replace("克制写实，门内固定光源，保留推门手部和门缝细节。", style)
        state = PromptLintTests().state()
        state["visual_style"] = style
        report = lint.Report("master", "inline")
        lint.lint_master(report, text, state, None, [], [], None, False)
        self.assertEqual(([], []), (report.errors, report.warnings))
        self.assertEqual(["原文"], report.metrics["confirmed_style_terms"])
        report = lint.Report("master", "inline")
        lint.lint_master(report, text, None, None, [], [], None, False)
        self.assertIn("原文", [w["term"] for w in report.warnings])

    def test_cli_output_is_utf8_when_piped(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt = Path(directory) / "p.md"
            prompt.write_text("【人物身份母资产提示词】\n上传母图。", encoding="utf-8")
            # No "-X utf8" here: the script itself must choose UTF-8 for a pipe.
            result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/prompt_lint.py"), "asset",
                                     "--prompt", str(prompt)], capture_output=True, timeout=60)
            found = {w.get("term") for w in json.loads(result.stdout.decode("utf-8"))["warnings"]}
            self.assertTrue({"上传", "母图"} <= found)
            # check_package prints Chinese file paths; it failed to decode before reconfiguring stdout.
            result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/check_package.py")],
                                    capture_output=True, timeout=120)
            self.assertIn("status", json.loads(result.stdout.decode("utf-8")))

    def test_asset_record_wording_is_flagged(self):
        clean = ("【人物视频优化四视图提示词】\n风格化三维动画电影的角色设定板渲染，周文，52岁男性。"
                 "背景是灰白墙面的船坞值班室，墙上只有一只圆钟。光照为左上方窗外的阴天散射光。")
        for leftover in ("背景与他的身份定妆照是同一处真实环境。", "身高172厘米，数值不变。",
                         "适用集场与状态时点：第一集全集。", "当前妆色与伤污只属于本状态。"):
            report = lint.Report("asset", "inline")
            lint.lint_asset(report, clean + leftover, None)
            with self.subTest(leftover=leftover):
                self.assertIn("META_LANGUAGE", {item["code"] for item in report.errors + report.warnings})
        report = lint.Report("asset", "inline")
        lint.lint_asset(report, clean, None)
        self.assertEqual(([], []), (report.errors, report.warnings))

    def test_record_ids_are_flagged(self):
        # sim-4b: an old four-view still carried 造型版本LOOK-1，状态STATE-BASE.
        clean = ("【人物视频优化四视图提示词】\n风格化三维动画电影的角色设定板渲染，周文，52岁男性。"
                 "背景是灰白墙面的船坞值班室，墙上只有一只圆钟。光照为左上方窗外的阴天散射光。")
        for leftover, term in (("造型版本LOOK-1，", "LOOK-1"), ("状态STATE-BASE。", "STATE-BASE"),
                               ("身份同CHAR-ZHOUWEN。", "CHAR-ZHOUWEN"), ("道具PROP_03。", "PROP_03"),
                               ("取自EP01-SC02。", "EP01-SC02"), ("参照SCENE2。", "SCENE2")):
            report = lint.Report("asset", "inline")
            lint.lint_asset(report, clean + leftover, None)
            with self.subTest(leftover=leftover):
                self.assertEqual([term], [item.get("term") for item in report.errors if item["code"] == "RECORD_ID"])
        report = lint.Report("asset", "inline")
        lint.lint_asset(report, clean + "STATEMENT LOOKS CHARACTER PROPS SCENERY。", None)
        self.assertEqual([], [item for item in report.errors if item["code"] == "RECORD_ID"])


class BuildPackageTests(unittest.TestCase):
    def test_file_target_is_refused(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            target = handle.name
        try:
            result = subprocess.run(PYTHON + [str(ROOT / "scripts/build_package.py"), "--output", target],
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("not a directory", result.stderr + result.stdout)
        finally:
            Path(target).unlink()

    def test_package_contains_runtime_files_only(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "skill"
            result = subprocess.run(PYTHON + [str(ROOT / "scripts/build_package.py"), "--output", str(target)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            manifest = json.loads((target / "MANIFEST.json").read_text(encoding="utf-8"))
            names = set(manifest["files"])
            self.assertTrue({"SKILL.md", "references/examples.md", "scripts/storyboard_checks.py",
                             "scripts/prompt_lint.py", "evals/scenarios.md"} <= names)
            self.assertFalse(any(n.startswith(("evals/runs/", "docs/", "tests/", "specs/", "evals/media-pilot/"))
                                 for n in names))
            for name, item in manifest["files"].items():
                self.assertEqual(64, len(item["sha256"]), name)
            again = subprocess.run(PYTHON + [str(ROOT / "scripts/build_package.py"), "--output", str(target)],
                                   capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertNotEqual(0, again.returncode)


if __name__ == "__main__":
    unittest.main()
