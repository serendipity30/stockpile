"""Trades tab — what the assisted put-seller has placed, and managing it.

Lists every recorded short-put trade (``trades_store``), estimates live
cost-to-close and unrealized P/L from a Schwab re-quote, and previews a
closing order. Placement/closing is NOT wired yet — the action buttons are
disabled; this is the read + preview surface. Schwab-only.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from options_scanner import trade_actions, trades_store
from options_scanner.ui_theme import metric_card, section_header


@st.cache_data(ttl=30, show_spinner=False)
def _close_quote(app_key: str, app_secret: str, callback_url: str,
                 token_file: str, ticker: str, expiration: str,
                 strike: float) -> dict | None:
    """Cached (30s) read-only re-quote for one put. Returns dict or None."""
    from stocks_shared.schwab_live import get_client
    try:
        client = get_client(app_key, app_secret, callback_url, token_file)
    except Exception:
        return None
    return trade_actions.requote_put(client, ticker, expiration, strike)


def tab_trades() -> None:
    section_header(
        title="Trades",
        subtitle="Put-sells placed from the watchlist — live P/L and "
                 "cost-to-close estimates.",
        eyebrow="ASSISTED PUT-SELLING",
    )

    provider = st.session_state.get("data_source", "yahoo")
    scfg = st.session_state.get("schwab_config") or {}

    trades = trades_store.load()
    if not trades:
        st.info(
            "No trades yet. When order placement is enabled, put-sells you "
            "place from the **Watchlist** leaderboard's *investigate* dialog "
            "will appear here with live P/L and a cost-to-close estimate. "
            "Placement is currently disabled (preview only)."
        )
        return

    open_trades = [t for t in trades if t.get("status") == "open"]
    st.caption(f"{len(trades)} trade(s) · {len(open_trades)} open")

    for t in trades:
        exp = t.get("expiration", "")
        try:
            exp_disp = datetime.strptime(exp, "%Y-%m-%d").strftime("%b %d '%y")
        except Exception:
            exp_disp = exp or "?"
        qty = int(t.get("quantity", 1))
        credit_ps = float(t.get("credit", 0))          # per share
        total_credit = credit_ps * 100 * qty
        label = (f"{t.get('ticker', '?')} ${t.get('strike', '?')} PUT — "
                 f"{exp_disp} · {qty}x · {t.get('status', 'open')}"
                 + ("  ·  PAPER" if t.get("paper") else ""))

        with st.expander(label, expanded=(t.get("status") == "open")):
            # Live re-quote for cost-to-close (Schwab, read-only).
            q = None
            if provider == "schwab" and scfg.get("app_key"):
                q = _close_quote(
                    scfg.get("app_key", ""), scfg.get("app_secret", ""),
                    scfg.get("callback_url", ""), scfg.get("token_file", ""),
                    t.get("ticker"), exp, float(t.get("strike", 0)),
                )
            close_mid = q.get("mid") if q else None

            m1, m2, m3, m4 = st.columns(4)
            with m1:
                metric_card("CREDIT (OPEN)", f"${total_credit:,.0f}",
                            delta=f"${credit_ps:.2f}/sh", delta_sign="neutral")
            with m2:
                if close_mid is not None:
                    metric_card("COST TO CLOSE", f"${close_mid * 100 * qty:,.0f}",
                                delta=f"${close_mid:.2f}/sh", delta_sign="neutral")
                else:
                    metric_card("COST TO CLOSE", "—",
                                delta="re-quote unavailable", delta_sign="neutral")
            with m3:
                if close_mid is not None:
                    pnl = (credit_ps - close_mid) * 100 * qty
                    metric_card("UNREALIZED P/L", f"${pnl:,.0f}",
                                delta_sign="pos" if pnl >= 0 else "neg")
                else:
                    metric_card("UNREALIZED P/L", "—")
            with m4:
                metric_card("STATUS", t.get("status", "open").upper())

            if t.get("status") == "open":
                st.markdown("**Close this position** (buy to close)")
                default_close = (trade_actions.round_to_tick(close_mid)
                                 if close_mid else 0.05)
                cc1, cc2 = st.columns([1, 1])
                with cc1:
                    st.number_input(
                        "Close limit (debit per share)", min_value=0.01,
                        value=float(default_close),
                        step=float(trade_actions.tick_for(default_close)),
                        format="%.2f", key=f"close_limit_{t['id']}",
                    )
                with cc2:
                    st.markdown("<div style='height:1.72rem'></div>",
                                unsafe_allow_html=True)
                    st.button(
                        "Place Closing Trade", disabled=True,
                        key=f"close_btn_{t['id']}",
                        help="Closing orders aren't wired up yet — coming in "
                             "a future update.",
                    )
                st.caption("Closing is disabled — preview only. Verify at "
                           "your broker.")

            st.button("Remove from tracker", key=f"rm_{t['id']}",
                      on_click=trades_store.remove, args=(t["id"],))

    st.caption("Estimates use a live Schwab mid; verify at your broker.")
