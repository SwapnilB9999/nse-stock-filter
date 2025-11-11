NSE Stock Filter – Intraday Candidates (9:20–9:30 IST)

Gate time (configurable): waits for the first 5–15 minutes to stabilize.

Reads market breadth → picks bullish/bearish sector → returns 2–3 liquid stocks.

Built for signals discovery only (no auto-trading).

Educational; use with your own discretion and data license.

Run locally

pip install -r requirements.txt
streamlit run nse_stock_filter_app.py


Config

Gate hour/minute (default 9:20)

Number of stocks to show (2 or 3)

Quick QA checklist (so the demo feels solid)

✅ Gate time defaults to 9:20 (not fixed 9:30).

✅ One click flow: “Run Filter” shows result only once; no spamming entries.

✅ NSE rate-limit friendly (use a single requests.Session, modest calls).

✅ Clear “Educational only” note on the page.

✅ Show timestamp (IST) and universe scanned (e.g., NIFTY50).
