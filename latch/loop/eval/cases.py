"""The eval cases: real, public Python bug-fix commits with a linked issue, plus one hand-built wrong patch each.

Every real fix is an upstream commit (base = its parent, head = the commit itself, tests included).
Every wrong patch is CONSTRUCTED by us (a plausible partial or mistaken fix applied to the same base,
touching only non-test source). No real reverted/superseded attempt was found for these fixes.
`wrong["edits"]` are exact (old, new) string replacements; each `old` must occur exactly once in `file`.
"""

CASES = [
    {
        "id": "cachetools-423",
        "clone": "cachetools",
        "repo": "tkem/cachetools",
        "fix": "bcf9e8176ebe16da58751fce971c98ffe045ede1",
        "issue": 423,
        "pr": None,
        "title": "RRCache.popitem() on an empty cache raises the choice function's exception instead of KeyError",
        "wrong": {
            "file": "src/cachetools/__init__.py",
            "summary": "also convert StopIteration from the choice function (covers next(iter(...)) choosers) but not ValueError from min/max",
            "edits": [("key = self.__choice(self.__keys)\n        except IndexError:",
                       "key = self.__choice(self.__keys)\n        except (IndexError, StopIteration):")],
        },
    },
    {
        "id": "boltons-319",
        "clone": "boltons",
        "repo": "mahmoud/boltons",
        "fix": "8ba3a7fa0d99b73f7f43c1aed82c571b941eecea",
        "issue": 319,
        "pr": None,
        "title": "boltons.timeutils daterange wrong when starting in December with a year step",
        "wrong": {
            "file": "boltons/timeutils.py",
            "summary": "fix the month rollover into December for month-only steps, but not for year steps",
            "edits": [("now = now.replace(year=now.year + y_step + m_y_step,",
                       "now = now.replace(year=now.year + y_step + m_y_step - (1 if cur_month == 0 and not y_step else 0),")],
        },
    },
    {
        "id": "tabulate-180",
        "clone": "python-tabulate",
        "repo": "astanin/python-tabulate",
        "fix": "20c6370d5da2dae89b305bfb6c7f12a0f8b7236c",
        "issue": 180,
        "pr": None,
        "title": "Exception when tabulating empty data and using maxcolwidths",
        "wrong": {
            "file": "tabulate/__init__.py",
            "summary": "guard the empty-data case in tabulate() but not in _wrap_text_to_colwidths()",
            "edits": [("    if maxcolwidths is not None:\n        num_cols = len(list_of_lists[0])\n",
                       "    if maxcolwidths is not None:\n        num_cols = len(list_of_lists[0]) if list_of_lists else 0\n")],
        },
    },
    {
        "id": "tabulate-190",
        "clone": "python-tabulate",
        "repo": "astanin/python-tabulate",
        "fix": "6c48142c0b57ea6108cb1d304b69b90b18748e45",
        "issue": 190,
        "pr": None,
        "title": "maxcolwidths does not preserve line breaks",
        "wrong": {
            "file": "tabulate/__init__.py",
            "summary": "keep line breaks by not wrapping multi-line cells at all",
            "edits": [("wrapped = wrapper.wrap(casted_cell)",
                       "wrapped = casted_cell.split(\"\\n\") if \"\\n\" in casted_cell else wrapper.wrap(casted_cell)")],
        },
    },
    {
        "id": "toolz-602",
        "clone": "toolz",
        "repo": "pytoolz/toolz",
        "fix": "5a7e078c941c990dcaca53ac6920e5d5c0b1475f",
        "issue": 602,
        "pr": 603,
        "title": "partition_all outputs padding tokens on sequences with inaccurate __len__",
        "extra": ["--ignore=bench", "--ignore=toolz/tests/test_package.py"],
        "wrong": {
            "file": "toolz/itertoolz.py",
            "summary": "raise LookupError only when __len__ over-reports, not when it under-reports",
            "edits": [("            yield prev[:len(seq) % n]\n",
                       "            end = len(seq) % n\n"
                       "            if prev[end - 1] is no_pad:\n"
                       "                raise LookupError('The sequence passed to `partition_all` has invalid length')\n"
                       "            yield prev[:end]\n")],
        },
    },
    {
        "id": "packaging-810",
        "clone": "packaging",
        "repo": "pypa/packaging",
        "fix": "16f558722612e8ad637c37f11464d5de62c8bb33",
        "issue": 810,
        "pr": 1097,
        "title": "Specifier greater-than comparison returns incorrect result for a version with dev+local parts",
        "wrong": {
            "file": "src/packaging/specifiers.py",
            "summary": "special-case the issue's example: stop the local-version guard from rejecting only when both versions carry differing dev segments",
            "edits": [("if prospective.local is not None and _base_version(\n            prospective\n        ) == _base_version(spec):",
                       "if (\n            prospective.local is not None\n            and _base_version(prospective) == _base_version(spec)\n            and (prospective.dev is None or spec.dev is None or prospective.dev == spec.dev)\n        ):")],
        },
    },
    {
        "id": "more-itertools-409",
        "clone": "more-itertools",
        "repo": "more-itertools/more-itertools",
        "fix": "62411c1618493f94b16901746c34e72ad415061e",
        "issue": 409,
        "pr": 412,
        "title": "spy: changing the result list changes the returned iterable",
        "wrong": {
            "file": "more_itertools/more.py",
            "summary": "wrap the head in iter() so it looks decoupled, but the iterator still reads the live list",
            "edits": [("return head, chain(head, it)", "return head, chain(iter(head), it)")],
        },
    },
    {
        "id": "click-3360",
        "clone": "click",
        "repo": "pallets/click",
        "fix": "0551bf53588ae87f462d336f24f853a156fefe3a",
        "issue": 3360,
        "pr": 3434,
        "title": "Empty output from HelpFormatter.write_usage for a program without arguments",
        "wrong": {
            "file": "src/click/formatting.py",
            "summary": "emit the prefix line when args are empty, but keep its trailing space",
            "edits": [("        if text_width >= (term_len(usage_prefix) + 20):\n            # The arguments will fit",
                       "        if not args:\n            self.write(usage_prefix)\n            self.write(\"\\n\")\n            return\n\n"
                       "        if text_width >= (term_len(usage_prefix) + 20):\n            # The arguments will fit")],
        },
    },
    {
        "id": "click-3019",
        "clone": "click",
        "repo": "pallets/click",
        "fix": "812b8000f79c1fbb747a2de5114fc74515558857",
        "issue": 3019,
        "pr": 3021,
        "title": "click.prompt and click.confirm argument prompt_suffix no longer works when suffix is empty",
        "wrong": {
            "file": "src/click/termui.py",
            "summary": "fix the empty prompt_suffix rendering in prompt() only, not in confirm()",
            "edits": [("echo(text.rstrip(\" \"), nl=False, err=err)", "echo(text[:-1], nl=False, err=err)"),
                      ("return f(\" \")", "return f(text[-1:])")],
        },
    },
]


# Cases dropped during validation (never run); the reason is part of the record.
DROPPED = [
    {"id": "cachetools-221", "repo": "tkem/cachetools", "fix": "91aa4c63f5716d8717ee2f898a01f40ce26986ae",
     "reason": "no usable constructed wrong patch: the fix changes an expiry-boundary comparison that the repo's own "
               "suite pins in many places, so the only plausible mutation (`<` to `<=` in expire()) turns the base "
               "suite red (14 failures). A wrong patch that keeps the suite green could not be built honestly."},
    {"id": "boltons-4457decc", "repo": "mahmoud/boltons", "fix": "4457decc",
     "reason": "the repo's own pytest_ignore_collect hook defeats --ignore, so the old-commit suite cannot be run cheaply"},
    {"id": "boltons-8177b933", "repo": "mahmoud/boltons", "fix": "8177b933", "reason": "same as boltons-4457decc"},
]

# Real SWE-bench Lite instances (the SWT-Bench Lite instance pool): sympy, version 1.9+ (pure python, runs on the Mac).
# Variants: real = base + the gold source patch; nofix = head is the base itself, so Nemotron writes the fix.
# Oracle = the instance's own test_patch with FAIL_TO_PASS tests selected via -k (never shown to the model).
import json as _json
from pathlib import Path as _Path

SWE_FILE = _Path(__file__).with_name("swe_instances.json")


def swe_cases():
    import re
    out = []
    for r in _json.loads(SWE_FILE.read_text()):
        num = r["instance_id"].rsplit("-", 1)[1]
        out.append({
            "id": r["instance_id"].replace("sympy__sympy-", "sympy-"),
            "swe": True, "clone": "sympy", "repo": r["repo"], "base": r["base_commit"], "fix": None,
            "instance_id": r["instance_id"], "pr": int(num), "issue": None,
            "title": r["problem_statement"].strip().splitlines()[0][:120], "problem_statement": r["problem_statement"],
            "patch": r["patch"], "test_patch": r["test_patch"], "version": r["version"],
            "f2p": _json.loads(r["FAIL_TO_PASS"]),
            "test_files": re.findall(r"^diff --git a/(\S+)", r["test_patch"], re.M),
        })
    return out


CASES = CASES + swe_cases()
