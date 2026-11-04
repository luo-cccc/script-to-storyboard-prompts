"""Behavioral regression of mechanical contracts, using portable synthetic inputs."""
import copy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("storyboard_checks", ROOT / "scripts/storyboard_checks.py")
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)
FIXTURES = ROOT / "evals/fixtures/state-budget"


def fresh():
    return checks.load_json(FIXTURES / "base-state.json")


def populate(state, count=3):
    for n in range(1, count + 1):
        plan = copy.deepcopy(state["segment_plan"][n - 1])
        prompt = state["prompt_versions"][n - 1]
        prompt["status"] = "DONE"
        plan.update(prompt_version=prompt["prompt_version"], budget_version=prompt["budget_version"],
                    delivery_ref=prompt["delivery_ref"], status="DONE",
                    checks={"TEXT": {"status": "PASS", "evidence": "prompts.md synthetic review"}},
                    end_state={"source_formal": n, "door": "half" if n == 1 else "open"})
        state["coverage_ledger"].append(plan)
        state["step_ledger"].append({"step_id": plan["formal_id"], "status": "DONE",
                                     "prompt_version": prompt["prompt_version"], "delivery_ref": prompt["delivery_ref"]})
    sync(state)
    return state


def sync(state):
    derived = checks.derive(state)
    for field in ("last_completed_formal", "script_cursor", "next_chain_unstarted"):
        state[field] = derived[field]
    state["last_frame_snapshot"] = copy.deepcopy(derived["end_state_source"])
    if derived["registry_exhausted"]:
        state.update(phase="COMPLETE", next_required="COMPLETE", awaiting_continue=False)
    else:
        state.update(phase="FORMAL_RUNNING", next_required=derived["frontier"], awaiting_continue=True)
    return derived


def completed():
    return populate(fresh())


def blocked():
    state = completed()
    state["return_to"] = {"request_id": "REQ-1", "phase": "COMPLETE", "next_required": "COMPLETE",
                          "awaiting_continue": False, "episode_id": "EP01", "scene_id": "SC01"}
    state["prompt_versions"][0]["adapters"] = [{"request_id": "REQ-1", "base_prompt_version": "P1",
        "adapter_version": "A1", "lifecycle": "ACTIVE", "text_status": "BLOCKED", "input_status": "PENDING",
        "submission_ref": None}]
    state["blocking_items"] = [{"request_id": "REQ-1", "step_id": "ADAPT_REQ-1", "phase": "FORMAL_RUNNING",
                                "gap": "Missing initial frame", "blocks": ["COMPLETE"]}]
    state["step_ledger"].append({"step_id": "ADAPT_REQ-1", "request_id": "REQ-1", "status": "IN_PROGRESS"})
    state.update(phase="FORMAL_RUNNING", next_required="WAIT_USER", awaiting_continue=False)
    return state


class StateBudgetTests(unittest.TestCase):
    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(checks.CheckError) as caught:
            function(*args, **kwargs)
        self.assertEqual(code, caught.exception.detail["code"])

    def test_base_fixture_and_literal_expected(self):
        state = fresh()
        result = checks.validate(state)
        expected = checks.load_json(FIXTURES / "expected.json")["initial"]
        for key, value in expected.items():
            self.assertEqual(value, result["derived"][key])
        self.assertEqual(75, len(state))
        self.assertEqual([], state["coverage_ledger"])

    def test_partial_chain_two_deliveries_and_disk_resume(self):
        expected = checks.load_json(FIXTURES / "expected.json")
        state = populate(fresh(), 1)
        for key, value in expected["after_first"].items():
            self.assertEqual(value, state[key])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            restored = checks.load_json(path)
        self.assertTrue(checks.validate(restored)["ok"])
        plan = copy.deepcopy(restored["segment_plan"][1])
        restored["prompt_versions"][1]["status"] = "DONE"
        plan.update(prompt_version="P2", budget_version="B2", status="DONE", delivery_ref="prompts.md#formal-2",
                    checks={"TEXT": {"status": "PASS", "evidence": "fixture"}}, end_state={"door": "open"})
        restored["coverage_ledger"].append(plan)
        restored["step_ledger"].append({"step_id": "FORMAL_2", "prompt_version": "P2", "status": "DONE", "delivery_ref": "prompts.md#formal-2"})
        sync(restored)
        for key, value in expected["after_second"].items():
            self.assertEqual(value, restored[key])
        self.assertEqual(2, len(restored["coverage_ledger"]))
        self.assertTrue(checks.validate(restored)["ok"])

    def test_repair_middle_gap_absorbs_valid_suffix(self):
        state = completed()
        state["coverage_ledger"][1]["status"] = "INVALID"
        sync(state)
        self.assertEqual(1, state["last_completed_formal"])
        self.assertEqual("FORMAL_2", state["next_required"])
        self.assertTrue(checks.validate(state)["ok"])
        state["coverage_ledger"][1]["status"] = "DONE"
        derived = sync(state)
        self.assertEqual(3, derived["last_completed_formal"])
        self.assertEqual("FORMAL_3", derived["end_state_formal_id"])
        self.assertEqual(3, derived["end_state_source"]["source_formal"])
        self.assertEqual(3, len(state["coverage_ledger"]))
        self.assertTrue(checks.validate(state)["ok"])

    def test_duplicate_coverage_is_rejected(self):
        state = populate(fresh(), 1)
        state["coverage_ledger"].append(copy.deepcopy(state["coverage_ledger"][0]))
        self.assert_error("DUPLICATE_COVERAGE", checks.validate, state)

    def test_missing_delivery_evidence_is_rejected(self):
        state = populate(fresh(), 1)
        state["coverage_ledger"][0]["delivery_ref"] = None
        self.assert_error("DELIVERY", checks.validate, state)

    def test_missing_text_or_budget_evidence_is_rejected(self):
        state = populate(fresh(), 1)
        state["coverage_ledger"][0]["checks"]["TEXT"]["evidence"] = None
        self.assert_error("TEXT_EVIDENCE", checks.validate, state)
        state = populate(fresh(), 1)
        state["prompt_versions"][0]["budget_status"] = "INVALID"
        self.assert_error("BUDGET_EVIDENCE", checks.validate, state)

    def test_text_evidence_requires_reference_text(self):
        for value in (None, False, True, 0, 1, [], {}, ["review"], {"ref": "review"}, "", " \n", "NONE", " UNKNOWN "):
            with self.subTest(evidence=value):
                state = completed()
                state["coverage_ledger"][0]["checks"]["TEXT"]["evidence"] = value
                self.assert_error("TEXT_EVIDENCE", checks.validate, state)

    def test_plan_does_not_count_as_delivery(self):
        state = fresh()
        state["last_completed_formal"] = 3
        self.assert_error("DERIVED_MISMATCH", checks.validate, state)
        self.assertEqual(0, checks.derive(state)["last_completed_formal"])

    def test_gap_overlap_and_noncanonical_end_rejected(self):
        state = fresh()
        state["segment_plan"][1]["start_cursor"] = state["segment_plan"][0]["start_cursor"]
        self.assert_error("PLAN_GAP", checks.validate, state)
        state = fresh()
        state["script_cursor"]["anchor_id"] = "END"
        self.assert_error("CURSOR_CANONICAL", checks.validate, state)

    def test_timestamp_is_not_source_anchor(self):
        state = fresh()
        state["chain_registry"][0]["anchors"][1]["source_anchor"] = "10秒"
        self.assert_error("SOURCE_ANCHOR", checks.validate, state)

    def test_unknown_source_mapping_refused(self):
        state = fresh()
        state["chain_registry"][1]["source_version"] = "SRC-2"
        self.assert_error("SOURCE_MAPPING_UNSUPPORTED", checks.validate, state)

    def test_cross_episode_same_scene_is_not_reused(self):
        state = fresh()
        state["chain_registry"][1].update(id="EP02-SC01-C01", episode_id="EP02")
        for plan in state["segment_plan"]:
            for field in ("start_cursor", "end_cursor"):
                cursor = plan[field]
                if isinstance(cursor, dict) and cursor["chain_id"] == "EP01-SC01-C02":
                    cursor["chain_id"] = "EP02-SC01-C01"
        state["segment_plan"][2]["episode_id"] = "EP02"
        populate(state, 2)
        self.assertEqual("EP02-SC01-C01", state["script_cursor"]["chain_id"])
        state.update(episode_id="EP02", phase="EPISODE_PLANNING", next_required="EP02_PLAN")
        self.assertTrue(checks.validate(state)["ok"])
        state.update(phase="SCENE_PREP", next_required="EP01-SC01_ANALYSIS")
        self.assert_error("SCENE_SCOPE", checks.validate, state)

    def test_cancel_complete_preserves_production_and_original(self):
        state = blocked()
        original = copy.deepcopy(state)
        candidate = checks.cancel_request(state, "REQ-1", "user-message:cancel-1")
        self.assertEqual(state, original)
        for field in ("coverage_ledger", "script_cursor", "segment_plan", "budget_ref", "last_completed_formal"):
            self.assertEqual(state[field], candidate[field])
        self.assertEqual("COMPLETE", candidate["phase"])
        self.assertEqual("COMPLETE", candidate["next_required"])
        adapter = candidate["prompt_versions"][0]["adapters"][0]
        self.assertEqual("CANCELLED", adapter["lifecycle"])
        self.assertEqual("BLOCKED", adapter["text_status"])
        self.assertFalse(candidate["awaiting_continue"])
        self.assertIsNone(candidate["return_to"])
        self.assert_error("TYPE", checks.cancel_request, candidate, "REQ-1", "same-request")

    def test_cancel_keeps_other_blocker_and_context(self):
        state = blocked()
        state["blocking_items"].append({"request_id": "REQ-2", "step_id": "OTHER", "phase": "FORMAL_RUNNING",
                                        "gap": "Other dependency", "blocks": ["COMPLETE"]})
        candidate = checks.cancel_request(state, "REQ-1", "user-message:cancel")
        self.assertEqual("WAIT_USER", candidate["next_required"])
        self.assertEqual(["REQ-2"], [b["request_id"] for b in candidate["blocking_items"]])
        self.assertEqual("COMPLETE", candidate["return_to"]["next_required"])
        self.assertNotIn("request_id", candidate["return_to"])

    def test_cancel_keeps_edit_lock_and_outer_context(self):
        state = blocked()
        state.update(edit_lock="FORMAL_2", edit_context={"phase": "COMPLETE", "next_required": "COMPLETE"}, phase="EDIT_LOCK")
        state["blocking_items"].append({"request_id": "REQ-2", "step_id": "FORMAL_2", "phase": "FORMAL_RUNNING",
                                        "gap": "Revision incomplete", "blocks": ["FORMAL_2"]})
        candidate = checks.cancel_request(state, "REQ-1", "user-message:cancel")
        self.assertEqual("EDIT_LOCK", candidate["phase"])
        self.assertEqual("WAIT_USER", candidate["next_required"])
        self.assertEqual("FORMAL_2", candidate["edit_lock"])
        self.assertEqual(state["edit_context"], candidate["edit_context"])
        self.assertIsNotNone(candidate["return_to"])

    def test_cancel_preserves_live_media_record(self):
        state = blocked()
        generation = {"task_id": "synthetic-running-task", "provider_status": "RUNNING"}
        state["step_ledger"][6]["generation"] = generation
        candidate = checks.cancel_request(state, "REQ-1", "user-message:cancel")
        self.assertEqual(generation, candidate["step_ledger"][6]["generation"])

    def test_cancel_refuses_unknown_scope_and_nested_return(self):
        state = blocked()
        state["return_to"]["previous_return_to"] = {"phase": "COMPLETE"}
        self.assert_error("NESTED_RETURN_UNSUPPORTED", checks.cancel_request, state, "REQ-1", "user:1")
        state = blocked()
        state["blocking_items"].append({"request_id": "REQ-2", "step_id": "OTHER", "phase": "FORMAL_RUNNING", "gap": "unknown scope"})
        self.assert_error("BLOCK_SCOPE_UNKNOWN", checks.cancel_request, state, "REQ-1", "user:1")

    def test_json_duplicate_nonfinite_and_wrong_types(self):
        self.assert_error("DUPLICATE_KEY", checks.parse_json, '{"a":1,"a":2}')
        for data in ('{"a":NaN}', '{"a":Infinity}', '{"a":1e999}'):
            self.assert_error("NUMBER", checks.parse_json, data)
        for field, value in (("state_seq", True), ("last_completed_formal", "1"), ("phase", []), ("awaiting_continue", 1)):
            state = fresh()
            state[field] = value
            with self.subTest(field=field):
                with self.assertRaises(checks.CheckError):
                    checks.validate(state)

    def test_old_schema_and_unknown_fields_rejected(self):
        state = fresh()
        state["state_version"] = "1.8"
        self.assert_error("STATE_VERSION", checks.validate, state)
        state = fresh()
        state["extra"] = "unexpected"
        self.assert_error("STATE_FIELDS", checks.validate, state)

    def test_confirmed_settings_gate(self):
        state = fresh()
        state["production_settings"]["visual_style"]["status"] = "PENDING"
        self.assert_error("SETTING_EVIDENCE", checks.validate, state)
        state["production_settings_status"] = "WAIT_CONFIRM"
        self.assert_error("SETTINGS_GATE", checks.validate, state)

    def test_budget_fixtures_and_offset_parallel(self):
        state = completed()
        budgets = checks.load_json(FIXTURES / "budgets.json")
        self.assertEqual(3, len(checks.validate(state, budgets)["budgets_checked"]))
        timing = {"parallel": {"basis": "Synthetic simultaneous tracks with delayed start", "tracks": [
            {"offset_s": 0, "timing": {"seconds": 2}},
            {"offset_s": 1.5, "timing": {"sequence": [{"seconds": 1}, {"seconds": 3}]}}
        ]}}
        self.assertEqual(5.5, checks.calculate_timing(timing))

    def test_budget_local_clock_gap_overlap_and_limit(self):
        state = completed()
        base = checks.load_json(FIXTURES / "budgets.json")[1]
        for replacement in (0, 5, 7):
            budget = copy.deepcopy(base)
            budget["shots"][1]["phases"][0]["start_s"] = replacement
            with self.subTest(start=replacement):
                with self.assertRaises(checks.CheckError):
                    checks.check_budget(budget, state)
        budget = copy.deepcopy(base)
        budget["shots"][1]["start_s"] = 6.5
        self.assert_error("TIME_MISMATCH", checks.check_budget, budget, state)
        budget = copy.deepcopy(base)
        budget["target_max_s"] = 9
        self.assert_error("TIME_LIMIT", checks.check_budget, budget, state)

    def test_budget_version_negative_bool_and_speech(self):
        state = completed()
        base = checks.load_json(FIXTURES / "budgets.json")[0]
        budget = copy.deepcopy(base)
        budget["budget_version"] = "wrong"
        self.assert_error("VERSION_MAPPING", checks.check_budget, budget, state)
        for value in (-1, True, float("nan"), float("inf")):
            budget = copy.deepcopy(base)
            budget["duration_s"] = value
            with self.subTest(value=value):
                self.assert_error("NUMBER", checks.check_budget, budget, state)
        budget = copy.deepcopy(base)
        budget["speech_checks"] = [{"speech_id": "SP1", "source_text": "门开了。", "rendered_text": "门开了。"}]
        self.assertEqual(1, checks.check_budget(budget, state)["speech_pairs_checked"])
        budget["speech_checks"][0]["rendered_text"] = "门已经开了。"
        self.assert_error("SPEECH_MISMATCH", checks.check_budget, budget, state)

    def prepare_commit(self, directory):
        path = Path(directory) / "state.json"
        candidate_path = Path(directory) / "candidate.json"
        state = fresh()
        state.update(state_storage="FILE", delivery_channel="FILE", state_ref=str(path.resolve()))
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        candidate = populate(copy.deepcopy(state), 1)
        candidate.update(state_seq=1, transaction_id="fixture-commit-1")
        candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        return path, candidate_path

    def test_commit_success_and_stale_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            path, candidate = self.prepare_commit(directory)
            result = checks.commit(path, candidate, 0)
            self.assertEqual(1, result["state_seq"])
            restored = checks.load_json(path)
            self.assertEqual("A01", restored["script_cursor"]["anchor_id"])
            self.assert_error("STALE_STATE", checks.commit, path, candidate, 0)
            self.assertFalse(path.with_name(path.name + ".lock").exists())

    def test_commit_replace_failure_keeps_previous_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path, candidate = self.prepare_commit(directory)
            original = path.read_bytes()
            with patch.object(checks.os, "replace", side_effect=OSError("synthetic replacement failure")):
                with self.assertRaises(OSError):
                    checks.commit(path, candidate, 0)
            self.assertEqual(original, path.read_bytes())
            self.assertEqual({"state.json", "candidate.json"}, {p.name for p in Path(directory).iterdir()})

    def test_commit_fsync_failure_keeps_previous_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path, candidate = self.prepare_commit(directory)
            original = path.read_bytes()
            with patch.object(checks.os, "fsync", side_effect=OSError("synthetic disk failure")):
                with self.assertRaises(OSError):
                    checks.commit(path, candidate, 0)
            self.assertEqual(original, path.read_bytes())

    def test_commit_lock_and_invalid_candidate_keep_old_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path, candidate = self.prepare_commit(directory)
            original = path.read_bytes()
            lock = path.with_name(path.name + ".lock")
            lock.write_text("fixture other writer", encoding="utf-8")
            self.assert_error("WRITE_LOCK", checks.commit, path, candidate, 0)
            self.assertTrue(lock.exists())
            lock.unlink()
            data = checks.load_json(candidate)
            data["coverage_ledger"].append(copy.deepcopy(data["coverage_ledger"][0]))
            candidate.write_text(json.dumps(data), encoding="utf-8")
            self.assert_error("DUPLICATE_COVERAGE", checks.commit, path, candidate, 0)
            self.assertEqual(original, path.read_bytes())

    def test_commit_retains_request_and_step_history(self):
        for change in ("adapter", "step", "both", "owner", "lifecycle", "decision", "sequence", "step_decision", "step_status"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                candidate_path = Path(directory) / "candidate.json"
                old = checks.cancel_request(blocked(), "REQ-1", "user-message:cancel")
                old.update(state_storage="FILE", state_ref=str(path.resolve()))
                path.write_text(json.dumps(old), encoding="utf-8")
                original = path.read_bytes()
                candidate = copy.deepcopy(old)
                candidate.update(state_seq=2, transaction_id="after-cancellation")
                adapter = candidate["prompt_versions"][0]["adapters"][0]
                step = candidate["step_ledger"][-1]
                if change in ("adapter", "both"):
                    candidate["prompt_versions"][0]["adapters"] = []
                if change in ("step", "both"):
                    candidate["step_ledger"].pop()
                if change == "owner":
                    candidate["prompt_versions"][0]["adapters"] = []
                    adapter["base_prompt_version"] = "P2"
                    candidate["prompt_versions"][1]["adapters"] = [adapter]
                if change == "lifecycle":
                    adapter["lifecycle"] = "ACTIVE"
                if change == "decision":
                    adapter["decision_ref"] = "user-message:different"
                if change == "sequence":
                    adapter["cancelled_at_state_seq"] = 0
                if change == "step_decision":
                    step["decision_ref"] = "user-message:different"
                if change == "step_status":
                    step["status"] = "IN_PROGRESS"
                candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
                self.assert_error("HISTORY_LOSS", checks.commit, path, candidate_path, 1)
                self.assertEqual(original, path.read_bytes())
                self.assertFalse(path.with_name(path.name + ".lock").exists())

    def test_commit_allows_cancellation_and_explicit_step_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            candidate_path = Path(directory) / "candidate.json"
            old = blocked()
            old.update(state_storage="FILE", state_ref=str(path.resolve()))
            old["step_ledger"].append({"step_id": "ASSET_EXTRA", "status": "IN_PROGRESS"})
            path.write_text(json.dumps(old), encoding="utf-8")
            candidate = checks.cancel_request(old, "REQ-1", "user-message:cancel")
            candidate["step_ledger"][-1].update(status="DONE", prompt_version="asset-v1", delivery_ref="asset.md")
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            self.assertTrue(checks.commit(path, candidate_path, 0)["ok"])
            candidate["state_seq"] = 2
            candidate["transaction_id"] = "after-cancellation"
            candidate["step_ledger"][-1]["status"] = "INVALID"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            self.assertTrue(checks.commit(path, candidate_path, 1)["ok"])
            restored = checks.load_json(path)
            self.assertEqual("CANCELLED", restored["prompt_versions"][0]["adapters"][0]["lifecycle"])
            self.assertEqual("INVALID", restored["step_ledger"][-1]["status"])

    def test_commit_cannot_drop_old_step_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path, candidate_path = self.prepare_commit(directory)
            old = checks.load_json(path)
            old["step_ledger"].extend([
                {"step_id": "ASSET_EXTRA", "prompt_version": "asset-v1", "status": "INVALID"},
                {"step_id": "ASSET_EXTRA", "prompt_version": "asset-v2", "status": "DONE", "delivery_ref": "asset-v2.md"}])
            path.write_text(json.dumps(old), encoding="utf-8")
            original = path.read_bytes()
            candidate = checks.load_json(candidate_path)
            candidate["step_ledger"].append(copy.deepcopy(old["step_ledger"][-1]))
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            self.assert_error("HISTORY_LOSS", checks.commit, path, candidate_path, 0)
            self.assertEqual(original, path.read_bytes())

    def test_commit_cleanup_failure_reports_committed(self):
        unlink = Path.unlink
        for operation in ("unlink", "close"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                path, candidate = self.prepare_commit(directory)
                lock = path.with_name(path.name + ".lock")
                closed_fds = []

                def fail_lock_unlink(target, *args, **kwargs):
                    if target == lock:
                        raise OSError("synthetic lock cleanup failure")
                    return unlink(target, *args, **kwargs)

                close = checks.os.close

                def fail_close(fd):
                    closed_fds.append(fd)
                    raise OSError("synthetic close failure")

                output = io.StringIO()
                argv = ["storyboard_checks.py", "commit", "--state", str(path), "--candidate", str(candidate), "--expected-state-seq", "0"]
                target, name, replacement = (Path, "unlink", fail_lock_unlink) if operation == "unlink" else (checks.os, "close", fail_close)
                try:
                    with patch.object(target, name, replacement), patch.object(sys, "argv", argv), redirect_stdout(output):
                        exit_code = checks.main()
                finally:
                    for fd in closed_fds:
                        close(fd)
                result = json.loads(output.getvalue())
                self.assertEqual(0, exit_code, result)
                self.assertTrue(result["ok"])
                self.assertTrue(result["committed"])
                self.assertFalse(result["cleanup_complete"])
                self.assertEqual("CLEANUP_FAILED", result["warnings"][0]["code"])
                self.assertEqual(1, checks.load_json(path)["state_seq"])
                self.assertEqual("A01", checks.load_json(path)["script_cursor"]["anchor_id"])

    def test_commit_failure_keeps_primary_error_and_cleanup_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            path, candidate = self.prepare_commit(directory)
            original = path.read_bytes()
            lock = path.with_name(path.name + ".lock")
            unlink = Path.unlink

            def fail_lock_unlink(target, *args, **kwargs):
                if target == lock:
                    raise OSError("synthetic cleanup failure")
                return unlink(target, *args, **kwargs)

            argv = ["storyboard_checks.py", "commit", "--state", str(path), "--candidate", str(candidate), "--expected-state-seq", "0"]
            output = io.StringIO()
            with patch.object(checks.os, "replace", side_effect=OSError("synthetic replacement failure")), \
                    patch.object(Path, "unlink", fail_lock_unlink), patch.object(sys, "argv", argv), redirect_stdout(output):
                exit_code = checks.main()
            result = json.loads(output.getvalue())
            self.assertEqual(2, exit_code)
            self.assertFalse(result["ok"])
            self.assertFalse(result["committed"])
            self.assertIn("synthetic replacement failure", result["errors"][0]["message"])
            self.assertIn("synthetic cleanup failure", result["warnings"][0]["message"])
            self.assertEqual(original, path.read_bytes())
            self.assertTrue(lock.exists())
            self.assertEqual([], list(Path(directory).glob("*.tmp")))

    def test_cli_check_and_derive_are_read_only(self):
        path = FIXTURES / "base-state.json"
        original = path.read_bytes()
        for command in ("check", "derive"):
            result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(ROOT / "scripts/storyboard_checks.py"), command, "--state", str(path)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])
        self.assertEqual(original, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
