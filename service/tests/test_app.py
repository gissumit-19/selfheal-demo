import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import bulk_get, lookup_segment, to_mps  # noqa: E402


def test_to_mps():
    assert to_mps(100) == pytest.approx(27.78, abs=0.01)


def test_lookup_segment_is_deterministic():
    assert lookup_segment("seg-1") == lookup_segment("seg-1")


def test_bulk_get_full_page():
    ids = [f"seg-{i}" for i in range(50)]
    assert [s["segment_id"] for s in bulk_get(ids)] == ids


async def _refresh_cache(cold: bool):
    await asyncio.sleep(0.5 if cold else 0.01)               # a cold cache is slow to warm up


@pytest.mark.skipif(os.getenv("FLAKY") != "1", reason="flaky scenario not enabled")
def test_eta_cache_refresh():
    """A timing-sensitive test, as found in real suites. To make the demo repeatable it is
    slow (and so times out) on the FIRST attempt of a run, and fast on any re-run, which is
    how a cold-cache flake behaves. FLAKY_ATTEMPT is GitHub's run_attempt, or Jenkins'
    TRIGGERED_BY (the agent's rebuild counts as a re-run)."""
    attempt = os.getenv("FLAKY_ATTEMPT", "1")
    cold = attempt in ("1", "user")
    asyncio.run(asyncio.wait_for(_refresh_cache(cold), timeout=0.2))
