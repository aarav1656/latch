"""Step events: {step, status: started|done|failed, ts, detail}, for the web, the CLI and the receipt."""

import datetime

STEPS = ("fetch", "repo_map", "test_writer", "base_run", "head_run", "triage", "fix", "revert_check", "verdict")


def _ts():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class StepLog:
    """Records every step event in `self.events` and forwards it to `sink(event)` when given."""

    def __init__(self, sink=None):
        self.sink = sink
        self.events = []

    def emit(self, step, status, detail=None):
        if status not in ("started", "done", "failed"):
            raise ValueError(f"bad step status {status!r}")
        event = {"step": step, "status": status, "ts": _ts(), "detail": detail}
        self.events.append(event)
        if self.sink:
            self.sink(event)
        return event

    def started(self, step, detail=None):
        return self.emit(step, "started", detail)

    def done(self, step, detail=None):
        return self.emit(step, "done", detail)

    def failed(self, step, detail=None):
        return self.emit(step, "failed", detail)

    def has(self, step):
        return any(e["step"] == step for e in self.events)
