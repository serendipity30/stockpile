"""Streamlit web UI for the options scanner."""

import asyncio
import sys

# Streamlit's internal async handling is incompatible with Windows's default
# ProactorEventLoop on Python 3.12+. Switch to the Selector policy before
# Streamlit starts its own loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from pathlib import Path

import streamlit as st

from options_scanner.ui_theme import (
    badge,
    disclaimer_chip,
    footer as ui_footer,
    inject_theme,
    metric_card,
    register_altair_theme,
    section_header,
)
from options_scanner.display.scan_stamp import PROVIDER_LABELS, PROVIDER_COLORS
from options_scanner.tabs.gex import tab_gex
from options_scanner.tabs.portfolio import tab_portfolio
from options_scanner.tabs.single import tab_single
from options_scanner.tabs.spreads import tab_directional, tab_neutral, tab_spreads

_FAVICON_PATH = Path(__file__).parent / "assets" / "favicon.png"
st.set_page_config(
    page_title="Options Scanner — Stockpile",
    page_icon=str(_FAVICON_PATH) if _FAVICON_PATH.exists() else "•",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Inject the global stylesheet and Altair theme as early as possible so
# every downstream widget renders in the redesigned visual language.
inject_theme()
register_altair_theme()


# ── Legacy theme switcher (kept for backward-compat session_state keys) ─────
# The new design system replaces the old four-way theme picker. We leave a
# no-op so any existing references / saved preferences don't crash.

THEMES: dict[str, None] = {"Default": None}


def _apply_theme(theme_name: str) -> None:  # noqa: ARG001 — preserved for compat
    """Compatibility shim: the new ui_theme.inject_theme() supersedes this."""
    return None


# ── Main ─────────────────────────────────────────────────────────────────────

# Config must load first so data_source_choice is seeded into session_state
# before we compute the accent colors below.
from options_scanner.config import (
    load_config, get_provider,
    get_schwab_config as _get_schwab_cfg,
    get_moomoo_config as _get_moomoo_cfg,
)
_app_cfg = load_config()
_cfg_provider = get_provider(_app_cfg)
_cfg_schwab = _get_schwab_cfg(_app_cfg)
_cfg_moomoo = _get_moomoo_cfg(_app_cfg)
_schwab_configured = (
    bool(_cfg_schwab.get("app_key"))
    and not _cfg_schwab["app_key"].startswith("your-")
    and bool(_cfg_schwab.get("app_secret"))
    and not _cfg_schwab["app_secret"].startswith("your-")
)
if "data_source_choice" not in st.session_state:
    if _cfg_provider == "schwab" and _schwab_configured:
        st.session_state["data_source_choice"] = "schwab"
    elif _cfg_provider == "moomoo":
        st.session_state["data_source_choice"] = "moomoo"
    else:
        st.session_state["data_source_choice"] = "yahoo"

# Compute accent colors from the current data-source choice. Reads
# `data_source_choice` (the widget key) — NOT the effective
# `data_source` — so the color flips on the same rerun the dropdown
# changed, not one rerun later.
_BTN_COLORS = {
    "yahoo":  ("#16a34a", "#15803d"),   # normal, hover
    "schwab": ("#2563eb", "#1d4ed8"),
    "moomoo": ("#f97316", "#ea6e0e"),
}
_btn_bg, _btn_hover = _BTN_COLORS.get(
    st.session_state.get("data_source_choice", "yahoo"),
    _BTN_COLORS["yahoo"],
)

# Static layout rules via st.markdown so they land in the main document.
# st.html() renders in an iframe and cannot affect position:fixed elements
# in the main page — st.markdown(unsafe_allow_html=True) injects directly.
_STYLES_CSS = (
    Path(__file__).parent / "options_scanner" / "styles.css"
).read_text(encoding="utf-8")
st.markdown(f"<style>{_STYLES_CSS}</style>", unsafe_allow_html=True)

# Dynamic accent colors — injected fresh each rerun so button colors
# flip immediately when the data source toggle changes. st.markdown is
# used (not st.html) so the rules reach the main document.
st.markdown(f"""<style>
.stButton > button[kind="primary"],
button[data-testid="stBaseButton-primary"] {{
    background-color: {_btn_bg} !important;
    border-color: {_btn_bg} !important;
}}
.stButton > button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover {{
    background-color: {_btn_hover} !important;
    border-color: {_btn_hover} !important;
}}
[class*="st-key-data_source_pill"] button[aria-pressed="true"],
[class*="st-key-data_source_pill"] button[aria-selected="true"],
[class*="st-key-data_source_pill"] button[data-testid*="Active"] {{
    color: {_btn_bg} !important;
    border-color: {_btn_bg} !important;
    box-shadow: inset 0 0 0 1px {_btn_bg} !important;
}}
[class*="st-key-data_source_pill"] button[aria-pressed="true"] p,
[class*="st-key-data_source_pill"] button[aria-selected="true"] p,
[class*="st-key-data_source_pill"] button[data-testid*="Active"] p {{
    color: {_btn_bg} !important;
}}
</style>""", unsafe_allow_html=True)

# Sidebar-state observer: watches the actual sidebar element's rendered
# width and writes data-sidebar-open onto body so the header-bar CSS
# above can respond. Identical to the previous implementation — Streamlit
# offers no native hook for this.
st.iframe(
    r"""
    <script>
    (function() {
        const doc = window.parent.document;

        // Sidebar-open state — drives pill positioning CSS.
        const syncSidebar = () => {
            const sb = doc.querySelector('[data-testid="stSidebar"]');
            if (!sb) return;
            const w = sb.getBoundingClientRect().width;
            doc.body.dataset.sidebarOpen = w > 60 ? 'true' : 'false';
        };

        // Theme detection — reads the actual rendered background of the
        // Streamlit app container so we respond to the hamburger toggle,
        // not just the OS preference. Sets data-osc-theme="dark"|"light"
        // on <html> so CSS can branch on it.
        const syncTheme = () => {
            const app = doc.querySelector('[data-testid="stApp"]');
            if (!app) return;
            const bg = window.parent.getComputedStyle(app).backgroundColor;
            const m = bg.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
            if (!m) return;
            const brightness = (+m[1] + +m[2] + +m[3]) / 3;
            doc.documentElement.setAttribute(
                'data-osc-theme', brightness < 80 ? 'dark' : 'light'
            );
        };

        const sync = () => { syncSidebar(); syncTheme(); };
        sync();
        const obs = new MutationObserver(sync);
        obs.observe(doc.body, {
            childList: true, subtree: true,
            attributes: true,
            attributeFilter: ['style', 'class', 'aria-expanded'],
        });
        window.addEventListener('resize', sync);
    })();
    </script>
    """,
    height=0, width=0,
)


# Title-bar data-source switch — pinned via CSS to the right of the
# rescan pill so it's always visible without opening the sidebar.
def _source_label(s: str) -> str:
    if s == "yahoo":
        return "Yahoo Finance"
    if s == "moomoo":
        return "Moomoo (live)"
    return "Schwab (live)" if _schwab_configured else "Schwab (unconfigured)"

with st.container(key="data_source_pill"):
    _source_raw = st.segmented_control(
        "Data source",
        ["yahoo", "schwab", "moomoo"],
        format_func=_source_label,
        label_visibility="collapsed",
        key="data_source_choice",
    )
if _source_raw is None:
    _source_raw = "yahoo"

if _source_raw == "schwab" and _schwab_configured:
    data_source = "schwab"
elif _source_raw == "moomoo":
    data_source = "moomoo"
else:
    data_source = "yahoo"
st.session_state["data_source"] = data_source
st.session_state["schwab_config"] = _cfg_schwab if data_source == "schwab" else None
st.session_state["moomoo_config"] = _cfg_moomoo if data_source == "moomoo" else None


# ── Page header chips ────────────────────────────────────────────────────
# Sidebar: an "About" panel — the legacy theme picker is gone (we now ship
# one canonical design system). Add helpful links and a status indicator.
with st.sidebar:
    st.markdown(
        "<div style='padding: 0.5rem 0 0.75rem 0;'>"
        + badge("WORKSPACE", "neutral")
        + "</div>",
        unsafe_allow_html=True,
    )
    section_header(
        title="Stockpile",
        subtitle=(
            "Options Analytics made for:<br>"
            "• Income generation<br>"
            "• Directional bets<br>"
            "• Defined-risk spreads<br>"
            "• GEX analysis"
        ),
    )
    st.markdown(
        disclaimer_chip("Research tool · Not investment advice"),
        unsafe_allow_html=True,
    )
    st.markdown("---")
    section_header("Data source", eyebrow="ACTIVE PROVIDER")
    _src_label = _source_label(data_source)
    _src_color = PROVIDER_COLORS.get(data_source, "#94a3b8")
    st.markdown(
        f"<div style='font-size:0.86rem; margin-bottom:0.4rem;'>"
        f"<span style='display:inline-block; padding:0.2rem 0.65rem; "
        f"border-radius:6px; font-weight:500; color:#FFFFFF; "
        f"background-color:{_src_color};'>{_src_label}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Switch between Yahoo Finance (free, 15-min delay), Schwab "
        "(authenticated, live), and Moomoo (live via OpenD). "
        "Use the toggle in the top bar."
    )
    st.markdown("---")
    section_header("About", eyebrow="HOW THIS WORKS")
    st.caption(
        "Surface contracts whose implied volatility sits above (or below) "
        "the fitted surface. Filter by DTE, delta, liquidity; export a "
        "shareable HTML report."
    )
    st.caption(
        "For every option in the chain, we fit a smooth volatility "
        "surface across strike and DTE, then rank contracts by how much "
        "their IV exceeds the fit (IV+pp). 3pp ≈ noise; 5+pp is signal."
    )
    st.markdown("---")
    section_header("Documentation", eyebrow="REFERENCE")
    st.markdown(
        "- [README](https://github.com/) — overview & install\n"
        "- [Interpreting IV](https://github.com/) — what IV+pp means\n"
        "- [Spreads](https://github.com/) — strategy glossary",
        unsafe_allow_html=False,
    )

# Compatibility shim — keep `_apply_theme(theme_choice)` working in case
# any deferred code path references it. With the new design system in
# place this is a no-op.
_apply_theme("Default")

# Brand wordmark — now in normal document flow just below the fixed
# title bar (rescan / data-source / surface-fit pills), so it scrolls
# away with the page instead of staying pinned.
st.markdown(
    """
    <div class='osc-wordmark-inline'>
      <span class='osc-wm-dot'></span>
      <span class='osc-wm-brand'>STOCKPILE</span>
      <span class='osc-wm-suffix'>· OPTIONS SCANNER</span>
    </div>
    """,
    unsafe_allow_html=True,
)

(
    panel_single, panel_gex, panel_portfolio,
    panel_spreads, panel_directional, panel_neutral,
) = st.tabs(
    ["Single Ticker", "GEX", "Portfolio",
     "Spreads", "Directional", "Neutral"]
)

with panel_single:
    tab_single()

with panel_gex:
    tab_gex()

with panel_portfolio:
    tab_portfolio()

with panel_spreads:
    tab_spreads()

with panel_directional:
    tab_directional()

with panel_neutral:
    tab_neutral()

# ── Footer ───────────────────────────────────────────────────────────────
ui_footer()
