# Latch fix loop

When Latch's gate stays shut (the proof test fails on a submitted "fix"), a Nemotron coding agent
on Nebius Token Factory rewrites the code and the harness re-runs. The harness, not the model,
decides open or shut. Every iteration lands in a JSON receipt.

```
issue + base (buggy) + head (submitted fix)
  -> Ultra writes ONE proof test from the issue (frozen; the agent can never edit it)
  -> harness: proof test must be RED on base (assertion), repo suite must be GREEN on head
  -> proof test RED on head  => gate SHUT
  -> Lightning triage: does this failure really show the issue? (env/import error => gave_up, no patching)
  -> loop up to N: Ultra gets issue + diff + proof test + pytest output + source, returns whole-file rewrites
       -> harness applies (existing non-test .py files only), runs repo suite + proof test
       -> gate OPEN only if proof test is green AND repo suite is green
  -> gate_open | gave_up (cap reached / not reproducible), receipt written
```

Reused from `latch/`: `prove.archive`, `prove.run_test`, `prove.expected_base_failure`,
`prove.proven`, `run.call_model`, `run.load_key` (NEBIUS_API_KEY from env or `export` in `~/.zshrc`),
`harness.parse.extract_test_function`. Nothing outside `latch/loop/` is modified; the source repo
is never touched (revisions are archived to temp dirs).

Models (only these two are accepted): `nvidia/Nemotron-3-Ultra-550b-a55b` (default; writes the proof
test and the patches) and `nvidia/Nemotron-3_5-Lightning` (triage; also allowed as `--model`).
`/v1/models` on Token Factory lists both.

## Run the demo

**Constructed regression case: hand-written partial fix modelled on common agent behaviour, not an upstream bug.**
(The same sentence is stored as `case_note` in the receipt and the `started` event.) `latch/loop/demo/`
holds a small room-booking module, a hand-written partial fix that patches `overlaps()` and adds one test but
leaves `merge_bookings()` merging back-to-back bookings, and the issue text. All 5 tests in the head suite
are green; the fix is still wrong.

```sh
cd /path/to/nvdia
python3 -m latch.loop demo --prepare      # once: builds the demo git repo, checks git/pytest/key. No model calls.
python3 -m latch.loop demo \
  --receipt latch/runs/loop-demo.json --events latch/runs/loop-demo-events.jsonl
```

stdout is JSONL events, stderr a short human trace, exit status `0` gate_open, `1` gave_up, `2` error
(fail closed), `64` bad arguments. Measured wall time of the second command, 6 consecutive runs from a clean `git archive` of commit `5603db2`
in `/tmp` (includes every API call and all pytest runs, `--prepare` excluded): 19.7, 14.9, 15.8, 17.2, 25.3 and
14.7 s, i.e. 14.7 to 25.3 s; all 6 ended `gate_open` after one fix iteration. This is Token Factory latency on
one day and varies (an earlier pre-fix run took 38.5 s), so treat it as a range, not a guarantee. Saved run:
`latch/runs/loop-demo.json` and `latch/runs/loop-demo-events.jsonl` (run 3 of the 6).

Pytest runs use `COLUMNS=200`, `-rf --tb=short`, and the proof test's failure is classified from its failure section,
so long generated test names no longer break the base-red check. Model-written code runs under `setrlimit`
(CPU 240 s, file size 256 MB, no core dumps; address space and process count on Linux only) plus a 300 s timeout.

Your own repo:

```sh
python3 -m latch.loop run --repo ~/proj --base <buggy-sha> --head <fix-sha> \
  --issue-file issue.txt [--test-command "python3 -m pytest -q"] [--max-iterations 3] \
  [--model nvidia/Nemotron-3-Ultra-550b-a55b] [--proof-test my_test.py] [--no-triage] \
  [--receipt out.json] [--events out.jsonl] [--run-id ID]
```

## Python interface (for the web app)

```python
from latch.loop import run_loop, run_demo, LoopError, ALLOWED_MODELS, DEFAULT_MODEL

receipt = run_loop(
    repo,                       # path to a git repo (never modified)
    base, head,                 # revisions: buggy base, submitted fix
    issue,                      # issue text (expected behavior)
    test_command="python3 -m pytest -q",
    max_iterations=3,           # 0..10
    model=DEFAULT_MODEL,        # fix agent; must be in ALLOWED_MODELS else ValueError
    receipt_path=None,          # also write the receipt JSON here
    on_event=None,              # callable(dict), called per event, synchronously
    proof_test=None,            # pytest function source; skips Ultra generation
    triage=True,                # Lightning fail-closed triage
    run_id=None,
    model_fn=None,              # test stub: (key, user, model=, system=, max_tokens=, prose=) -> (status, text, completion_id)
)  # -> receipt dict; receipt["verdict"] in {"gate_open", "gave_up"}
# raises ValueError for bad arguments (no events), LoopError for infra failure (after an `error` event)

receipt = run_demo(on_event=cb, receipt_path="...")   # same kwargs; builds/reuses the demo repo
```

`run_loop` blocks (~30 s for the demo); call it in a thread or subprocess and forward `on_event`
output to the browser (SSE/websocket). The CLI is the subprocess form: read stdout line by line.

## Events (JSONL on stdout, `--events FILE`, and `on_event`)

Every event has `type`, `ts` (ISO-8601 UTC, `...Z`) and `run_id`. Text fields (`issue`, `diff`,
`pytest_output`, `test`, `model_text`, `reason`) are plain strings clipped to ~20 KB (head + tail kept);
when anything was clipped the event has `"truncated": true` and `"truncated_fields": [...]`.

| type | when | extra fields |
| --- | --- | --- |
| `started` | first | `repo, base, head, issue, test_command, model, test_model, max_iterations` |
| `proof_test` | test generated | `name, test, generated_by, completion_id` |
| `gate_shut` | iteration 0 verdict | `reason, base_red, head_suite_green, head_proof_green, pytest_output` |
| `gate_check` | head already passes everything | `iteration: 0` (followed by `gate_open`, no loop) |
| `triage` | Lightning (or deterministic) check | `verdict` (`reproduced`/`not_reproduced`/`unclear`), `model, completion_id, reason` |
| `iteration_started` | per iteration | `iteration, model` |
| `model_response` | agent replied | `iteration, model, completion_id, model_text` |
| `patch_applied` | files written | `iteration, diff, changed_files` |
| `iteration_result` | harness verdict | `iteration, model, completion_id, diff, pytest_output, verdict` (`gate_open`/`gate_shut`/`invalid_patch`), `detail` |
| `gate_open` / `gave_up` | final | `reason, receipt, receipt_path` |
| `error` | infra failure (missing key, API error, git/pytest crash). Final; exit 2 | `reason`, `receipt_path` |

## Receipt (JSON)

`run_id, repo, base, head, issue, test_command, model, test_model, triage, max_iterations, started_at,
finished_at, proof_test{name,source,generated_by,completion_id}, initial{base_proof, head_proof,
head_suite, base_red, head_suite_green, gate_open}, triage{...}, iterations[{iteration, model,
completion_id, diff, changed_files, pytest_output, proof_returncode, suite_returncode, verdict}],
verdict, reason, final_iteration, receipt_path`.

## Why it fails closed

- The proof test must fail on base with an assertion; otherwise `gave_up` (it cannot judge anything).
- A proof-test failure that is an import/collection/runtime error is not patched; Lightning must also
  confirm the failure reproduces the issue (`unclear` counts as no).
- The model may only rewrite existing non-test `.py` files inside the repo; test edits, new files and
  path escapes are `invalid_patch` (the iteration is spent).
- The repo's own suite must stay green; a patch that fixes the issue by breaking it keeps the gate shut.
- Any HTTP/git/pytest failure is an `error` event and exit 2, never a silent pass.

Caveat: the proof test is generated from the issue by a model, so an over-strict test could be satisfied
only by changing behavior the issue did not ask for. The receipt keeps the test so a human can read it.

## Tests

```sh
python3 -m unittest latch.loop.test_loop -v    # offline: stubbed model, real git + pytest (~50 s)
```
