"""Best-effort network fetch of the meta dashboard (SOT-2055).

Isolated from analysis/selection so the deterministic path never touches the
network. ``deck_update.py --fetch`` uses this to (re)generate snapshot JSON; the
committed snapshots under ``decks/meta/snapshots`` remain the reproducible input.
"""
from __future__ import annotations

import re
import urllib.request
from typing import List

from tools.meta_snapshot import SOURCE_BASE, parse_daily_html

_INDEX_DATE_RE = re.compile(r'daily/(\d{4}-\d{2}-\d{2})\.html')


def _get(url: str, timeout: float = 25.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ptcg-claude-meta/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def list_available_dates(source: str = SOURCE_BASE) -> List[str]:
    """Return the daily snapshot dates linked from the index page."""
    html = _get(f"{source}/index.html")
    seen: List[str] = []
    for m in _INDEX_DATE_RE.finditer(html):
        d = m.group(1)
        if d not in seen:
            seen.append(d)
    return sorted(seen)


def fetch_daily(date: str, source: str = SOURCE_BASE) -> dict:
    """Fetch and parse a single daily snapshot."""
    html = _get(f"{source}/daily/{date}.html")
    return parse_daily_html(html, date)
