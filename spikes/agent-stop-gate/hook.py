import json
import os
import sys
from pathlib import Path

event = json.load(sys.stdin)
Path(os.environ["LATCH_SPIKE_LOG"]).open("a").write(
    json.dumps({"stop_hook_active": event.get("stop_hook_active")}) + "\n"
)
if os.environ.get("LATCH_SPIKE_ALLOW") != "1" and not event.get("stop_hook_active"):
    print(json.dumps({"decision": "block", "reason": "Run the behavior proof before finishing."}))
