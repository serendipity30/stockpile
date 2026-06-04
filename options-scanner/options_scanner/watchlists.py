"""Persist named option-scanner watchlists — one JSON file per watchlist.

Curated ticker baskets ("Mega Caps", "Semiconductors", …) live as individual
files under `options-scanner/watchlists/`, so each is independently editable
and shareable, and personal lists stay out of git (only the shipped starters
are tracked; everything else is gitignored).

Each file holds one watchlist:
  name        display name (dedup key, case-insensitive)
  tickers     ["AAPL", "MSFT", ...]
  option_type "Calls" | "Puts" | "Both"
  min_dte, max_dte, min_oi, min_vol, delta_min, delta_max, top_n
  ts          ISO-8601 timestamp (last saved)

The filename is a slug of the name (e.g. "AI Stocks" -> ai-stocks.json) —
purely cosmetic. Dedup is by the `name` field, so renaming or overwriting
never depends on the filename.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

_DIR = Path(__file__).parents[1] / "watchlists"


def _slug(name: str) -> str:
    """Filesystem-friendly slug of a watchlist name."""
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return s or "watchlist"


def _read(path: Path) -> dict | None:
    """Parse one watchlist file, back-filling filter defaults. None if the
    file is corrupt or missing a name/tickers."""
    try:
        e = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(e, dict) or not e.get("name") or not e.get("tickers"):
        return None
    e.setdefault("option_type", "Calls")
    e.setdefault("min_dte",   30)
    e.setdefault("max_dte",   90)
    e.setdefault("min_oi",    25)
    e.setdefault("min_vol",   1)
    e.setdefault("delta_min", 0.10)
    e.setdefault("delta_max", 0.70)
    e.setdefault("top_n",     5)
    return e


def load() -> list[dict]:
    """Return all saved watchlists sorted by name. [] when the folder is
    missing/empty; corrupt or incomplete files are skipped."""
    if not _DIR.is_dir():
        return []
    out = [e for e in (_read(p) for p in _DIR.glob("*.json")) if e is not None]
    out.sort(key=lambda e: e["name"].lower())
    return out


def _path_for(name: str) -> Path | None:
    """Path of the file whose watchlist name matches (case-insensitive)."""
    key = str(name).strip().lower()
    if not key or not _DIR.is_dir():
        return None
    for path in _DIR.glob("*.json"):
        e = _read(path)
        if e and e["name"].strip().lower() == key:
            return path
    return None


def save(entry: dict) -> None:
    """Write a watchlist to its own file. Overwrites the existing file for
    that name (case-insensitive); otherwise creates a fresh <slug>.json."""
    name = str(entry.get("name", "")).strip()
    if not name or not entry.get("tickers"):
        return
    entry = {**entry, "name": name,
             "ts": datetime.now().isoformat(timespec="seconds")}
    _DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(name)
    if path is None:
        # New watchlist: pick a free <slug>.json so we never clobber a
        # different list that happens to share the slug.
        base = _slug(name)
        path = _DIR / f"{base}.json"
        n = 2
        while path.exists():
            path = _DIR / f"{base}-{n}.json"
            n += 1
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")


def delete(name: str) -> None:
    """Delete the watchlist file matching name (case-insensitive). No-op if
    absent."""
    path = _path_for(name)
    if path is not None:
        try:
            path.unlink()
        except Exception:
            pass
