"""get_client rebuilds its cached client when the token file changes.

Re-running schwab_auth.py rewrites the token file; a long-running process
(the Streamlit server, the trading dashboard) must pick up the new token
without a restart. We exercise that by faking schwab-py's client builder
and bumping the token file's mtime — no network or real auth involved.
"""
import os

import schwab

from stocks_shared import schwab_live


def _patch_builder(monkeypatch):
    """Replace schwab-py's token-file client builder with a call counter."""
    calls = {"n": 0}

    def _fake_from_token_file(token_path, app_key, app_secret):
        calls["n"] += 1
        return f"client-{calls['n']}"

    monkeypatch.setattr(schwab.auth, "client_from_token_file",
                        _fake_from_token_file)
    return calls


def test_same_mtime_serves_from_cache(tmp_path, monkeypatch):
    calls = _patch_builder(monkeypatch)
    token = tmp_path / "schwab-token.json"
    token.write_text("{}")
    schwab_live._client_cache.clear()

    c1 = schwab_live.get_client("ak", "as", "cb", str(token))
    c2 = schwab_live.get_client("ak", "as", "cb", str(token))

    assert c1 == c2 == "client-1"
    assert calls["n"] == 1   # built once; second call hit the cache


def test_newer_token_file_rebuilds_client(tmp_path, monkeypatch):
    calls = _patch_builder(monkeypatch)
    token = tmp_path / "schwab-token.json"
    token.write_text("{}")
    schwab_live._client_cache.clear()

    assert schwab_live.get_client("ak", "as", "cb", str(token)) == "client-1"

    # Simulate a re-auth: same path, newer mtime.
    token.write_text("{}")
    bump = token.stat().st_mtime + 100
    os.utime(token, (bump, bump))

    assert schwab_live.get_client("ak", "as", "cb", str(token)) == "client-2"
    assert calls["n"] == 2   # rebuilt from the fresh token, no restart needed


def test_token_mtime_tracks_file_changes(tmp_path):
    """token_mtime() is the signal the UI uses to drop cached fetches after
    a re-auth — None when missing, and it changes when the file is rewritten."""
    token = tmp_path / "schwab-token.json"
    assert schwab_live.token_mtime(str(token)) is None
    assert schwab_live.token_mtime("") is None

    token.write_text("{}")
    m1 = schwab_live.token_mtime(str(token))
    assert m1 is not None

    bump = token.stat().st_mtime + 100
    os.utime(token, (bump, bump))
    assert schwab_live.token_mtime(str(token)) != m1
