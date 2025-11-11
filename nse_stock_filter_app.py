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
DEFAULT_STOCK_COUNT = 3
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
        # returns list of indices with percentChange
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
    items = j.get("data") or j  # sometimes the list is directly at root
    pct = 0.0
    for row in items:
        name = row.get("index", row.get("indexSymbol", row.get("indexName", "")))
        if str(name).strip().upper() == "NIFTY 50":
            # percent change key names vary
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

def pick_sector(nse: NSE, trend: str) -> pd.DataFrame:
    """
    From /api/allIndices, take sector indices only and rank by percentChange.
    """
    j = nse.all_indices()
    items = j.get("data") or j
    rows = []
    sector_set = set(SECTOR_INDICES)
    for row in items:
        name = str(row.get("index", row.get("indexSymbol", row.get("indexName", "")))).strip()
        if name in sector_set:
            # normalize % change
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
    df = df.sort_values("percentChange", ascending=(trend == "BEARISH")).reset_index(drop=True)
    return df

def top_stocks_in_sector(nse: NSE, sector_name: str, count: int, trend: str) -> pd.DataFrame:
    """
    From /api/equity-stockIndices?index=SECTOR, pick top/bottom by pChange.
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

st.title("📈 NSE Intraday Stock Filter (by_swapnil)")
st.caption("Finds market trend from NIFTY 50, picks leading/lagging sector, and shows top 2–3 stocks from that sector.")

colA, colB = st.columns(2)
with colA:
    h = st.number_input("Gate Hour (IST)", min_value=9, max_value=11, value=DEFAULT_GATE[0], step=1)
with colB:
    m = st.number_input("Gate Minute", min_value=0, max_value=59, value=DEFAULT_GATE[1], step=1)

num_stocks = st.slider("How many stocks to display", 2, 5, DEFAULT_STOCK_COUNT, 1)
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

        # 1) Market trend from NIFTY 50
        trend, nifty_pct = nifty50_trend(nse)
        trend_emoji = "🟢" if trend == "BULLISH" else "🔴"
        st.subheader(f"{trend_emoji} Market Trend: **{trend}** (NIFTY 50: {nifty_pct:.2f}%)")

        # 2) Sector ranking
        sec_df = pick_sector(nse, trend)
        if sec_df.empty:
            st.error("Could not fetch sector data. Try again.")
            st.stop()

        top_sector = sec_df.iloc[0]['sector']
        st.write("**Sector Ranking** (by % change):")
        st.dataframe(sec_df, use_container_width=True)

        st.success(f"Selected Sector ➜ **{top_sector}**")

        # 3) Top stocks in selected sector
        stocks_df = top_stocks_in_sector(nse, top_sector, num_stocks, trend)
        if stocks_df.empty:
            st.error("Could not fetch constituents for the selected sector.")
            st.stop()

        # display results
        st.subheader("🎯 Selected Stocks")
        st.dataframe(stocks_df, use_container_width=True)

        st.caption("Tip: Re-run after a minute if you want updated rankings. The selection respects market trend.")
    except Exception as e:
        st.error(f"Error: {e}")
