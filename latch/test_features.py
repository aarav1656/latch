"""Offline tests for model-call accounting, step events, the repo map and the revert check."""

import io
import json
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from latch.modelcalls import PRICES_SOURCE_URL, ModelCalls, estimate_cost, total_cost
from latch.prove import prove
from latch.repomap import build_repo_map, file_symbols, parse_selection, symbol_index, validate_selection
from latch.revert import changed_files, is_test_path, make_mutant, revert_check
from latch.run import LIGHTNING, MODEL
from latch.steps import StepLog
from latch.test_prove import ProveRunnerTests

FAIL = "________ test_double ________\nE       AssertionError\nFAILED latch_issue_test.py::test_double - AssertionError\n"
GENERATED = "def test_double():\n    from app import double\n    assert double(2) == 4\n"


class CostTests(unittest.TestCase):
    def test_cost_uses_published_prices_and_is_null_when_unknown(self):
        self.assertEqual(estimate_cost(MODEL, 1_000_000, 1_000_000), 4.0)
        self.assertEqual(estimate_cost(LIGHTNING, 1000, 500), round((1000 * 0.06 + 500 * 0.24) / 1e6, 6))
        self.assertIsNone(estimate_cost(MODEL, None, 5))
        self.assertIsNone(estimate_cost("other/model", 1, 1))
        self.assertTrue(PRICES_SOURCE_URL.startswith("https://"))

    def test_total_ignores_unknown_and_is_null_if_nothing_is_known(self):
        self.assertEqual(total_cost([{"cost_usd": 0.5}, {"cost_usd": None}, {"cost_usd": 0.25}]), 0.75)
        self.assertIsNone(total_cost([{"cost_usd": None}]))
        self.assertIsNone(total_cost([]))


class ModelCallsTests(unittest.TestCase):
    def test_records_role_model_ids_tokens_latency_and_cost(self):
        def fn(key, user, model=None, meta=None, on_retry=None, **kw):
            meta.update(prompt_tokens=100, completion_tokens=10, latency_ms=42, status=200)
            return 200, "ok", "cmpl-1"

        calls = ModelCalls(fn, uses_meta=True)
        self.assertEqual(calls.ask("fixer")("k", "u", model=MODEL), (200, "ok", "cmpl-1"))
        entry = calls.calls[0]
        self.assertEqual({k: entry[k] for k in ("role", "model", "prompt_tokens", "completion_tokens", "latency_ms", "completion_id")},
                         {"role": "fixer", "model": MODEL, "prompt_tokens": 100, "completion_tokens": 10,
                          "latency_ms": 42, "completion_id": "cmpl-1"})
        self.assertEqual(entry["cost_usd"], estimate_cost(MODEL, 100, 10))
        self.assertEqual(calls.summary()["model_prices_source"], PRICES_SOURCE_URL)

    def test_stub_without_meta_records_latency_and_null_cost(self):
        calls = ModelCalls(lambda key, user, model=None, **kw: (200, "x", "c"), uses_meta=False)
        calls.ask("triage")("k", "u", model=LIGHTNING, system="s")
        entry = calls.calls[0]
        self.assertIsNone(entry["prompt_tokens"])
        self.assertIsNone(entry["cost_usd"])
        self.assertIsInstance(entry["latency_ms"], int)

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(ValueError):
            ModelCalls(lambda *a, **k: None).ask("nope")


class CallModelMetaTests(unittest.TestCase):
    def test_meta_gets_usage_and_latency(self):
        from latch import run
        body = json.dumps({"id": "c1", "choices": [{"message": {"content": "hi"}}],
                           "usage": {"prompt_tokens": 7, "completion_tokens": 3}}).encode()
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = body
        response.__enter__.return_value = response
        meta = {}
        with mock.patch("latch.run.urllib.request.urlopen", return_value=response):
            self.assertEqual(run.call_model("k", "u", meta=meta), (200, "hi", "c1"))
        self.assertEqual((meta["prompt_tokens"], meta["completion_tokens"], meta["status"]), (7, 3, 200))
        self.assertIsInstance(meta["latency_ms"], int)

    def test_meta_on_failure_has_status_and_null_tokens(self):
        from latch import run
        meta = {}
        with mock.patch("latch.run.urllib.request.urlopen",
                        side_effect=urllib.error.HTTPError("u", 402, "x", {}, io.BytesIO(b""))):
            self.assertEqual(run.call_model("k", "u", meta=meta), (402, None, None))
        self.assertEqual(meta["status"], 402)
        self.assertIsNone(meta["prompt_tokens"])


class StepLogTests(unittest.TestCase):
    def test_events_have_the_contract_fields_and_reach_the_sink(self):
        seen = []
        log = StepLog(seen.append)
        log.started("fetch", {"a": 1})
        log.done("fetch")
        log.failed("revert_check", "x")
        self.assertEqual([e["status"] for e in seen], ["started", "done", "failed"])
        self.assertEqual(set(seen[0]), {"step", "status", "ts", "detail"})
        self.assertTrue(seen[0]["ts"].endswith("Z"))
        self.assertTrue(log.has("fetch"))
        with self.assertRaises(ValueError):
            log.emit("x", "weird")


class RepoMapTests(unittest.TestCase):
    def make(self, root):
        root = Path(root)
        (root / "pkg").mkdir()
        (root / "pkg" / "dates.py").write_text(
            "class Booking:\n    def overlaps(self, other):\n        'True if two bookings overlap'\n        return True\n\n"
            "def merge(items, key=None):\n    return items\n")
        (root / "pkg" / "test_dates.py").write_text("def test_x():\n    pass\n")
        (root / "other.py").write_text("def unrelated():\n    pass\n")
        return root

    def test_symbol_index_skips_tests_and_has_qualified_names(self):
        with tempfile.TemporaryDirectory() as temp:
            index = symbol_index(self.make(temp))
        self.assertEqual(sorted(index), ["other.py", "pkg/dates.py"])
        names = [s[0] for s in index["pkg/dates.py"]]
        self.assertEqual(names, ["Booking", "Booking.overlaps", "merge"])
        self.assertEqual(file_symbols("def f(:"), [])

    def test_parse_and_validate_drop_invented_names_and_always_keep_changed_files(self):
        with tempfile.TemporaryDirectory() as temp:
            index = symbol_index(self.make(temp))
        chosen = parse_selection("<think>x</think>- `pkg/dates.py`: merge, Booking.overlaps, ghost_fn\nghost.py: a\n")
        files, dropped = validate_selection(chosen, index, {"other.py"})
        by = {f["path"]: f for f in files}
        self.assertEqual(sorted(by), ["other.py", "pkg/dates.py"])
        self.assertEqual(sorted(by["pkg/dates.py"]["symbols"]), ["Booking.overlaps", "merge"])
        self.assertTrue(by["other.py"]["changed"])
        self.assertIn("ghost.py", dropped)

    def test_build_repo_map_uses_lightning_and_falls_back_when_the_call_fails(self):
        seen = {}

        def ask(key, user, model=None, system=None, **kw):
            seen.update(model=model, user=user)
            return 200, "pkg/dates.py: merge", "cmpl-map"

        with tempfile.TemporaryDirectory() as temp:
            root = self.make(temp)
            result = build_repo_map(ask, "k", root, "merge drops touching bookings", ["pkg/dates.py"])
            failed = build_repo_map(lambda *a, **k: (402, None, None), "k", root, "x", [])
        self.assertEqual((result["status"], result["completion_id"], seen["model"]), ("ok", "cmpl-map", LIGHTNING))
        self.assertIn("pkg/dates.py", result["text"])
        self.assertIn("merge", result["text"])
        self.assertEqual(failed["status"], "unavailable")
        self.assertIn("402", failed["detail"])


class RevertTests(unittest.TestCase):
    def trees(self, root):
        root = Path(root)
        base, head = root / "base", root / "head"
        for d, body in ((base, "def f():\n    return 1\n"), (head, "def f():\n    return 2\n")):
            d.mkdir()
            (d / "app.py").write_text(body)
            (d / ".latch-home").mkdir()
            (d / "test_app.py").write_text("def test_old():\n    pass\n")
        (head / "new_mod.py").write_text("X = 1\n")
        (head / "test_new.py").write_text("def test_new():\n    pass\n")
        return base, head

    def run_check(self, root, fails, **kw):
        base, head = self.trees(root)
        changes = [("M", "app.py"), ("A", "new_mod.py"), ("A", "test_new.py")]
        seen = []

        def run(directory):
            seen.append(directory.name)
            text = (directory / "app.py").read_text()
            return {"returncode": 1 if fails(directory) else 0,
                    "stdout": "________ test_x ________\nE   assert 2 == 1\n" if fails(directory) else "", "stderr": ""}

        result = revert_check(run, "test_x", "def test_x():\n    pass\n", "latch_issue_test.py", head, base, changes,
                              Path(root) / "mut", is_test_path, **kw)
        return result, seen, Path(root) / "mut"

    def test_reverting_the_fix_makes_the_test_fail_again(self):
        with tempfile.TemporaryDirectory() as temp:
            result, seen, mut = self.run_check(temp, lambda d: "return 1" in (d / "app.py").read_text())
            self.assertTrue(result["ok"])
            self.assertEqual(seen, ["revert-fix"])
            self.assertFalse((mut / "revert-fix" / "new_mod.py").exists())  # files the change added are deleted
            self.assertTrue((mut / "revert-fix" / "test_new.py").exists())  # tests the change added are kept
            self.assertFalse((mut / "revert-fix" / ".latch-home").exists())
            self.assertEqual(result["tests_kept"], ["test_new.py"])

    def test_a_test_that_still_passes_without_the_fix_keeps_the_gate_shut(self):
        with tempfile.TemporaryDirectory() as temp:
            result, _, _ = self.run_check(temp, lambda d: False)
        self.assertFalse(result["ok"])
        self.assertIn("did NOT fail", result["summary"])
        self.assertFalse(result["mutants"][0]["failed_as_expected"])

    def test_loop_rewrites_are_reverted_too_and_the_submitted_patch_is_a_second_mutant(self):
        with tempfile.TemporaryDirectory() as temp:
            base, head = self.trees(temp)
            submitted = Path(temp) / "submitted"
            submitted.mkdir()
            (submitted / "app.py").write_text("def f():\n    return 3\n")
            (submitted / "helper.py").write_text("H = 'wrong'\n")
            (head / "helper.py").write_text("H = 'right'\n")
            (base / "helper.py").write_text("H = 'base'\n")
            seen = []

            def run(directory):
                seen.append((directory.name, (directory / "helper.py").read_text()))
                bad = directory.name == "restore-submitted" or "base" in (directory / "helper.py").read_text()
                return {"returncode": 1 if bad else 0, "stdout": "________ test_x ________\nE   assert 1 == 2\n" if bad else "", "stderr": ""}

            result = revert_check(run, "test_x", "def test_x():\n    pass\n", "latch_issue_test.py", head, base,
                                  [("M", "app.py")], Path(temp) / "mut", is_test_path,
                                  loop_files=["helper.py"], submitted_tree=submitted)
        self.assertTrue(result["ok"])
        self.assertEqual([n for n, _ in seen], ["revert-fix", "restore-submitted"])
        self.assertEqual([m["name"] for m in result["mutants"]], ["revert_fix_to_base", "restore_submitted_patch"])

    def test_nothing_to_revert_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base, head = self.trees(temp)
            result = revert_check(lambda d: self.fail("must not run"), "t", "x", "f.py", head, base,
                                  [("M", "test_app.py")], Path(temp) / "m", is_test_path)
        self.assertFalse(result["ok"])
        self.assertFalse(result["ran"])

    def test_changed_files_reads_git_status(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = ProveRunnerTests().make_repo(temp)
            self.assertEqual(changed_files(repo, "HEAD~1", "HEAD"), [("M", "app.py")])


class ProveIntegrationTests(unittest.TestCase):
    def go(self, runner, calls=None, **kw):
        events = []
        with tempfile.TemporaryDirectory() as temp:
            repo = ProveRunnerTests().make_repo(temp)

            def model(key, user, model=None, system=None, meta=None, **k):
                if meta is not None:
                    meta.update(prompt_tokens=10, completion_tokens=2, latency_ms=5)
                if "map a Python repository" in (system or ""):
                    return 200, "app.py: double", "cmpl-map"
                if "triage" in (system or ""):
                    return 200, "REPRODUCES: wrong value", "cmpl-tri"
                return 200, GENERATED, "cmpl-test"

            with mock.patch("latch.prove.load_key", return_value="k"), mock.patch("latch.prove.call_model", side_effect=model):
                result = prove(repo, "HEAD~1", "HEAD", "double(2) returns 5", "python3 -m pytest -q",
                               Path(temp) / "r.json", runner=runner, on_step_event=events.append, **kw)
            saved = json.loads((Path(temp) / "r.json").read_text())
        return result, saved, events

    def runner(self, revert_fails=True):
        def run(snapshot, command):
            if snapshot.name == "base" or (revert_fails and snapshot.name == "revert-fix"):
                return {"returncode": 1, "stdout": FAIL, "stderr": ""}
            return {"returncode": 0, "stdout": "1 passed", "stderr": ""}
        return run

    def test_receipt_has_model_calls_steps_repo_map_triage_and_revert_check(self):
        result, saved, events = self.go(self.runner())
        self.assertTrue(result["proven"])
        self.assertEqual([c["role"] for c in saved["model_calls"]], ["repo_map", "test_writer", "triage"])
        self.assertEqual([c["model"] for c in saved["model_calls"]], [LIGHTNING, MODEL, LIGHTNING])
        self.assertEqual([c["completion_id"] for c in saved["model_calls"]], ["cmpl-map", "cmpl-test", "cmpl-tri"])
        self.assertTrue(all(c["cost_usd"] is not None and c["prompt_tokens"] == 10 for c in saved["model_calls"]))
        self.assertEqual(saved["model_cost_usd"], total_cost(saved["model_calls"]))
        self.assertEqual(saved["model_prices_source"], PRICES_SOURCE_URL)
        self.assertEqual(saved["repo_map"]["status"], "ok")
        self.assertEqual(saved["triage"]["verdict"], "reproduced")
        self.assertTrue(saved["revert_check"]["ok"])
        names = [e["step"] for e in events if e["status"] == "started"]
        for want in ("fetch", "repo_map", "test_writer", "base_run", "head_run", "triage", "revert_check"):
            self.assertIn(want, names)
        self.assertEqual(events[-1]["step"], "verdict")
        self.assertEqual(saved["steps"], events)
        self.assertTrue(all(set(e) == {"step", "status", "ts", "detail"} for e in events))

    def test_a_proof_test_that_still_passes_after_the_revert_is_not_proven(self):
        result, saved, events = self.go(self.runner(revert_fails=False))
        self.assertFalse(result["proven"])
        self.assertIn("revert check failed", saved["why_not_proven"])
        self.assertIn(("revert_check", "failed"), [(e["step"], e["status"]) for e in events])

    def test_revert_can_be_disabled_and_models_can_be_skipped(self):
        result, saved, _ = self.go(self.runner(revert_fails=False), revert=False, triage=False, repo_map=False)
        self.assertTrue(result["proven"])
        self.assertEqual([c["role"] for c in saved["model_calls"]], ["test_writer"])
        self.assertEqual(saved["revert_check"], {"ran": False, "skipped": "revert check disabled"})

    def test_named_verdict_fields_and_proven_back_compat(self):
        result, saved, events = self.go(self.runner())
        self.assertEqual(saved["verdict"], "VALIDATED")
        self.assertTrue(saved["proven"] and result["proven"])  # proven == (verdict == VALIDATED)
        self.assertEqual(len(saved["base_sha"]), 40)
        self.assertNotEqual(saved["base_sha"], saved["head_sha"])
        self.assertIn("red on base", saved["verdict_reason"])
        self.assertIn("AssertionError", saved["verdict_logs"]["base"])
        detail = events[-1]["detail"]
        self.assertEqual(events[-1]["step"], "verdict")
        self.assertEqual(detail, {"verdict": "VALIDATED", "reason": saved["verdict_reason"]})  # contract with latch-web

    def test_surviving_revert_is_mutation_survived_and_not_proven(self):
        result, saved, events = self.go(self.runner(revert_fails=False))
        self.assertEqual((saved["verdict"], saved["proven"]), ("MUTATION_SURVIVED", False))
        self.assertEqual(events[-1]["detail"], {"verdict": "MUTATION_SURVIVED", "reason": saved["verdict_reason"]})

    def test_green_on_base_is_no_regression_found(self):
        green = lambda snapshot, command: {"returncode": 0, "stdout": "1 passed", "stderr": ""}
        result, saved, _ = self.go(green)
        self.assertEqual((saved["verdict"], saved["proven"]), ("NO_REGRESSION_FOUND", False))

    def test_collection_error_is_invalid_test(self):
        broken = lambda snapshot, command: {"returncode": 2, "stdout": "ERROR collecting latch_issue_test.py\nImportError", "stderr": ""}
        result, saved, _ = self.go(broken)
        self.assertEqual((saved["verdict"], saved["proven"]), ("INVALID_TEST", False))

    def test_still_red_on_head_is_fix_fails_test(self):
        red = lambda snapshot, command: {"returncode": 1, "stdout": FAIL, "stderr": ""}
        result, saved, _ = self.go(red)
        self.assertEqual((saved["verdict"], saved["proven"]), ("FIX_FAILS_TEST", False))

    def test_flake_check_reruns_both_sides_and_stable_runs_stay_validated(self):
        calls = []
        base_run = self.runner()

        def counting(snapshot, command):
            calls.append(snapshot.name)
            return base_run(snapshot, command)

        result, saved, events = self.go(counting)
        self.assertEqual((calls.count("base"), calls.count("head")), (5, 5))
        self.assertEqual(saved["verdict"], "VALIDATED")
        self.assertEqual((saved["flaky"]["runs"], saved["flaky"]["flaky"], saved["flaky"]["flake_rate"]), (5, False, 0.0))
        started = [e["detail"] for e in events if e["step"] == "flake_check" and e["status"] == "started"]
        self.assertEqual(started, [{"runs": 5}])
        self.assertIn(("flake_check", "done"), [(e["step"], e["status"]) for e in events])

    def test_a_head_that_fails_once_in_five_is_flaky_and_stops_before_the_revert_check(self):
        head_calls = []

        def run(snapshot, command):
            if snapshot.name == "base":
                return {"returncode": 1, "stdout": FAIL, "stderr": ""}
            head_calls.append(1)
            return {"returncode": 1 if len(head_calls) == 3 else 0, "stdout": FAIL if len(head_calls) == 3 else "1 passed", "stderr": ""}

        result, saved, events = self.go(run)
        self.assertEqual((saved["verdict"], saved["proven"], result["proven"]), ("FLAKY", False, False))
        self.assertTrue(saved["flaky"]["flaky"])
        self.assertEqual(saved["flaky"]["head_pass_rate"], 0.8)
        self.assertEqual(saved["flaky"]["flake_rate"], 0.1)
        self.assertFalse(saved["revert_check"]["ran"])
        self.assertIn(("flake_check", "failed"), [(e["step"], e["status"]) for e in events])
        self.assertNotIn("revert_check", [e["step"] for e in events])
        self.assertEqual(events[-1]["detail"]["verdict"], "FLAKY")

    def test_flaky_beats_no_regression_found(self):
        base_calls = []

        def run(snapshot, command):
            if snapshot.name == "base":
                base_calls.append(1)
                failed = len(base_calls) == 4
                return {"returncode": 1 if failed else 0, "stdout": FAIL if failed else "1 passed", "stderr": ""}
            return {"returncode": 0, "stdout": "1 passed", "stderr": ""}

        _, saved, _ = self.go(run)
        self.assertEqual(saved["verdict"], "FLAKY")

    def test_flake_runs_is_configurable_and_one_disables_it(self):
        calls = []

        def run(snapshot, command):
            calls.append(snapshot.name)
            return self.runner()(snapshot, command)

        _, saved, events = self.go(run, flake_runs=3)
        self.assertEqual((calls.count("base"), calls.count("head"), saved["flaky"]["runs"]), (3, 3, 3))
        _, saved, events = self.go(self.runner(), flake_runs=1)
        self.assertEqual(saved["verdict"], "VALIDATED")
        self.assertIsNone(saved["flaky"])
        self.assertNotIn("flake_check", [e["step"] for e in events])

    def test_invalid_tests_are_not_rerun(self):
        calls = []

        def run(snapshot, command):
            calls.append(1)
            return {"returncode": 2, "stdout": "ERROR collecting latch_issue_test.py\nImportError", "stderr": ""}

        _, saved, _ = self.go(run)
        self.assertEqual((saved["verdict"], len(calls)), ("INVALID_TEST", 2))


if __name__ == "__main__":
    unittest.main()
