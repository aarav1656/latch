"""Vercel fallback entry: cached receipts only (no live runs).

Vercel functions are short-lived and have no persistent disk, so the live proof
worker, SSE job streams and sandbox cannot run there. This serves the UI, the
recorded Click receipt and any receipt bundled in the deploy, with live runs
switched off (the UI explains that). The real app is the container (Dockerfile).
"""

import os
import sys
from pathlib import Path

os.environ["LATCH_LIVE"] = "0"
os.environ.setdefault("LATCH_DATA", "/tmp/latch-data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from latch.web.app import build_service, make_handler  # noqa: E402

handler = make_handler(build_service(), trust_proxy=True)
