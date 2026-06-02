"""Portfolio tab: upload a brokerage CSV, scan every position.

For each ticker in the CSV: fetch the option chain, filter by DTE/OI/volume/
delta, and surface the rank-1 candidate as an explicit action card. Covered
positions also get a roll-close lookup for the existing short option.

Controls:
  Option type  — Calls / Puts / Both
  Scan mode    — Roll (surface roll candidates) / Best option (just top pick)
  Positions    — Open only (shares > 0) / All tickers (every ticker in CSV)
  Format       — auto-detected on upload; user can override

The tab keeps its CSV validation helpers (_validate_csv, _show_validation)
module-private — they're only meaningful in this upload context.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime

import streamlit as st

from options_scanner.display.iv_chart import show_iv_chart
from options_scanner.display.leaderboard import render_leaderboard
from options_scanner.display.portfolio_action_card import render_portfolio_action_card
from options_scanner.display.scan_results import show_scan_results
from options_scanner.display.spot_meta import (
    fetch_spot_meta,
    spot_help_text,
    spot_value_html,
)
from options_scanner.fetch import fetch_position
from options_scanner.portfolio import detect_brokerage
from options_scanner.ui_theme import badge, metric_card, section_header


@st.cache_data(show_spinner=False)
def _validate_csv(content: bytes, brokerage: str) -> tuple[list, int, str | None, list | None]:
    """Validate an uploaded CSV.

    Returns (issues, row_count, parse_error, positions_info):
    - issues:         list of ValidationIssue (stockpile only; [] for other formats)
    - row_count:      total tickers parsed (stockpile: data rows)
    - parse_error:    error string if parse failed, else None
    - positions_info: list of {ticker, shares, n_calls, n_puts} for non-stockpile;
                      None for stockpile (validator doesn't provide position detail)
    """
    if brokerage == "stockpile":
        from stocks_shared.validators import validate_stockpile_csv, count_data_rows
        text = content.decode("utf-8-sig")
        return validate_stockpile_csv(text), count_data_rows(text), None, None

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        from options_scanner.portfolio import get_portfolio
        positions = get_portfolio(tmp_path, brokerage, include_closed=True)
        info = [
            {
                "ticker": p["ticker"],
                "shares": p["shares"],
                "n_calls": sum(o["contracts"] for o in p["open_calls"]),
                "n_puts":  sum(o["contracts"] for o in p["open_puts"]),
            }
            for p in positions
        ]
        return [], len(positions), None, info
    except Exception as exc:
        return [], 0, str(exc), None
    finally:
        os.unlink(tmp_path)


def _show_validation(issues: list, row_count: int, parse_error: str | None,
                     brokerage: str,
                     positions_info: list | None = None) -> bool:
    """Render the validation panel.  Returns True if the file is scan-ready."""
    if parse_error:
        st.error(f"Could not parse CSV: {parse_error}")
        return False

    if brokerage != "stockpile":
        plural = "s" if row_count != 1 else ""
        st.success(f"Parsed successfully — {row_count} ticker{plural} found.")

        if positions_info:
            has_opts   = [p for p in positions_info
                          if p["n_calls"] > 0 or p["n_puts"] > 0]
            stock_only = [p for p in positions_info
                          if p["shares"] > 0
                          and p["n_calls"] == 0 and p["n_puts"] == 0]
            closed     = [p for p in positions_info
                          if p["shares"] <= 0
                          and p["n_calls"] == 0 and p["n_puts"] == 0]

            def _opt_label(p: dict) -> str:
                tags = []
                if p["n_calls"]: tags.append(f"{p['n_calls']}C")
                if p["n_puts"]:  tags.append(f"{p['n_puts']}P")
                return f"{p['ticker']} ({' '.join(tags)})"

            if has_opts:
                st.caption("**Open options:** "
                           + ", ".join(_opt_label(p) for p in has_opts))
            if stock_only:
                st.caption("**Stock only:** "
                           + ", ".join(f"{p['ticker']} ({p['shares']:g}sh)"
                                       for p in stock_only))
            if closed:
                st.caption("**Closed:** "
                           + ", ".join(p["ticker"] for p in closed))

        return True

    errors   = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    if not issues:
        st.success(f"Valid — {row_count} rows, no issues found.")
        return True

    parts = []
    if errors:
        parts.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}")
    if warnings:
        parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
    summary = f"{row_count} rows — {', '.join(parts)}"

    if errors:
        st.error(summary)
    else:
        st.warning(summary)

    with st.expander("Show issues", expanded=bool(errors)):
        import pandas as pd
        df = pd.DataFrame([
            {
                "Row":     str(i.row) if i.row > 0 else "—",
                "Field":   i.field or "—",
                "Level":   i.severity.upper(),
                "Message": i.message,
            }
            for i in issues
        ])

        def _row_style(row):
            color = (
                "background-color: rgba(239,68,68,0.18)"
                if row["Level"] == "ERROR"
                else "background-color: rgba(234,179,8,0.22)"
            )
            return [color] * len(row)

        styled = df.style.apply(_row_style, axis=1)
        st.dataframe(styled, hide_index=True, width="stretch")

    return not errors


def _parse_watchlist(text: str) -> list[str]:
    """Parse a free-text watchlist into a deduped, normalized ticker list.

    Accepts commas, whitespace, or newlines as separators. Order is
    preserved (first occurrence wins).
    """
    from stocks_shared.yahoo import normalize_ticker
    raw = text.replace(",", " ").split()
    seen: dict[str, None] = {}
    for tok in raw:
        t = normalize_ticker(tok)
        if t:
            seen.setdefault(t, None)
    return list(seen.keys())


def _scan_one(pos: dict, opt_type_key: str, scan_mode_key: str,
              provider: str, scfg: dict | None,
              min_dte: int, max_dte: int) -> dict:
    """Fetch + enrich one position and build its result dict.

    Shared by both input sources. Watchlist tickers pass a synthetic
    position (`shares=0`, no open options), so the roll-close-cost block
    below is skipped and the position scans as "best option" only.
    """
    ticker = pos["ticker"]
    df, earnings_dates, err = fetch_position(
        ticker, int(min_dte), provider, scfg,
        moomoo_config=st.session_state.get("moomoo_config"),
        opt_type=opt_type_key,
        max_dte=int(max_dte),
    )

    # Roll close cost lookup — only in Roll mode, only for open options
    # on the relevant side(s).
    roll_close_costs = {}
    if scan_mode_key == "roll":
        opts_to_lookup = []
        if opt_type_key in ("calls", "both"):
            opts_to_lookup += [(opt, "calls") for opt in pos["open_calls"]]
        if opt_type_key in ("puts", "both"):
            opts_to_lookup += [(opt, "puts") for opt in pos["open_puts"]]

        _schwab_client = None
        if provider == "schwab" and opts_to_lookup:
            from stocks_shared.schwab_live import get_client
            try:
                _schwab_client = get_client(
                    scfg["app_key"], scfg["app_secret"],
                    scfg["callback_url"], scfg["token_file"],
                )
            except (ValueError, TypeError):
                pass

        for opt, side in opts_to_lookup:
            m, d, y = opt["expiration"].split("/")
            exp_yf = f"{y}-{m}-{d}"
            if provider == "schwab" and _schwab_client is not None:
                from stocks_shared.schwab_live import fetch_option_chain_schwab
                chain = fetch_option_chain_schwab(_schwab_client, ticker, exp_yf)
            else:
                from stocks_shared.yahoo import fetch_option_chain
                chain = fetch_option_chain(ticker, exp_yf)
            if chain is None:
                continue
            chain_df = chain.calls if side == "calls" else chain.puts
            row = chain_df[chain_df["strike"] == float(opt["strike"])]
            if not row.empty:
                bid  = float(row["bid"].iloc[0] or 0)
                ask  = float(row["ask"].iloc[0] or 0)
                last = float(row["lastPrice"].iloc[0] or 0)
                roll_close_costs[opt["symbol"]] = (
                    (bid + ask) / 2 if bid > 0 and ask > 0 else last
                )

    return {
        "position": pos,
        "error": err,
        "df": df,
        "spot": float(df["spot"].iloc[0]) if not df.empty else None,
        "earnings_dates": earnings_dates,
        "roll_close_costs": roll_close_costs,
    }


def tab_portfolio() -> None:
    section_header(
        title="Portfolio scan",
        subtitle=(
            "Upload a brokerage CSV — we'll surface roll candidates and rich "
            "options ticker-by-ticker."
        ),
        eyebrow="STEP 01 · INPUT",
    )

    # ── Input source: brokerage CSV (today's flow) vs typed watchlist ─────────
    input_source = st.radio(
        "Input source", ["Brokerage CSV", "Watchlist"],
        horizontal=True, key="p_input_source",
        help="Brokerage CSV: scan every position in an export. "
             "Watchlist: type a basket of tickers — no broker account or "
             "CSV needed (best-option scan only).",
    )
    is_watchlist = input_source == "Watchlist"

    uploaded = None
    brokerage = None
    watchlist_tickers: list[str] = []

    if is_watchlist:
        _wl_text = st.text_area(
            "Tickers",
            key="p_watchlist",
            placeholder="AMD, NVDA, AAPL  (commas, spaces, or new lines)",
            help="Separate tickers by comma, space, or new line. Append ! to "
                 "a symbol to disable index normalization.",
        )
        watchlist_tickers = _parse_watchlist(_wl_text or "")
        if watchlist_tickers:
            st.caption(f"{len(watchlist_tickers)} ticker(s): "
                       + ", ".join(watchlist_tickers))
    else:
        # ── Upload row: file picker (50 %) + format selector (25 %) + spacer ──
        _up_col, _fmt_col, _ = st.columns([2, 1, 1])
        with _up_col:
            uploaded = st.file_uploader("Brokerage CSV export", type=["csv"])
            st.markdown(
                "<div style='margin: 0.2rem 0 0 0;'>"
                + badge("PROCESSED LOCALLY · NEVER UPLOADED", "positive")
                + "</div>",
                unsafe_allow_html=True,
            )

        # ── Auto-detect format on new file upload ────────────────────────────
        if uploaded is not None:
            _file_sig = f"{uploaded.name}:{len(uploaded.getvalue())}"
            if st.session_state.get("_port_file_sig") != _file_sig:
                _detected = detect_brokerage(uploaded.getvalue())
                st.session_state["_port_file_sig"] = _file_sig
                st.session_state["_port_auto_detected"] = _detected
                st.session_state["_port_detect_ran"] = True
                if _detected:
                    st.session_state["p_brokerage"] = _detected

        with _fmt_col:
            brokerage = st.selectbox(
                "Format",
                ["schwab", "robinhood", "fidelity", "merrill", "stockpile"],
                index=None,
                placeholder="Select format…",
                key="p_brokerage",
                help="Select your brokerage export format, or 'stockpile' for "
                     "a manually-entered transaction log.",
            )
            if uploaded is not None and st.session_state.get("_port_detect_ran"):
                _auto = st.session_state.get("_port_auto_detected")
                if _auto and brokerage == _auto:
                    st.markdown(
                        badge("AUTO-DETECTED", "positive")
                        + f"&nbsp;<span style='font-size:0.78rem'>{_auto}</span>",
                        unsafe_allow_html=True,
                    )
                elif not _auto and brokerage is None:
                    st.markdown(
                        badge("FORMAT UNKNOWN", "neutral")
                        + "&nbsp;<span style='font-size:0.78rem'>select manually</span>",
                        unsafe_allow_html=True,
                    )

    # ── Controls row 1: filter params ────────────────────────────────────────
    pc1, pc2, pc3, pc4, pc5, pc6 = st.columns([1, 1, 1, 1, 2, 1])
    with pc1:
        port_min_dte = st.number_input("Min DTE", value=30, min_value=1,
                                       key="p_min_dte")
    with pc2:
        port_max_dte = st.number_input("Max DTE", value=90, min_value=1,
                                       key="p_max_dte")
    with pc3:
        port_min_oi = st.number_input("Min OI", value=25, min_value=0,
                                      key="p_min_oi")
    with pc4:
        port_min_vol = st.number_input("Min Vol", value=1, min_value=0,
                                       key="p_min_vol")
    with pc5:
        port_delta_range = st.slider("Delta Range", 0.0, 1.0, (0.10, 0.70),
                                     0.05, key="p_delta")
    with pc6:
        port_top = st.number_input("Top N per ticker", value=5, min_value=1,
                                   key="p_top")

    # ── Controls row 2: scan semantics ───────────────────────────────────────
    # Watchlist mode is best-option only over a typed basket, so Scan mode
    # and the position-scope checkboxes (which are about CSV positions) hide.
    if is_watchlist:
        opt_type_label = st.radio(
            "Option type", ["Calls", "Puts", "Both"],
            horizontal=True, key="p_opt_type",
        )
        scan_mode_label = "Best option"
        scope_open = scope_stock = scope_closed = True
    else:
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            opt_type_label = st.radio(
                "Option type", ["Calls", "Puts", "Both"],
                horizontal=True, key="p_opt_type",
            )
        with sc2:
            scan_mode_label = st.radio(
                "Scan mode", ["Best option", "Roll"],
                horizontal=True, key="p_scan_mode",
                help="Best option: surface the top IV-rich pick with no roll context. "
                     "Roll: find candidates to roll existing open positions into.",
            )
        with sc3:
            st.caption("Positions to scan")
            scope_open   = st.checkbox("Open options", value=True,  key="p_scope_open",
                                       help="Has existing short calls or puts.")
            scope_stock  = st.checkbox("Stock only",   value=True,  key="p_scope_stock",
                                       help="Holds shares with no open options.")
            scope_closed = st.checkbox("Closed",       value=False, key="p_scope_closed",
                                       help="Previously held, now fully exited.")

    opt_type_key  = {"Calls": "calls", "Puts": "puts", "Both": "both"}[opt_type_label]
    scan_mode_key = {"Roll": "roll", "Best option": "best"}[scan_mode_label]
    _side = {"calls": "call", "puts": "put", "both": "both"}[opt_type_key]

    # Invalidate stored results when the source, file, format, watchlist, or
    # scan semantics change.
    _cache_key = (
        input_source,
        f"{uploaded.name}:{len(uploaded.getvalue())}" if uploaded else None,
        tuple(watchlist_tickers),
        brokerage,
        opt_type_key,
        scan_mode_key,
        scope_open, scope_stock, scope_closed,
        int(port_min_dte),
        int(port_max_dte),
    )
    if st.session_state.get("_portfolio_cache_key") != _cache_key:
        st.session_state.pop("portfolio_results", None)
        st.session_state["_portfolio_cache_key"] = _cache_key

    # ── Validation (CSV source only; auto-runs when file + format are set) ────
    scan_ready = False
    if not is_watchlist and uploaded is not None and brokerage is not None:
        with st.container(border=True):
            st.caption(
                f"**Validation** — {uploaded.name}"
                + (" (stockpile format)" if brokerage == "stockpile" else "")
            )
            issues, row_count, parse_error, positions_info = _validate_csv(
                uploaded.getvalue(), brokerage
            )
            scan_ready = _show_validation(
                issues, row_count, parse_error, brokerage, positions_info,
            )

            if brokerage == "stockpile":
                st.caption(
                    "See the README for the full format spec and an example "
                    "row for every transaction type (BUY, SELL, STO, BTO, "
                    "STC, BTC, EXPIRED, ASSIGNED, EXERCISED, DIVIDEND, "
                    "SPLIT, TRANSFER_IN)."
                )

    _scan_disabled = (not watchlist_tickers if is_watchlist
                      else (uploaded is None or brokerage is None
                            or not scan_ready))
    _scan_label = "Scan Watchlist" if is_watchlist else "Scan Portfolio"
    if st.button(_scan_label, type="primary", disabled=_scan_disabled):
        _provider = st.session_state.get("data_source", "yahoo")
        _scfg = st.session_state.get("schwab_config")

        if is_watchlist:
            # Synthetic positions: no shares, no open options → best-option scan.
            positions = [
                {"ticker": t, "shares": 0, "open_calls": [], "open_puts": []}
                for t in watchlist_tickers
            ]
            source_name = f"Watchlist ({len(positions)} tickers)"
        else:
            from options_scanner.portfolio import get_portfolio
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
                f.write(uploaded.getvalue())
                tmp_path = f.name
            try:
                positions = get_portfolio(tmp_path, brokerage, include_closed=True)
                # Keep positions that match any checked bucket. Roll mode only
                # applies inside the "Open options" bucket; the other two buckets
                # always use "best option" logic (handled in the render loop via
                # the covered/roll_close flags, which are False/None when the
                # position has no open options).
                positions = [
                    p for p in positions
                    if (scope_open   and (p["open_calls"] or p["open_puts"]))
                    or (scope_stock  and p["shares"] > 0
                        and not p["open_calls"] and not p["open_puts"])
                    or (scope_closed and p["shares"] <= 0
                        and not p["open_calls"] and not p["open_puts"])
                ]
            except Exception as exc:
                st.error(f"Could not parse CSV: {exc}")
                os.unlink(tmp_path)
                st.stop()
            os.unlink(tmp_path)
            source_name = uploaded.name

        if not positions:
            st.warning("No positions to scan." if is_watchlist
                       else "No positions found in this CSV.")
            st.stop()

        st.success(f"Found {len(positions)} position(s): "
                   f"{', '.join(p['ticker'] for p in positions)}")

        progress = st.progress(0, text="Scanning…")
        results = []
        for i, pos in enumerate(positions):
            progress.progress((i + 1) / len(positions),
                              text=f"Scanning {pos['ticker']} "
                                   f"({i+1}/{len(positions)})…")
            results.append(_scan_one(
                pos, opt_type_key, scan_mode_key, _provider, _scfg,
                int(port_min_dte), int(port_max_dte),
            ))

        progress.empty()
        st.session_state["scan_ts"] = datetime.now().astimezone()
        st.session_state["scan_provider"] = st.session_state.get(
            "data_source", "yahoo"
        )
        st.session_state["portfolio_results"] = {
            "results": results,
            "uploaded_name": source_name,
            "opt_type": opt_type_key,
            "scan_mode": scan_mode_key,
        }

    # ── Render stored results (survives widget interactions / re-runs) ────────
    stored = st.session_state.get("portfolio_results")
    if stored is None:
        return

    results          = stored["results"]
    uploaded_name    = stored["uploaded_name"]
    stored_opt_type  = stored.get("opt_type", "calls")
    stored_scan_mode = stored.get("scan_mode", "roll")
    stored_side      = {"calls": "call", "puts": "put", "both": "both"}[stored_opt_type]

    # ── Cross-ticker leaderboard — richest IV+pp across the whole basket ──────
    if len(results) > 1:
        section_header(
            title="Leaderboard",
            subtitle="Richest IV+pp contracts across every scanned ticker.",
            eyebrow="TOP CANDIDATES",
        )
        render_leaderboard(results, stored_side, int(port_min_oi),
                           int(port_top), int(port_min_vol),
                           delta_range=port_delta_range)

    for res in results:
        pos    = res["position"]
        ticker = pos["ticker"]

        # Build a compact expander label summarising what this position holds.
        shares_str = f"{pos['shares']:g} shares" if pos["shares"] > 0 else "no shares"
        label_parts = [ticker, shares_str]
        if stored_opt_type in ("calls", "both") and pos["open_calls"]:
            n = sum(o["contracts"] for o in pos["open_calls"])
            label_parts.append(f"{n} short call(s)")
        if stored_opt_type in ("puts", "both") and pos["open_puts"]:
            n = sum(o["contracts"] for o in pos["open_puts"])
            label_parts.append(f"{n} short put(s)")
        label = " — ".join(label_parts)

        with st.expander(label, expanded=True):
            if res["error"]:
                st.error(res["error"])
                continue

            spot           = res["spot"]
            earnings_dates = res["earnings_dates"]
            df             = res["df"]

            if spot is None or df.empty:
                st.warning("No options data returned — Yahoo may be "
                           "throttling. Try again in a moment.")
                continue

            m1, m2, m3, m4 = st.columns(4)
            if earnings_dates:
                earn_days = (earnings_dates[0] - date.today()).days
                earn_label = f"{earnings_dates[0].strftime('%b %d')}"
                earn_sub   = f"in {earn_days}d"
            else:
                earn_label = "—"
                earn_sub   = "no upcoming events"
            with m1:
                _meta = fetch_spot_meta(
                    ticker, st.session_state.get("scan_provider", "yahoo"),
                )
                metric_card("SPOT",
                            spot_value_html(spot, _meta["pct_change"]),
                            help_text=spot_help_text(_meta))
            with m2:
                metric_card("SHARES", f"{pos['shares']:,g}" if pos["shares"] > 0 else "—")
            with m3:
                metric_card("EXPIRATIONS", f"{df['expiration'].nunique()}")
            with m4:
                metric_card("NEXT EARNINGS", earn_label,
                            delta=earn_sub, delta_sign="neutral")

            # Open option info rows (Roll mode only — irrelevant in Best mode)
            if stored_scan_mode == "roll":
                if stored_opt_type in ("calls", "both"):
                    for opt in pos["open_calls"]:
                        close = res["roll_close_costs"].get(opt["symbol"])
                        close_str = (f" — close mid: **${close:.2f}**"
                                     if close else "")
                        st.info(f"Open call: **{opt['symbol']}** "
                                f"({opt['contracts']} contract(s)){close_str}")
                if stored_opt_type in ("puts", "both"):
                    for opt in pos["open_puts"]:
                        close = res["roll_close_costs"].get(opt["symbol"])
                        close_str = (f" — close mid: **${close:.2f}**"
                                     if close else "")
                        st.info(f"Open put: **{opt['symbol']}** "
                                f"({opt['contracts']} contract(s)){close_str}")

            port_delta_min, port_delta_max = port_delta_range
            df_filt = df[df["delta"].abs().between(
                port_delta_min, port_delta_max)].copy()

            # Action card(s) — one per side being scanned.
            if stored_opt_type in ("calls", "both"):
                df_calls = (df_filt[df_filt["type"] == "call"]
                            if stored_opt_type == "both" else df_filt)
                roll_close_call = None
                if stored_scan_mode == "roll" and pos["open_calls"]:
                    roll_close_call = res["roll_close_costs"].get(
                        pos["open_calls"][0]["symbol"]
                    )
                render_portfolio_action_card(
                    ticker=ticker,
                    df_filt=df_calls,
                    spot=spot,
                    shares=int(pos["shares"]),
                    covered=bool(pos["open_calls"]) and stored_scan_mode == "roll",
                    roll_close=roll_close_call,
                    open_options=pos["open_calls"],
                    min_oi=int(port_min_oi),
                    min_vol=int(port_min_vol),
                    opt_type="calls",
                )

            if stored_opt_type in ("puts", "both"):
                df_puts = (df_filt[df_filt["type"] == "put"]
                           if stored_opt_type == "both" else df_filt)
                roll_close_put = None
                if stored_scan_mode == "roll" and pos["open_puts"]:
                    roll_close_put = res["roll_close_costs"].get(
                        pos["open_puts"][0]["symbol"]
                    )
                render_portfolio_action_card(
                    ticker=ticker,
                    df_filt=df_puts,
                    spot=spot,
                    shares=int(pos["shares"]),
                    covered=bool(pos["open_puts"]) and stored_scan_mode == "roll",
                    roll_close=roll_close_put,
                    open_options=pos["open_puts"],
                    min_oi=int(port_min_oi),
                    min_vol=int(port_min_vol),
                    opt_type="puts",
                )

            show_iv_chart(df_filt, spot, stored_side,
                           int(port_min_oi), int(port_top), False,
                           ticker=ticker, key_prefix=f"p_{ticker}",
                           min_vol=int(port_min_vol),
                           provider=st.session_state.get("scan_provider", "yahoo"))

            # For roll_close_cost in the candidates table: use the first open
            # option for the active side; None if no roll context or "both".
            _table_roll_close = None
            if stored_scan_mode == "roll":
                if stored_opt_type == "calls" and pos["open_calls"]:
                    _table_roll_close = res["roll_close_costs"].get(
                        pos["open_calls"][0]["symbol"]
                    )
                elif stored_opt_type == "puts" and pos["open_puts"]:
                    _table_roll_close = res["roll_close_costs"].get(
                        pos["open_puts"][0]["symbol"]
                    )

            st.markdown("**Top candidates**")
            show_scan_results(df_filt, stored_side, False, _table_roll_close,
                               int(port_min_oi), int(port_top),
                               int(port_min_vol))

    # Portfolio HTML download
    from options_scanner.report import render_portfolio_html
    port_html = render_portfolio_html(
        results, uploaded_name, int(port_min_oi), int(port_top),
        int(port_min_vol), opt_type=stored_opt_type,
        delta_range=port_delta_range,
    )
    st.download_button(
        "⬇ Download Portfolio Report",
        data=port_html.encode("utf-8"),
        file_name=f"portfolio_{date.today().strftime('%Y%m%d')}.html",
        mime="text/html",
    )
