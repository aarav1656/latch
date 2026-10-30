"""Offline tests for the provider switch (nebius default, openrouter dev-only). No network: urlopen and model_fn are mocked."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from latch import provider as providers
from latch import run
from latch.modelcalls import ModelCalls, estimate_cost, total_cost

ULTRA, LIGHT = run.MODEL, run.LIGHTNING


def env(**kw):
    """A clean provider environment: LATCH_PROVIDER unset unless given."""
    base = {k: v for k, v in os.environ.items() if k not in ("LATCH_PROVIDER", "OPENROUTER_API_KEY", "NEBIUS_API_KEY")}
    base.update(kw)
    return mock.patch.dict(os.environ, base, clear=True)


def reply(body):
    response = mock.MagicMock()
    response.status = 200
    response.read.return_value = json.dumps(body).encode()
    response.__enter__.return_value = response
    return response


def http_error(code, headers=None):
    return urllib.error.HTTPError("u", code, "x", headers or {}, io.BytesIO(b""))


class SelectionTests(unittest.TestCase):
    def test_default_is_nebius_and_unchanged(self):
        with env():
            self.assertEqual(providers.current(), "nebius")
            self.assertFalse(providers.is_dev())
            self.assertEqual(providers.url(), "https://api.tokenfactory.nebius.com/v1/chat/completions")
            self.assertEqual(providers.key_env(), "NEBIUS_API_KEY")
            self.assertEqual(providers.resolve_model(ULTRA), "nvidia/Nemotron-3-Ultra-550b-a55b")
            self.assertEqual(providers.resolve_model(LIGHT), "nvidia/Nemotron-3_5-Lightning")
            self.assertEqual(providers.max_tokens_for(2048), 2048)
            self.assertEqual(providers.not_configured(), "NEBIUS_API_KEY is not configured")

    def test_openrouter_mapping_url_key_and_token_floor(self):
        with env(LATCH_PROVIDER="openrouter"):
            self.assertEqual(providers.current(), "openrouter")
            self.assertTrue(providers.is_dev())
            self.assertEqual(providers.url(), "https://openrouter.ai/api/v1/chat/completions")
            self.assertEqual(providers.resolve_model(ULTRA), "nvidia/nemotron-3-ultra-550b-a55b:free")
            self.assertEqual(providers.resolve_model(LIGHT), "nvidia/nemotron-3.5-lightning:free")
            self.assertEqual(providers.max_tokens_for(2048), 16384)
            self.assertEqual(providers.max_tokens_for(32000), 32000)
            self.assertEqual(providers.not_configured(), "OPENROUTER_API_KEY is not configured")

    def test_only_ultra_and_lightning_map_and_bad_provider_is_rejected(self):
        with env(LATCH_PROVIDER="openrouter"):
            for other in ("nvidia/Nemotron-3-Super-120b-a12b", "nvidia/Nemotron-Nano-30B", "meta/llama"):
                with self.assertRaises(ValueError):
                    providers.resolve_model(other)
        with env(LATCH_PROVIDER="bogus"), self.assertRaises(ValueError):
            providers.current()

    def test_provider_flag_overrides_env_and_is_stripped(self):
        with env(LATCH_PROVIDER="nebius"):
            self.assertEqual(providers.take_flag(["--repo", "r", "--provider", "openrouter", "--x"]), ["--repo", "r", "--x"])
            self.assertEqual(providers.current(), "openrouter")
        with env():
            self.assertEqual(providers.take_flag(["--provider=openrouter"]), [])
            self.assertEqual(providers.current(), "openrouter")
        with env():
            self.assertEqual(providers.take_flag(["a"]), ["a"])
            self.assertEqual(providers.current(), "nebius")
        with env(), self.assertRaises(ValueError):
            providers.take_flag(["--provider", "nope"])
        with env(), self.assertRaises(ValueError):
            providers.take_flag(["--provider"])

    def test_load_key_is_provider_specific_and_never_falls_back_across_providers(self):
        with env(LATCH_PROVIDER="openrouter", NEBIUS_API_KEY="fake-nb"):
            self.assertIsNone(run.load_key())
        with env(LATCH_PROVIDER="openrouter", OPENROUTER_API_KEY="fake-or", NEBIUS_API_KEY="fake-nb"):
            self.assertEqual(run.load_key(), "fake-or")
        with env(NEBIUS_API_KEY="fake-nb", OPENROUTER_API_KEY="fake-or"):
            self.assertEqual(run.load_key(), "fake-nb")


class DevPathTests(unittest.TestCase):
    def test_dev_path_and_check_write(self):
        with env(LATCH_PROVIDER="openrouter"):
            self.assertEqual(str(providers.dev_path("latch/runs/latest-proof.json")), "latch/runs/dev/latest-proof-openrouter.json")
            self.assertEqual(providers.check_write("latch/runs/dev/x.json"), "latch/runs/dev/x.json")
            self.assertEqual(providers.check_write("/tmp/elsewhere/r.json"), "/tmp/elsewhere/r.json")
            self.assertIsNone(providers.check_write(None))
            for bad in ("latch/runs/eval-summary.json", "latch/runs/eval/a-real.json", "/x/repo/latch/runs/latest.json",
                        "latch/runs/dev/../eval-summary.json"):
                with self.assertRaises(ValueError, msg=bad):
                    providers.check_write(bad)
        with env():  # nebius is unrestricted
            self.assertEqual(providers.check_write("latch/runs/eval-summary.json"), "latch/runs/eval-summary.json")

    def test_mark_dev(self):
        with env(LATCH_PROVIDER="openrouter"):
            doc = providers.mark_dev({})
        self.assertEqual((doc["provider"], doc["dev_only"]), ("openrouter", True))
        self.assertEqual(doc["note"], "Dev-only run via OpenRouter free tier; not Nebius Token Factory numbers.")
        doc = providers.mark_dev({}, "nebius")
        self.assertEqual(doc, {"provider": "nebius"})


class CallModelTests(unittest.TestCase):
    def call(self, effects, **kw):
        sleeps, retries = [], []
        meta = kw.pop("meta", {})
        with mock.patch("latch.run.urllib.request.urlopen", side_effect=effects) as opened:
            out = run.call_model("k", "u", on_retry=retries.append, sleep=sleeps.append, jitter=lambda: 0.5, meta=meta, **kw)
        return out, sleeps, retries, opened, meta

    @staticmethod
    def sent(opened, n=0):
        request = opened.call_args_list[n].args[0]
        return request.full_url, json.loads(request.data), request.headers

    def test_nebius_request_is_unchanged(self):
        with env(LATCH_PROVIDER="nebius"):
            out, _, _, opened, _ = self.call([reply({"id": "c", "choices": [{"message": {"content": "def f(): pass"}}]})], model=ULTRA)
        url, body, headers = self.sent(opened)
        self.assertEqual(out, (200, "def f(): pass", "c"))
        self.assertEqual(url, "https://api.tokenfactory.nebius.com/v1/chat/completions")
        self.assertEqual((body["model"], body["max_tokens"]), (ULTRA, 2048))
        self.assertEqual(headers["Authorization"], "Bearer k")

    def test_openrouter_request_maps_model_floors_tokens_and_takes_only_content(self):
        message = {"role": "assistant", "content": "def test_x():\n    assert 1\n", "reasoning": "def hidden_reasoning(): ...",
                   "reasoning_content": "def more_reasoning(): ..."}
        with env(LATCH_PROVIDER="openrouter"):
            out, _, _, opened, _ = self.call([reply({"id": "or-1", "choices": [{"message": message}]})], model=ULTRA)
        url, body, _ = self.sent(opened)
        self.assertEqual(url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(body["model"], "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertEqual(body["max_tokens"], 16384)
        self.assertEqual(out, (200, "def test_x():\n    assert 1\n", "or-1"))
        self.assertNotIn("reasoning", out[1])

    def test_openrouter_empty_content_is_not_filled_from_reasoning(self):
        message = {"content": "", "reasoning": "def sneaky(): return 1"}
        with env(LATCH_PROVIDER="openrouter"):
            out, *_ = self.call([reply({"id": "or-2", "choices": [{"message": message}]})], model=LIGHT, prose=True)
        self.assertEqual(out[0], 200)
        self.assertEqual(out[1], "")

    def test_openrouter_429_backs_off_patiently_and_honours_retry_after(self):
        good = reply({"id": "or-3", "choices": [{"message": {"content": "ok"}}]})
        with env(LATCH_PROVIDER="openrouter"):
            out, sleeps, retries, opened, meta = self.call(
                [http_error(429), http_error(429, {"Retry-After": "30"}), good], model=LIGHT)
        self.assertEqual(out, (200, "ok", "or-3"))
        self.assertEqual(sleeps, [4.5, 30.5])  # 4*2^0 + jitter, then Retry-After beats 4*2^1
        self.assertEqual([r["status"] for r in retries], [429, 429])
        self.assertEqual((meta["retries"], meta["retried_statuses"]), (2, [429, 429]))
        self.assertEqual(retries[0]["attempts"], 6)

    def test_openrouter_gives_up_after_six_attempts_and_caps_the_delay(self):
        with env(LATCH_PROVIDER="openrouter"):
            out, sleeps, _, opened, _ = self.call([http_error(429)] * 6, model=LIGHT)
        self.assertEqual(out, (429, None, None))
        self.assertEqual(opened.call_count, 6)
        self.assertEqual(len(sleeps), 5)
        self.assertEqual(sleeps, [4.5, 8.5, 16.5, 32.5, 60.5])

    def test_nebius_retry_policy_is_still_three_attempts_one_second_base(self):
        with env():
            out, sleeps, _, opened, _ = self.call([http_error(429)] * 3, model=LIGHT)
        self.assertEqual((out, opened.call_count, sleeps), ((429, None, None), 3, [1.5, 2.5]))


class ModelCallsTests(unittest.TestCase):
    @staticmethod
    def fake(key, user, model=None, **kw):
        return 200, "x", "cmpl"

    def test_entries_carry_provider_and_resolved_model_nebius(self):
        with env():
            mc = ModelCalls(self.fake)
            mc.ask("fixer")("k", "u", model=ULTRA)
        self.assertEqual((mc.calls[0]["provider"], mc.calls[0]["model"]), ("nebius", ULTRA))

    def test_entries_carry_provider_and_resolved_model_openrouter_and_no_cost(self):
        with env(LATCH_PROVIDER="openrouter"):
            mc = ModelCalls(self.fake)
            mc.ask("triage")("k", "u", model=LIGHT)
            mc.ask("test_writer")("k", "u", model=ULTRA)
        self.assertEqual([(c["provider"], c["model"]) for c in mc.calls],
                         [("openrouter", "nvidia/nemotron-3.5-lightning:free"), ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free")])
        self.assertEqual([c["cost_usd"] for c in mc.calls], [None, None])
        self.assertIsNone(total_cost(mc.calls))

    def test_cost_is_only_estimated_for_nebius(self):
        self.assertEqual(estimate_cost(ULTRA, 1_000_000, 1_000_000), 4.0)
        self.assertIsNone(estimate_cost(ULTRA, 1_000_000, 1_000_000, "openrouter"))

    def test_real_call_model_meta_reports_retries_into_the_entry(self):
        good = reply({"id": "c", "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}})
        with env(LATCH_PROVIDER="openrouter"), mock.patch("latch.run.urllib.request.urlopen", side_effect=[http_error(429), good]), \
                mock.patch("latch.run.time.sleep"):
            mc = ModelCalls()
            self.assertEqual(mc.ask("repo_map")("k", "u", model=LIGHT), (200, "ok", "c"))
        entry = mc.calls[0]
        self.assertEqual((entry["retries"], entry["retried_statuses"], entry["prompt_tokens"]), (1, [429], 5))
        self.assertEqual(entry["provider"], "openrouter")


class MissingKeyTests(unittest.TestCase):
    def test_prove_error_names_the_provider_key(self):
        from latch import prove as prove_module
        with tempfile.TemporaryDirectory() as tmp, env(LATCH_PROVIDER="openrouter"):
            import subprocess
            def g(*a):
                subprocess.run(["git", "-C", tmp, "-c", "user.email=t@e.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                                "-c", "core.hooksPath=/dev/null", *a], check=True, capture_output=True)
            g("init", "-q")
            Path(tmp, "a.py").write_text("x = 1\n")
            g("add", "."), g("commit", "-qm", "a")
            Path(tmp, "a.py").write_text("x = 2\n")
            g("commit", "-qam", "b")
            with mock.patch.object(prove_module, "load_key", return_value=None), \
                    self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY is not configured"):
                prove_module.prove(tmp, "HEAD~1", "HEAD", "x should be 3", "python3 -m pytest -q",
                                   str(Path(tmp, "latch", "runs", "dev", "r.json")))

    def test_prove_refuses_a_public_receipt_path_on_openrouter(self):
        from latch import prove as prove_module
        with env(LATCH_PROVIDER="openrouter"), self.assertRaisesRegex(ValueError, "dev-only"):
            prove_module.prove(".", "HEAD~1", "HEAD", "issue", "python3 -m pytest -q", "latch/runs/latest-proof.json")


if __name__ == "__main__":
    unittest.main()
