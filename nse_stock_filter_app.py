import time
import requests
import pandas as pd
import pytz
import datetime as dt
import streamlit as st

# ------------------ App Settings ------------------
IST = pytz.timezone("Asia/Kolkata")
DEFAULT_GATE = (9, 20)
DEFAULT_STOCK_COUNT = 3
TOP_SECTORS = 2
SECTOR_INDICES = [
    "NIFTY BANK",
    "NIFTY FINANCIAL SERVICES",
    "NIFTY FMCG",
    "NIFTY IT",
    "NIFTY PHARMA",
    "NIFTY AUTO",
    "NIFTY METAL",
    "NIFTY REALTY",
    "NIFTY ENERGY",
    "NIFTY MEDIA",
    "NIFTY HEALTHCARE INDEX",
    "NIFTY CONSUMER DURABLES",
    "NIFTY OIL & GAS",
    "NIFTY PSU BANK",
    "NIFTY PRIVATE BANK",
    "NIFTY INFRASTRUCTURE",
]

# NSE API URLs
URLS = {
    "allIndices": "https://www.nseindia.com/api/allIndices",
    "constituents": "https://www.nseindia.com/api/equity-stockIndices",
    "home": "https://www.nseindia.com",
}

# Rotating User-Agent pool to reduce blocking
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


# ---------- NSE Session ----------
@st.cache_resource(ttl=180)  # cache session for 3 min
def get_nse_session():
    """
    Creates a warmed-up requests.Session with NSE cookies.
    Cached so we don't re-handshake on every button press.
    """
    for ua in USER_AGENTS:
        s = requests.Session()
        s.headers.update({
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "https://www.nseindia.com/",
            "DNT": "1",
        })
        try:
            r = s.get(URLS["home"], timeout=8)
            if r.status_code == 200:
                return s
        except Exception:
            continue
    raise RuntimeError(
        "Could not establish a session with NSE. "
        "NSE blocks server-side requests from cloud hosts. "
        "Run this app **locally** (`streamlit run nse_stock_filter_app.py`) "
        "for reliable access."
    )


def nse_get(session, url, params=None, retries=3, delay=1.0):
    """Robust GET with retries and back-off."""
    for attempt in range(retries):
        try:
            time.sleep(delay * attempt)   # progressive back-off
            r = session.get(url, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 401:
                # Session expired — force cache clear
                st.cache_resource.clear()
                raise RuntimeError(
                    "NSE returned 401 (Unauthorized). Session expired. "
                    "Click 'Run Filter' again — a fresh session will be created."
                )
            elif r.status_code == 403:
                raise RuntimeError(
                    f"NSE returned 403 (Forbidden) for {url}.\n\n"
                    "**Root cause:** NSE actively blocks requests from cloud/server IPs "
                    "(Streamlit Cloud, AWS, GCP, etc.).\n\n"
                    "**Fix:** Run this app **locally** on your machine:\n"
                    "```\npip install streamlit requests pandas pytz\n"
                    "streamlit run nse_stock_filter_app.py\n```"
                )
        except RuntimeError:
            raise
        except Exception as e:
            if attempt == retries - 1:
                raise RuntimeError(f"Network error after {retries} attempts: {e}")
    raise RuntimeError(f"Failed to fetch after {retries} retries: {url}")


# ---------- Logic ----------
def ist_now():
    return dt.datetime.now(IST)


def parse_pct(row):
    for k in ("percentChange", "percChange", "pChange"):
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return None


def nifty50_trend(session):
    j = nse_get(session, URLS["allIndices"])
    items = j.get("data") or j
    for row in items:
        name = str(row.get("index", row.get("indexSymbol", ""))).strip().upper()
        if name == "NIFTY 50":
            pct = parse_pct(row)
            if pct is not None:
                return ("BULLISH" if pct > 0 else "BEARISH"), pct
    raise RuntimeError("NIFTY 50 not found in allIndices response.")


def pick_sectors(session, trend):
    j = nse_get(session, URLS["allIndices"])
    items = j.get("data") or j
    sector_set = set(SECTOR_INDICES)
    rows = []
    for row in items:
        name = str(row.get("index", row.get("indexSymbol", ""))).strip()
        if name in sector_set:
            pct = parse_pct(row)
            if pct is not None:
                rows.append({"sector": name, "percentChange": pct})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("percentChange", ascending=(trend == "BEARISH")).reset_index(drop=True)
    return df


def top_stocks_in_sector(session, sector_name, count, trend):
    encoded = sector_name.replace(" ", "%20").replace("&", "%26")
    url = f"https://www.nseindia.com/api/equity-stockIndices?index={encoded}"
    j = nse_get(session, url)
    data = j.get("data", [])
    rows = []
    for d in data:
        sym = d.get("symbol")
        lp = d.get("lastPrice") or d.get("last") or d.get("lastprice")
        chg = parse_pct(d)
        vol = d.get("totalTradedVolume") or d.get("tradedQuantity") or d.get("volume")
        if sym and lp is not None and chg is not None:
            rows.append({
                "symbol": sym,
                "lastPrice": float(lp),
                "pChange": float(chg),
                "volume": vol,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("pChange", ascending=(trend == "BEARISH")).head(count).reset_index(drop=True)
    return df


# ---------- Streamlit UI ----------
st.set_page_config(page_title="NSE Stock Filter", page_icon="📈", layout="centered")

st.title("📈 NSE Intraday Stock Filter")
st.caption(
    "Finds market trend from NIFTY 50 → picks **Top 2 sectors** "
    "(leaders if bullish, laggards if bearish) → shows **3 stocks per sector = 6 stocks total**."
)

# ── Important notice for cloud deployments ──────────────────────────────────
with st.expander("⚠️ If you see a 403/fetch error — read this", expanded=False):
    st.markdown(
        """
**NSE blocks cloud server IPs** (Streamlit Cloud, AWS, GCP, Heroku, etc.).

This is a well-known restriction — NSE only serves its API to browser-based clients
from residential/corporate IPs.

**The reliable fix: run locally**
```bash
pip install streamlit requests pandas pytz
streamlit run nse_stock_filter_app.py
```
Your browser opens at `http://localhost:8501` and NSE works perfectly.

**Workaround for cloud**: Some users route requests through a residential proxy.
That is out of scope for this script.
        """
    )

colA, colB = st.columns(2)
with colA:
    h = st.number_input("Gate Hour (IST)", min_value=9, max_value=11, value=DEFAULT_GATE[0], step=1)
with colB:
    m = st.number_input("Gate Minute", min_value=0, max_value=59, value=DEFAULT_GATE[1], step=1)

stocks_per_sector = st.slider("Stocks per sector", 2, 5, DEFAULT_STOCK_COUNT, 1)
allow_early = st.checkbox("Override time gate (allow before gate)", value=False)

col1, col2 = st.columns([1, 3])
with col1:
    run_btn = st.button("🔎 Run Filter", type="primary", use_container_width=True)
with col2:
    if st.button("🔄 Reset Session Cache", help="Force a fresh NSE session if you see auth errors"):
        st.cache_resource.clear()
        st.success("Session cache cleared. Click 'Run Filter' again.")

st.divider()

if run_btn:
    now = ist_now()
    gate_time = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if (not allow_early) and (now < gate_time):
        st.warning(f"⏳ Wait until {gate_time.strftime('%I:%M %p')} IST (or tick Override).")
        st.stop()

    st.write(f"🕒 Time: **{now.strftime('%I:%M:%S %p')} IST**")

    try:
        with st.spinner("Connecting to NSE…"):
            session = get_nse_session()

        # ── 1) Market trend ─────────────────────────────────────────────────
        with st.spinner("Fetching NIFTY 50 trend…"):
            trend, nifty_pct = nifty50_trend(session)

        emoji = "🟢" if trend == "BULLISH" else "🔴"
        st.subheader(f"{emoji} Market Trend: **{trend}** (NIFTY 50: {nifty_pct:+.2f}%)")

        if trend == "BULLISH":
            st.info("Selecting **Top 2 gaining sectors** and their **top gaining stocks**.")
        else:
            st.info("Selecting **Top 2 losing sectors** and their **top losing stocks**.")

        # ── 2) Sector ranking ────────────────────────────────────────────────
        with st.spinner("Ranking sectors…"):
            sec_df = pick_sectors(session, trend)

        if sec_df.empty:
            st.error("Could not rank sectors. Try again.")
            st.stop()

        st.markdown("**Sector Ranking** (sorted by % change):")

        # Colour-code the dataframe
        def colour_pct(val):
            color = "#2ecc71" if val > 0 else "#e74c3c"
            return f"color: {color}; font-weight: bold"

        styled = sec_df.style.applymap(colour_pct, subset=["percentChange"]).format(
            {"percentChange": "{:+.2f}%"}
        )
        st.dataframe(styled, use_container_width=True)

        selected = sec_df.head(TOP_SECTORS)["sector"].tolist()
        st.success(f"✅ Selected → **{selected[0]}** & **{selected[1]}**")

        # ── 3) Stocks ────────────────────────────────────────────────────────
        st.subheader(f"🎯 Top {stocks_per_sector} Stocks per Sector")

        all_stocks = []
        for i, sector in enumerate(selected, 1):
            st.markdown(f"#### {i}. {sector}")
            with st.spinner(f"Fetching {sector} constituents…"):
                sdf = top_stocks_in_sector(session, sector, stocks_per_sector, trend)
            if sdf.empty:
                st.warning(f"No constituent data for **{sector}**.")
                continue
            sdf.insert(0, "sector", sector)
            styled_s = sdf.style.applymap(colour_pct, subset=["pChange"]).format(
                {"lastPrice": "₹{:.2f}", "pChange": "{:+.2f}%"}
            )
            st.dataframe(styled_s, use_container_width=True)
            all_stocks.append(sdf)

        if all_stocks:
            combined = pd.concat(all_stocks, ignore_index=True)
            st.divider()
            st.subheader("📋 Combined View")
            styled_c = combined.style.applymap(colour_pct, subset=["pChange"]).format(
                {"lastPrice": "₹{:.2f}", "pChange": "{:+.2f}%"}
            )
            st.dataframe(styled_c, use_container_width=True)

        st.caption("Tip: Re-run after a minute for updated rankings.")

    except RuntimeError as e:
        st.error(str(e))
        st.info(
            "💡 **Quick fix**: Run locally → `streamlit run nse_stock_filter_app.py`\n\n"
            "Or try clicking **Reset Session Cache** above and run again."
        )
    except Exception as e:
        st.error(f"Unexpected error: {e}")
