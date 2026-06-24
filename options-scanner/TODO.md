# Options Scanner — TODO / tech debt

Tracked items to revisit. Not blockers.

## 1. Sanitize `ticker` before building HTML output paths

- **Where:** `options_scanner/main.py` — `_html_path(ticker, mode, args)`
  and its `save_html` / `webbrowser.open` callers.
- **What:** the output HTML filename is derived from the user-supplied
  `ticker` CLI arg. A ticker containing path-traversal or special
  characters (e.g. `../`, an absolute path) could write the report
  outside the intended output directory.
- **Risk:** low — it's a local CLI run by the user with their own
  input. Worth hardening anyway (whitelist to `[A-Z0-9.^-]`, or
  validate before path construction) so a typo/paste can't escape the
  output dir.
- **Surfaced:** PR #22 review 2026-06-04 (pre-existing, not from the PR).

## 2. Replace deprecated `datetime.utcnow()`

- **Where:** `options_scanner/main.py` — the `scan_time` field
  (`_result_envelope()`); grep for any other `utcnow()` uses too.
- **What:** `datetime.utcnow()` is deprecated (Python 3.12+) and slated
  for removal; it emits a DeprecationWarning during the test run.
- **Fix:** use a timezone-aware UTC value, e.g.
  `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.
- **Surfaced:** PR #22 review 2026-06-04 (pre-existing).

## 3. More robust logging for the combined launcher / both apps

- **Where:** `run.py` (repo-root co-launcher) and the logging setup across
  `trading-dashboard/app.py` and the scanner.
- **What:** `run.py` captures both child processes' output and re-emits it
  to one console with `[scanner]` / `[dashboard]` line prefixes. That's a
  stop-gap: no log levels, no timestamps, no per-app files, no rotation —
  everything just interleaves on the console.
- **Fix (revisit):** proper logging — level-controlled/structured logs,
  optional per-app log files (with rotation), and/or `--log-file` /
  `--quiet` options on the launcher. Consider standardizing both apps on
  Python `logging` with a shared config.
- **Surfaced:** 2026-06-06, when line-prefixing was added to `run.py`.
