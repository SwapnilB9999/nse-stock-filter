# nse_stock_filter_app.py
# Local web app: click at/after 9:20 to filter NSE stocks by market trend & sector leaders/laggards

import time
import math
import requests
import pandas as pd
import pytz
import datetime as dt
import streamlit as st

# ------------------ App Settings ------------------
IST = pytz.timezone("Asia/Kolkata")
DEFAULT_GATE = (9, 20)  # 9:20
DEFAULT_STOCK_COUNT = 3   # per sector (3 stocks x 2 sectors = 6 total)
TOP_SECTORS = 2           # number of sectors to pick
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
# --------------------------------------------------

# ---------- NSE helper ----------
class NSE:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/",
        })
        try:
            self.s.get("https://www.nseindia.com", timeout=5)
        except Exception:
            pass

    def get_json(self, url, params=None, retries=3, timeout=7):
        for _ in range(retries):
            try:
                r = self.s.get(url, params=params, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                time.sleep(0.4)
        raise RuntimeError(f"Failed to fetch: {url}")

    def all_indices(self):
        return self.get_json("https://www.nseindia.com/api/allIndices")

    def index_constituents(self, index_name: str):
        idx = index_name.replace(" ", "%20")
        j = self.get_json(f"https://www.nseindia.com/api/equity-stockIndices?index={idx}")
        return j.get("data", [])

# ---------- Logic ----------
def ist_now():
    return dt.datetime.now(IST)

def nifty50_trend(nse: NSE) -> tuple[str, float]:
    """
    Get NIFTY 50 percent change from /api/allIndices.
    Returns ("BULLISH" or "BEARISH", pct_change)
    """
    j = nse.all_indices()
    items = j.get("data") or j
    pct = 0.0
    for row in items:
        name = row.get("index", row.get("indexSymbol", row.get("indexName", "")))
        if str(name).strip().upper() == "NIFTY 50":
            for k in ("percentChange", "percChange", "pChange"):
                if k in row and row[k] is not None:
                    try:
                        pct = float(row[k])
                    except Exception:
                        pass
                    break
            break
    trend = "BULLISH" if pct > 0 else "BEARISH"
    return trend, pct

def pick_sectors(nse: NSE, trend: str, n: int = TOP_SECTORS) -> pd.DataFrame:
    """
    From /api/allIndices, take sector indices only and rank by percentChange.
    - BULLISH  → top N sectors with highest positive % change
    - BEARISH  → top N sectors with most negative % change (lowest)
    Returns full ranked DataFrame; caller picks first n rows.
    """
    j = nse.all_indices()
    items = j.get("data") or j
    rows = []
    sector_set = set(SECTOR_INDICES)
    for row in items:
        name = str(row.get("index", row.get("indexSymbol", row.get("indexName", "")))).strip()
        if name in sector_set:
            pct = None
            for k in ("percentChange", "percChange", "pChange"):
                if k in row and row[k] is not None:
                    try:
                        pct = float(row[k])
                    except Exception:
                        pass
                    break
            if pct is None:
                continue
            rows.append({"sector": name, "percentChange": pct})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # BULLISH → sort descending (best performers first)
    # BEARISH → sort ascending (worst performers first)
    df = df.sort_values("percentChange", ascending=(trend == "BEARISH")).reset_index(drop=True)
    return df

def top_stocks_in_sector(nse: NSE, sector_name: str, count: int, trend: str) -> pd.DataFrame:
    """
    From /api/equity-stockIndices?index=SECTOR, pick top stocks by pChange.
    - BULLISH → highest pChange stocks
    - BEARISH → lowest pChange stocks
    """
    data = nse.index_constituents(sector_name)
    rows = []
    for d in data:
        sym = d.get("symbol")
        lp  = d.get("lastPrice") or d.get("last") or d.get("lastprice")
        chg = None
        for k in ("pChange", "perChange", "percentChange", "percChange"):
            if k in d and d[k] is not None:
                try:
                    chg = float(d[k])
                except Exception:
                    pass
                break
        vol = d.get("totalTradedVolume") or d.get("tradedQuantity") or d.get("volume")
        if sym and lp is not None and chg is not None:
            rows.append({"symbol": sym, "lastPrice": float(lp), "pChange": float(chg), "volume": vol})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("pChange", ascending=(trend == "BEARISH")).head(count).reset_index(drop=True)
    return df

# ---------- Streamlit UI ----------
st.set_page_config(page_title="NSE Stock Filter (9:20 click)", page_icon="📈", layout="centered")

st.title("📈 NSE Intraday Stock Filter")
st.caption(
    "Finds market trend from NIFTY 50 → picks **Top 2 sectors** "
    "(leaders if bullish, laggards if bearish) → shows **3 stocks per sector = 6 stocks total**."
)

colA, colB = st.columns(2)
with colA:
    h = st.number_input("Gate Hour (IST)", min_value=9, max_value=11, value=DEFAULT_GATE[0], step=1)
with colB:
    m = st.number_input("Gate Minute", min_value=0, max_value=59, value=DEFAULT_GATE[1], step=1)

stocks_per_sector = st.slider("Stocks per sector", 2, 5, DEFAULT_STOCK_COUNT, 1)
allow_early = st.checkbox("Override time gate (allow before gate)", value=False)

st.divider()

if st.button("🔎 Run Filter"):
    try:
        now = ist_now()
        gate_time = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        if (not allow_early) and (now < gate_time):
            st.warning(f"⏳ Wait until {gate_time.strftime('%I:%M %p')} IST to run (or tick Override).")
            st.stop()

        st.write(f"🕒 Time: **{now.strftime('%I:%M:%S %p')} IST**")

        nse = NSE()

        # ── 1) Market trend from NIFTY 50 ──────────────────────────────────
        trend, nifty_pct = nifty50_trend(nse)
        trend_emoji = "🟢" if trend == "BULLISH" else "🔴"
        st.subheader(f"{trend_emoji} Market Trend: **{trend}** (NIFTY 50: {nifty_pct:.2f}%)")

        if trend == "BULLISH":
            st.info("📊 NIFTY is **positive** → selecting **Top 2 gaining sectors** and their **top 3 stocks** each.")
        else:
            st.info("📊 NIFTY is **negative** → selecting **Top 2 losing sectors** and their **bottom 3 stocks** each.")

        # ── 2) Sector ranking ───────────────────────────────────────────────
        sec_df = pick_sectors(nse, trend, n=TOP_SECTORS)
        if sec_df.empty:
            st.error("Could not fetch sector data. Try again.")
            st.stop()

        st.write("**Full Sector Ranking** (sorted by % change):")
        st.dataframe(sec_df, use_container_width=True)

        selected_sectors = sec_df.head(TOP_SECTORS)["sector"].tolist()
        st.success(f"✅ Selected Sectors → **{selected_sectors[0]}** & **{selected_sectors[1]}**")

        # ── 3) Top stocks from each of the 2 selected sectors ──────────────
        st.subheader(f"🎯 Top {stocks_per_sector} Stocks per Sector  ({stocks_per_sector * TOP_SECTORS} total)")

        all_stocks = []
        for i, sector in enumerate(selected_sectors, start=1):
            st.markdown(f"#### Sector {i}: {sector}")
            stocks_df = top_stocks_in_sector(nse, sector, stocks_per_sector, trend)
            if stocks_df.empty:
                st.warning(f"Could not fetch constituents for **{sector}**.")
                continue
            stocks_df.insert(0, "sector", sector)   # add sector column for clarity
            st.dataframe(stocks_df, use_container_width=True)
            all_stocks.append(stocks_df)

        if all_stocks:
            combined = pd.concat(all_stocks, ignore_index=True)
            st.divider()
            st.subheader("📋 Combined View — All Selected Stocks")
            st.dataframe(combined, use_container_width=True)

        st.caption("Tip: Re-run after a minute for updated rankings. Selection always respects the current market trend.")

    except Exception as e:
        st.error(f"Error: {e}")
