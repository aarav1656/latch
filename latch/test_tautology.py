import ast
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from latch.tautology import (callers_of, changed_symbols, check_proof_test, check_tautology, hunks_from_sources,
                             parse_hunks, rejection_reason, symbols_from_sources, tautology_of)

BASE = '''\
DEFAULT_PREFIX = "v"
LIMITS = (1, 10)


def _clean(text):
    return text.strip()


def parse(text):
    text = _clean(text)
    major, minor = text.split(".")
    return Version(int(major), int(minor))


def unchanged(n):
    return n * 2


class Version:
    SEPARATOR = "."

    def __init__(self, major, minor):
        self.major = major
        self.minor = minor

    def bump(self):
        self.minor += 1
        return self

    def label(self):
        return f"{DEFAULT_PREFIX}{self.major}{self.SEPARATOR}{self.minor}"
'''

HEAD = '''\
DEFAULT_PREFIX = "V"
LIMITS = (1, 10)


def _clean(text):
    return text.strip().lstrip("v")


def parse(text):
    text = _clean(text)
    major, minor = text.split(".")
    return Version(int(major), int(minor))


def unchanged(n):
    return n * 2


class Version:
    SEPARATOR = "."

    def __init__(self, major, minor):
        self.major = major
        self.minor = minor

    def bump(self):
        if self.minor >= 9:
            self.major += 1
            self.minor = 0
        else:
            self.minor += 1
        return self

    def label(self):
        return f"{DEFAULT_PREFIX}{self.major}{self.SEPARATOR}{self.minor}"
'''

API = '''\
from pkg.version import parse


def format_version(text):
    return str(parse(text).label())


def render_all(items):
    return [format_version(i) for i in items]
'''


IDENTITY = ["-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=/dev/null"]


def run(*args, cwd):
    return subprocess.run(["git", *IDENTITY, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def make_repo(root, base_files, head_files):
    """A git repo with two commits; returns (repo, base_sha, head_sha)."""
    root = Path(root)
    run("init", "-q", cwd=root)
    for files in (base_files, head_files):
        for rel, text in files.items():
            if text is None:
                (root / rel).unlink()
                continue
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        run("add", "-A", cwd=root)
        run("commit", "-q", "-m", "c", cwd=root)
        if files is base_files:
            base = run("rev-parse", "HEAD", cwd=root)
    return root, base, run("rev-parse", "HEAD", cwd=root)


def check(source, changed, affected=()):
    info = {"determined": True, "symbols": sorted(changed), "affected": sorted(affected), "files": ["x.py"],
            "reason": None}
    return check_tautology(textwrap.dedent(source), info)


class HunkTests(unittest.TestCase):
    def test_parse_hunks_counts_and_defaults(self):
        diff = "@@ -3 +3,2 @@ def f\n@@ -10,0 +12,3 @@\n@@ -20,4 +25,0 @@\n"
        self.assertEqual(parse_hunks(diff), [((3, 3), (3, 4)), ((10, 9), (12, 14)), ((20, 23), (25, 24))])

    def test_hunks_from_sources(self):
        hunks = hunks_from_sources("a\nb\nc\n", "a\nB\nc\nd\n")
        self.assertEqual(hunks, [((2, 2), (2, 2)), ((4, 3), (4, 4))])


class SymbolMappingTests(unittest.TestCase):
    def symbols(self, base, head):
        return symbols_from_sources(textwrap.dedent(base), textwrap.dedent(head))

    def test_method_body_change_names_method_and_class_not_siblings(self):
        found = symbols_from_sources(BASE, HEAD)
        self.assertEqual(found, {"DEFAULT_PREFIX", "_clean", "Version", "bump"})
        self.assertNotIn("label", found)
        self.assertNotIn("parse", found)

    def test_module_constant_and_tuple_targets(self):
        found = self.symbols("A, B = 1, 2\nC = 3\n", "A, B = 1, 5\nC = 3\n")
        self.assertEqual(found, {"A", "B"})

    def test_class_attribute_change(self):
        base = "class C:\n    LIMIT = 1\n    def f(self):\n        return 1\n"
        head = "class C:\n    LIMIT = 2\n    def f(self):\n        return 1\n"
        self.assertEqual(self.symbols(base, head), {"C", "LIMIT"})

    def test_decorator_change_counts_for_the_function(self):
        base = "@cache\ndef f(x):\n    return x\n"
        head = "@lru_cache\ndef f(x):\n    return x\n"
        self.assertEqual(self.symbols(base, head), {"f"})

    def test_nested_function_names_inner_and_outer(self):
        base = "def outer():\n    def inner():\n        return 1\n    return inner()\n"
        head = "def outer():\n    def inner():\n        return 2\n    return inner()\n"
        self.assertEqual(self.symbols(base, head), {"outer", "inner"})

    def test_deleted_function_is_named_from_the_base_side(self):
        base = "def keep():\n    return 1\n\n\ndef gone():\n    return 2\n"
        head = "def keep():\n    return 1\n"
        self.assertEqual(self.symbols(base, head), {"gone"})

    def test_added_function(self):
        base = "def keep():\n    return 1\n"
        head = "def keep():\n    return 1\n\n\ndef new_one():\n    return 2\n"
        self.assertEqual(self.symbols(base, head), {"new_one"})

    def test_assignment_inside_module_level_if(self):
        base = "import sys\nif sys.platform == 'x':\n    LIMIT = 1\nelse:\n    LIMIT = 2\n"
        head = "import sys\nif sys.platform == 'x':\n    LIMIT = 1\nelse:\n    LIMIT = 3\n"
        self.assertEqual(self.symbols(base, head), {"LIMIT"})

    def test_local_variable_changes_do_not_become_symbols(self):
        base = "def f():\n    x = 1\n    return x\n"
        head = "def f():\n    x = 2\n    return x\n"
        self.assertEqual(self.symbols(base, head), {"f"})

    def test_parse_error_raises_value_error(self):
        with self.assertRaises(ValueError):
            symbols_from_sources("def f(:\n", "def f():\n    pass\n")


class TautologyOfTests(unittest.TestCase):
    def reason(self, expr):
        return tautology_of(ast.parse(expr, mode="eval").body)

    def test_self_comparisons(self):
        self.assertIn("compared with itself", self.reason("x == x"))
        self.assertIn("compared with itself", self.reason("f(a) == f(a)"))
        self.assertIn("compared with itself", self.reason("obj.value is obj.value"))
        self.assertIn("compared with itself", self.reason("v <= v"))

    def test_constants_only(self):
        for expr in ("True", "1 == 1", "'a' in ('a', 'b')", "not False", "[1, 2] == [1, 2]", "1"):
            self.assertIn("constants only", self.reason(expr), expr)

    def test_real_comparisons_are_not_tautologies(self):
        for expr in ("f(a) == 3", "f(a) == f(b)", "x != x", "r.minor == 10", "x is not None", "x < x + 1"):
            self.assertIsNone(self.reason(expr), expr)

    def test_boolean_combinations(self):
        self.assertIsNotNone(self.reason("f(a) == 1 or True"))
        self.assertIsNotNone(self.reason("x == x and y == y"))
        self.assertIsNone(self.reason("x == x and f(a) == 1"))


class PositiveCases(unittest.TestCase):
    CHANGED = {"Version", "bump", "DEFAULT_PREFIX", "_clean"}

    def ok(self, source, changed=None, affected=()):
        result = check(source, changed or self.CHANGED, affected)
        self.assertTrue(result["checked"], result)
        self.assertTrue(result["ok"], result["reason"])
        self.assertIsNone(rejection_reason(result))
        return result

    def test_direct_call_on_changed_class_and_method(self):
        result = self.ok('''
            def test_bump_rolls_over():
                from pkg.version import Version
                v = Version(1, 9)
                v.bump()
                assert (v.major, v.minor) == (2, 0)
        ''')
        self.assertEqual(result["asserted_symbols"], ["Version", "bump"])

    def test_method_on_changed_class_only_through_the_class(self):
        # `label` itself did not change, but Version did, and the object comes from it
        self.ok('''
            def test_label():
                from pkg.version import Version
                assert Version(1, 0).label() == "V1.0"
        ''')

    def test_import_alias_is_resolved(self):
        result = self.ok('''
            def test_alias():
                from pkg.version import Version as V
                assert V(1, 9).bump().major == 2
        ''')
        self.assertIn("Version", result["asserted_symbols"])

    def test_function_alias_resolves_to_the_changed_name(self):
        result = self.ok('''
            def test_alias():
                from pkg.version import _clean as tidy
                assert tidy("v1.2") == "1.2"
        ''')
        self.assertEqual(result["asserted_symbols"], ["_clean"])

    def test_module_alias_attribute(self):
        self.ok('''
            def test_module_alias():
                import pkg.version as ver
                assert ver.Version(1, 9).bump().major == 2
        ''')

    def test_changed_module_constant(self):
        result = self.ok('''
            def test_prefix():
                from pkg.version import DEFAULT_PREFIX
                assert DEFAULT_PREFIX == "V"
        ''')
        self.assertEqual(result["asserted_symbols"], ["DEFAULT_PREFIX"])

    def test_def_use_through_local_variables(self):
        self.ok('''
            def test_chain():
                from pkg.version import Version
                v = Version(1, 9)
                bumped = v.bump()
                nxt = bumped.major + 1
                assert nxt == 3
        ''')

    def test_tuple_unpacking_and_comprehension(self):
        self.ok('''
            def test_many():
                from pkg.version import Version
                a, b = Version(1, 9).bump(), Version(1, 1).bump()
                majors = [x.major for x in (a, b)]
                assert majors == [2, 1]
        ''')

    def test_pytest_raises_around_changed_call(self):
        self.ok('''
            def test_raises():
                import pytest
                from pkg.version import Version
                with pytest.raises(ValueError):
                    Version(1, -1).bump()
        ''')

    def test_pytest_raises_value_through_as_variable(self):
        self.ok('''
            def test_message():
                import pytest
                from pkg.version import Version
                with pytest.raises(ValueError) as info:
                    Version(1, -1).bump()
                assert "negative" in str(info.value)
        ''')

    def test_try_except_pytest_fail_pattern(self):
        result = self.ok('''
            def test_issue():
                import pytest
                from pkg.version import Version
                try:
                    v = Version(1, 9).bump()
                except Exception as error:
                    pytest.fail("Latch expected the issue operation to succeed: " + str(error))
        ''')
        self.assertEqual(result["asserted_symbols"], ["Version", "bump"])

    def test_conditional_pytest_fail(self):
        self.ok('''
            def test_cond():
                import pytest
                from pkg.version import Version
                v = Version(1, 9).bump()
                if v.major != 2:
                    pytest.fail("no rollover")
        ''')

    def test_tautology_next_to_a_real_assert_is_fine(self):
        self.ok('''
            def test_mixed():
                from pkg.version import Version
                v = Version(1, 9).bump()
                assert v == v
                assert v.major == 2
        ''')

    def test_conjunction_with_a_real_part(self):
        self.ok('''
            def test_and():
                from pkg.version import Version
                v = Version(1, 9)
                assert v == v and v.bump().major == 2
        ''')

    def test_helper_defined_in_the_test(self):
        self.ok('''
            def test_helper():
                from pkg.version import Version
                def roll():
                    return Version(1, 9).bump()
                assert roll().major == 2
        ''')

    def test_mutating_call_on_a_container(self):
        self.ok('''
            def test_collect():
                from pkg.version import Version
                seen = []
                seen.append(Version(1, 9).bump().major)
                assert seen == [2]
        ''')

    def test_hasattr_for_an_added_symbol(self):
        self.ok('''
            def test_added():
                import pkg.version as ver
                assert hasattr(ver, "bump")
        ''')

    def test_callers_of_a_changed_helper_count(self):
        self.ok('''
            def test_public_api():
                from pkg.api import format_version
                assert format_version(" v1.2 ") == "V1.2"
        ''', changed={"_clean"}, affected={"parse", "format_version"})


class NegativeCases(unittest.TestCase):
    CHANGED = {"Version", "bump", "DEFAULT_PREFIX", "_clean"}

    def bad(self, source, needle=None, changed=None):
        result = check(source, changed or self.CHANGED)
        self.assertTrue(result["checked"])
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["asserted_symbols"], [])
        self.assertIsNotNone(rejection_reason(result))
        self.assertIn("never asserts on code this change touched", result["reason"])
        if needle:
            self.assertIn(needle, result["reason"])
        return result

    def test_assert_true(self):
        self.bad('''
            def test_a():
                from pkg.version import Version
                Version(1, 9).bump()
                assert True
        ''', "constants only")

    def test_assert_on_itself(self):
        self.bad('''
            def test_a():
                from pkg.version import Version
                v = Version(1, 9).bump()
                assert v == v
        ''', "`v` is compared with itself")

    def test_assert_call_equals_same_call(self):
        self.bad('''
            def test_a():
                from pkg.version import Version
                assert Version(1, 9).bump() == Version(1, 9).bump()
        ''', "compared with itself")

    def test_or_true_escape(self):
        self.bad('''
            def test_a():
                from pkg.version import Version
                assert Version(1, 9).bump().major == 2 or True
        ''')

    def test_only_constants(self):
        self.bad('''
            def test_a():
                expected = 3
                assert expected == 3
                assert [1, 2] == [1, 2]
        ''')

    def test_only_non_changed_symbols(self):
        result = self.bad('''
            def test_a():
                from pkg.version import unchanged
                assert unchanged(2) == 4
                assert len("abc") == 3
        ''')
        self.assertIn("`Version`", result["reason"])

    def test_calls_changed_code_but_never_asserts_on_it(self):
        self.bad('''
            def test_a():
                from pkg.version import Version
                v = Version(1, 9).bump()
                total = 1 + 1
                assert total == 2
        ''')

    def test_raises_around_unrelated_code(self):
        self.bad('''
            def test_a():
                import pytest
                with pytest.raises(ValueError):
                    int("x")
        ''')

    def test_unguarded_pytest_fail(self):
        self.bad('''
            def test_a():
                import pytest
                from pkg.version import Version
                Version(1, 9).bump()
                pytest.fail("always")
        ''')

    def test_pytest_fail_guarded_by_unrelated_condition(self):
        self.bad('''
            def test_a():
                import pytest
                if 1 + 1 != 2:
                    pytest.fail("math")
        ''')

    def test_local_name_shadow_without_dependence(self):
        self.bad('''
            def test_a():
                from pkg.version import Version
                other = 5
                assert other + 1 == 6
        ''')

    def test_without_callers_a_public_api_test_is_rejected(self):
        # documents why head_root matters: _clean changed, the test only calls the unchanged public API
        self.bad('''
            def test_public_api():
                from pkg.api import format_version
                assert format_version(" v1.2 ") == "V1.2"
        ''', changed={"_clean"})


class RepoModeCases(unittest.TestCase):
    """The loop's lenient mode: the diff is a candidate patch that may miss the buggy code."""
    MODULES = {"pkg"}

    def result(self, source, changed=("bump",)):
        info = {"determined": True, "symbols": list(changed), "affected": [], "files": ["x.py"], "reason": None}
        return check_tautology(textwrap.dedent(source), info, self.MODULES)

    def test_assertion_on_unchanged_repo_code_is_accepted(self):
        result = self.result('''
            def test_a():
                from pkg.version import unchanged
                assert unchanged(2) == 4
        ''')
        self.assertTrue(result["ok"], result["reason"])
        self.assertEqual(result["mode"], "repo")
        self.assertEqual(result["asserted_symbols"], ["unchanged"])

    def test_module_import_forms(self):
        for body in ("import pkg\n    assert pkg.version.unchanged(2) == 4",
                     "import pkg.version as v\n    assert v.unchanged(2) == 4",
                     "from pkg import version\n    assert version.unchanged(2) == 4"):
            result = self.result("def test_a():\n    " + body + "\n")
            self.assertTrue(result["ok"], body)

    def test_stdlib_or_local_values_are_still_rejected(self):
        for body in ("import os\n    assert os.sep == '/'", "x = len('abc')\n    assert x == 3",
                     "from pkg.version import unchanged\n    v = unchanged(2)\n    assert v == v"):
            result = self.result("def test_a():\n    " + body + "\n")
            self.assertFalse(result["ok"], body)
            self.assertIn("never asserts on code from the repository", result["reason"])

    def test_repo_modules_lists_importable_top_levels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for rel in ("pkg/__init__.py", "src/lib/__init__.py", "tests/test_a.py", "single.py", "setup.py",
                        "docs/conf.py", ".hidden/x.py"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("")
            from latch.tautology import repo_modules
            self.assertEqual(repo_modules(root), {"pkg", "lib", "single"})


class UncheckedCases(unittest.TestCase):
    def test_undetermined_symbols_never_block(self):
        for changed in (None, {}, {"determined": False, "reason": "no diff"}):
            result = check_tautology("def test_a():\n    assert True\n", changed)
            self.assertFalse(result["checked"])
            self.assertTrue(result["ok"])
            self.assertIsNone(rejection_reason(result))
        self.assertIn("no diff", result["reason"])

    def test_unparseable_test_is_not_this_checks_job(self):
        result = check("def test_a(:\n", {"f"})
        self.assertFalse(result["checked"])
        self.assertTrue(result["ok"])

    def test_no_test_function(self):
        result = check("x = 1\n", {"f"})
        self.assertFalse(result["checked"])
        self.assertTrue(result["ok"])


class RepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def repo(self, base_files, head_files):
        return make_repo(self.tmp.name, base_files, head_files)

    def test_changed_symbols_from_a_real_diff(self):
        repo, base, head = self.repo({"pkg/version.py": BASE}, {"pkg/version.py": HEAD})
        found = changed_symbols(repo, base, head)
        self.assertTrue(found["determined"])
        self.assertEqual(found["symbols"], ["DEFAULT_PREFIX", "Version", "_clean", "bump"])
        self.assertEqual(found["files"], ["pkg/version.py"])

    def test_test_files_and_non_python_are_ignored(self):
        repo, base, head = self.repo(
            {"pkg/version.py": BASE, "tests/test_v.py": "def test_x():\n    assert 1\n", "README.md": "a\n"},
            {"pkg/version.py": HEAD, "tests/test_v.py": "def test_x():\n    assert 2\n", "README.md": "b\n"})
        self.assertEqual(changed_symbols(repo, base, head)["files"], ["pkg/version.py"])

    def test_only_test_files_changed_is_undetermined(self):
        repo, base, head = self.repo({"tests/test_v.py": "def test_x():\n    assert 1\n"},
                                     {"tests/test_v.py": "def test_x():\n    assert 2\n"})
        found = changed_symbols(repo, base, head)
        self.assertFalse(found["determined"])
        self.assertIn("no non-test Python", found["reason"])

    def test_no_diff_is_undetermined(self):
        repo, base, head = self.repo({"pkg/version.py": BASE}, {"pkg/other.py": "X = 1\n"})
        # head adds a file, so make a second repo state with identical commits instead
        found = changed_symbols(repo, head, head)
        self.assertFalse(found["determined"])

    def test_parse_error_in_head_is_undetermined(self):
        repo, base, head = self.repo({"pkg/version.py": BASE}, {"pkg/version.py": "def broken(:\n"})
        found = changed_symbols(repo, base, head)
        self.assertFalse(found["determined"])
        self.assertIn("pkg/version.py", found["reason"])

    def test_changes_outside_any_named_symbol_are_undetermined(self):
        repo, base, head = self.repo({"pkg/m.py": "import os\n\nprint('a')\n"}, {"pkg/m.py": "import os\n\nprint('b')\n"})
        found = changed_symbols(repo, base, head)
        self.assertFalse(found["determined"])
        self.assertIn("not inside any named", found["reason"])

    def test_added_and_deleted_files(self):
        repo, base, head = self.repo({"pkg/old.py": "def gone():\n    return 1\n"},
                                     {"pkg/old.py": None, "pkg/new.py": "def fresh():\n    return 1\n\nK = 2\n"})
        self.assertEqual(changed_symbols(repo, base, head)["symbols"], ["K", "fresh", "gone"])

    def test_callers_are_found_in_head_checkout(self):
        files_base = {"pkg/version.py": BASE, "pkg/api.py": API}
        files_head = {"pkg/version.py": HEAD, "pkg/api.py": API}
        repo, base, head = self.repo(files_base, files_head)
        found = changed_symbols(repo, base, head, head_root=repo)
        self.assertIn("parse", found["affected"])         # calls _clean and Version
        self.assertIn("format_version", found["affected"])  # calls parse (depth 2)
        self.assertIn("render_all", found["affected"])      # depth 3
        self.assertNotIn("unchanged", found["affected"])
        self.assertTrue(set(found["symbols"]).isdisjoint(found["affected"]))

    def test_callers_skip_test_files(self):
        root = Path(self.tmp.name)
        (root / "tests").mkdir()
        (root / "tests" / "test_a.py").write_text("def helper():\n    return bump()\n")
        (root / "pkg.py").write_text("def real():\n    return bump()\n")
        names, overflow = callers_of(root, {"bump"})
        self.assertEqual(names, {"real"})
        self.assertFalse(overflow)

    def test_too_many_callers_is_reported_as_overflow(self):
        root = Path(self.tmp.name)
        (root / "m.py").write_text("\n".join(f"def f{i}():\n    return hot()\n" for i in range(30)))
        names, overflow = callers_of(root, {"hot"}, cap=10)
        self.assertTrue(overflow)

    def test_end_to_end_accepts_and_rejects(self):
        repo, base, head = self.repo({"pkg/version.py": BASE, "pkg/api.py": API},
                                     {"pkg/version.py": HEAD, "pkg/api.py": API})
        good = textwrap.dedent('''
            def test_rollover():
                from pkg.version import Version
                assert Version(1, 9).bump().major == 2
        ''')
        bad = textwrap.dedent('''
            def test_rollover():
                from pkg.version import Version
                v = Version(1, 9)
                v.bump()
                assert v == v
        ''')
        ok = check_proof_test(good, repo, base, head, head_root=repo)
        self.assertEqual((ok["checked"], ok["ok"]), (True, True))
        self.assertEqual(set(ok), {"checked", "changed_symbols", "asserted_symbols", "ok", "reason", "affected_symbols", "mode"})
        self.assertEqual(ok["mode"], "changed")
        rejected = check_proof_test(bad, repo, base, head, head_root=repo)
        self.assertEqual((rejected["checked"], rejected["ok"]), (True, False))
        self.assertIn("compared with itself", rejection_reason(rejected))

    def test_check_proof_test_never_raises_on_a_bad_repo(self):
        result = check_proof_test("def test_a():\n    assert True\n", "/nonexistent/repo", "a", "b")
        self.assertFalse(result["checked"])
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
