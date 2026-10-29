import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(ROOT, "fixture")
RUNS = os.path.join(ROOT, "runs")
SCREEN = os.path.join(ROOT, "screen")
MODELS_JSON = os.path.join(os.path.dirname(ROOT), "research", "token-factory", "models.json")
URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"
MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"
LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
SYSTEM = (
    "Output one Python function and no prose. "
    "It must fail on the flipped source and pass on the restored source. "
    "Call the inputs the two sources disagree on."
)
LIGHTNING_SYSTEM = (
    "One sentence. Name the test that still passes when the changed line is wrong. No code."
)
SOURCE_NAME = "billing.py"
SUITE_NAME = "test_suite.py"

sys.path.insert(0, os.path.join(ROOT, "harness"))
from parse import extract_function  # noqa: E402


def load_key():
    key = os.environ.get("NEBIUS_API_KEY")
    if key:
        return key
    zshrc = os.path.expanduser("~/.zshrc")
    if os.path.exists(zshrc):
        with open(zshrc) as f:
            for line in f:
                m = re.match(r"\s*export\s+NEBIUS_API_KEY=(.*)", line)
                if m:
                    return m.group(1).split("#")[0].strip().strip("'\"") or None
    return None


def sh(*args):
    return subprocess.run(
        ["python3", *args], cwd=FIXTURE, capture_output=True, text=True, timeout=60
    )


def is_assertion_failure(result) -> bool:
    text = f"{result.stdout or ''}{result.stderr or ''}"
    return result.returncode != 0 and "AssertionError" in text


def read(name):
    with open(os.path.join(FIXTURE, name)) as f:
        return f.read()


def message_text(message, prose=False):
    content = message.get("content") or ""
    if isinstance(content, list):
        chunks = []
        for block in content:
            if isinstance(block, dict):
                chunks.append(str(block.get("text") or ""))
            else:
                chunks.append(str(block))
        content = "\n".join(chunks)
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    if prose:
        text = content.strip()
        if text.lower().startswith("here's a thinking process"):
            return ""
        return text
    if "def " in content:
        return content
    return f"{reasoning}\n{content}".strip()


def call_model(key, user, model=MODEL, system=SYSTEM, max_tokens=2048, prose=False):
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    ).encode()
    status = None
    for attempt in range(2):
        req = urllib.request.Request(
            URL,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                status = resp.status
                payload = json.loads(resp.read())
                message = payload["choices"][0]["message"]
                content = message_text(message, prose=prose)
                return status, content, payload.get("id")
        except urllib.error.HTTPError as e:
            status = e.code
            if status in (429, 503) and attempt == 0:
                time.sleep(3)
                continue
            return status, None, None
        except TimeoutError:
            return None, None, None
        except urllib.error.URLError:
            return None, None, None
    return status, None, None


def wrap_test(function_source):
    head = re.match(r"\s*(?:async\s+)?def\s+(\w+)\s*\((.*?)\)", function_source)
    fn_name = head.group(1)
    takes_self = head.group(2).split(",")[0].strip() == "self"
    if takes_self:
        body = textwrap.indent(textwrap.dedent(function_source), "    ")
        method = re.sub(r"def\s+\w+", "def test_boundary_kills", body, count=1)
        return (
            "import unittest\nfrom billing import discount_applies, annual_price_cents\n\n\n"
            f"class KillTest(unittest.TestCase):\n{method}\n\n\n"
            "if __name__ == '__main__':\n    unittest.main()\n"
        )
    return (
        "import unittest\nfrom billing import discount_applies, annual_price_cents\n\n\n"
        f"{textwrap.dedent(function_source)}\n\n\n"
        "class KillTest(unittest.TestCase):\n"
        "    def test_boundary_kills(self):\n"
        f"        {fn_name}()\n\n\n"
        "if __name__ == '__main__':\n    unittest.main()\n"
    )


def execute(state, on_step=None):
    def step(name):
        state["step"] = name
        if on_step:
            on_step(name)

    if not os.path.exists(os.path.join(FIXTURE, SOURCE_NAME)):
        state["reason"] = "fixture missing"
        print(state["reason"])
        return 2
    key = load_key()
    if not key:
        state["reason"] = "NEBIUS_API_KEY not found"
        print(state["reason"])
        return 7
    try:
        if "assert discount_applies(10, True) is True" in SYSTEM:
            state["reason"] = "system prompt injects the assertion"
            print(state["reason"])
            return 8
        restored = sh("flip.py", "restore")
        if restored.returncode != 0:
            state["reason"] = "restore failed"
            print(state["reason"])
            return 3
        step("suite")
        weak = sh("-m", "unittest", SUITE_NAME.replace(".py", ""))
        state["weak_green"] = weak.returncode == 0
        if not state["weak_green"]:
            state["reason"] = "suite failed on the restored source"
            state["suite_error"] = (weak.stderr or weak.stdout or "")[-500:]
            print(state["reason"])
            return 5

        restored_src = read(SOURCE_NAME)
        weak_src = read(SUITE_NAME)
        flipped = sh("flip.py", "flip")
        if flipped.returncode != 0:
            state["reason"] = "flip failed"
            print(state["reason"])
            return 3
        flipped_src = read(SOURCE_NAME)
        if flipped_src == restored_src or "seats > 10" not in flipped_src:
            state["reason"] = "flip did not change billing.py"
            print(state["reason"])
            return 3
        step("mutant")
        state["mutant_still_green"] = sh("-m", "unittest", SUITE_NAME.replace(".py", "")).returncode == 0
        if not state["mutant_still_green"]:
            state["reason"] = "weak test already caught the mutant"
            print(state["reason"])
            return 3

        if os.path.exists(MODELS_JSON):
            with open(MODELS_JSON) as f:
                ids = json.load(f).get("nvidia_ids", [])
            if MODEL not in ids:
                state["missing_model_id"] = MODEL
                state["reason"] = f"model id not listed: {MODEL}"
                print(state["reason"])
                return 4

        step("lightning")
        lightning_user = (
            f"Changed billing.py:\n{flipped_src}\n\n"
            f"Original billing.py:\n{restored_src}\n\n"
            f"Tests:\n{weak_src}\n"
        )
        light_status, light_text, _light_id = call_model(
            key,
            lightning_user,
            model=LIGHTNING,
            system=LIGHTNING_SYSTEM,
            max_tokens=2048,
            prose=True,
        )
        state["lightning_status"] = light_status
        state["lightning"] = (light_text or "").strip()[:500]

        step("ultra")
        user = (
            f"Restored billing.py:\n{restored_src}\n\n"
            f"Flipped billing.py:\n{flipped_src}\n\n"
            f"test_suite.py:\n{weak_src}\n"
        )
        status, content, completion_id = call_model(key, user)
        state["http_status"] = status
        state["completion_id"] = completion_id
        if content is None:
            state["reason"] = "timeout" if status is None else f"http {status}"
            print(state["reason"])
            return 6
        try:
            function_source = extract_function(content)
        except ValueError as e:
            state["reason"] = "model returned no function"
            state["model_text"] = (content or "")[:800]
            print(f"parse failure: {e}")
            print(state["model_text"])
            return 8
        state["assertion"] = function_source
        state["restored_src"] = restored_src
        state["flipped_src"] = flipped_src
        step("kill")
        with open(os.path.join(FIXTURE, "test_kill.py"), "w") as f:
            f.write(wrap_test(function_source))

        killed = sh("-m", "unittest", "test_kill")
        state["kill_failed"] = is_assertion_failure(killed)
        sh("flip.py", "restore")
        state["restored_passed"] = sh("-m", "unittest", "test_kill").returncode == 0
        if state["kill_failed"] and state["restored_passed"]:
            state["reason"] = None
            return 0
        if killed.returncode != 0 and not state["kill_failed"]:
            state["reason"] = "flipped run failed without AssertionError"
        else:
            state["reason"] = "kill did not fail on the flip and pass after restore"
        return 9
    finally:
        sh("flip.py", "restore")


def render_screen(state):
    path = os.path.join(SCREEN, "render.py")
    if not os.path.exists(path):
        return
    spec = importlib.util.spec_from_file_location("latch_render", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(os.path.join(SCREEN, "index.html"), "w") as f:
        f.write(mod.render({**state, "assertion": state["assertion"] or ""}))


def main():
    state = {
        "weak_green": None,
        "mutant_still_green": None,
        "kill_failed": False,
        "restored_passed": False,
        "model": MODEL,
        "lightning_model": LIGHTNING,
        "assertion": None,
        "lightning": None,
        "http_status": None,
        "reason": "running",
    }
    render_screen(state)
    code = 1
    try:
        code = execute(state)
    except TimeoutError:
        state["reason"] = "timeout"
        code = 6
    finally:
        if not (state.get("kill_failed") and state.get("restored_passed")):
            state["reason"] = state.get("reason") or "stopped"
        os.makedirs(RUNS, exist_ok=True)
        with open(os.path.join(RUNS, "latest.json"), "w") as f:
            json.dump(state, f, indent=2)
        render_screen(state)
    return code


if __name__ == "__main__":
    sys.exit(main())
