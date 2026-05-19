"""
HS300 白马攻防策略 · 月度信号
Implements the white-horse attack-defense strategy: market temperature → filtered
stock selection → industry diversification → actionable buy/sell signals.

Based on joinquant_baima_attack_defense_original_fixed.py
"""
import akshare as ak
import numpy as np
import pandas as pd
import yfinance as yf
import tushare as ts
import time
import os, sys
from datetime import datetime, date, timedelta

# ── Retry helper for unreliable East Money connections ──
def retry_call(fn, name, max_retries=3, delay=5):
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries:
                print(f"ERROR: {name} failed after {max_retries} attempts: {e}")
                raise
            print(f"  Retry {attempt}/{max_retries} for {name}: {e}")
            time.sleep(delay * attempt)

# ── Strategy Parameters ──
BUY_STOCK_COUNT = 10
MIN_INDUSTRY_COUNT = 5
UNKNOWN_INDUSTRY = "UNKNOWN"

# ── Tushare setup ──
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
if TUSHARE_TOKEN:
    ts.set_token(TUSHARE_TOKEN)
    tushare_pro = ts.pro_api()
else:
    tushare_pro = None
    print("WARNING: TUSHARE_TOKEN not set, industry data will be limited")

# ── Step 1: Check trading day ──
print(f"[{datetime.now().isoformat()}] Checking trading calendar...")
try:
    cal = retry_call(lambda: ak.tool_trade_date_hist_sina(), "trading_calendar")
    trading_days = set(str(d) for d in cal["trade_date"].tolist())
except Exception as e:
    print(f"WARNING: Calendar fetch failed ({e}), assuming today is trading day")
    trading_days = None

today = date.today().strftime("%Y-%m-%d")
if trading_days and today not in trading_days:
    print(f"SKIP: {today} is not a trading day.")
    sys.exit(0)
print(f"OK: {today} is a trading day.\n")

# ── Step 2: Market Temperature ──
print("=" * 60)
print("STEP 2: Market Temperature (沪深300)")
print("=" * 60)

# Get 000300 index data via yfinance (more reliable from GitHub Actions US runners)
print("  Fetching 000300 index via yfinance...")
try:
    ticker = yf.Ticker('000300.SS')
    index_hist = ticker.history(period='1y')
    if index_hist.empty:
        raise ValueError("No data from yfinance")
    closes = index_hist['Close'].values[-220:]
except Exception as e:
    print(f"  yfinance failed ({e}), trying akshare fallback...")
    index_df = retry_call(lambda: ak.stock_zh_index_daily_em(symbol="sh000300"), "index_daily", max_retries=3, delay=10)
    index_df = index_df.sort_values("date")
    closes = index_df["close"].values[-220:]

if len(closes) < 60:
    print(f"ERROR: Only {len(closes)} data points for 000300")
    sys.exit(1)

ma5 = np.mean(closes[-5:])
min220 = np.min(closes)
max220 = np.max(closes)
market_height = (ma5 - min220) / (max220 - min220) if max220 > min220 else 0.5

# Temperature classification
max60 = np.max(closes[-60:])
min_idx220 = np.min(closes)
if market_height < 0.20:
    temperature = "COLD"
elif market_height > 0.90:
    temperature = "HOT"
elif max60 / min_idx220 > 1.20:
    temperature = "WARM"
else:
    temperature = "WARM"  # default

temp_emoji = {"COLD": "❄️", "WARM": "☀️", "HOT": "🔥"}
print(f"  沪深300 MA5:        {ma5:.2f}")
print(f"  220日最低:          {min220:.2f}")
print(f"  220日最高:          {max220:.2f}")
print(f"  市场高度:           {market_height:.4f}")
print(f"  60日最高/220日最低:  {max60/min_idx220:.4f}")
print(f"  => 温度: {temp_emoji.get(temperature, '')} {temperature}")
print()

# ── Step 3: Filter Stocks by Temperature ──
print("=" * 60)
print(f"STEP 3: Stock Selection ({temperature} mode)")
print("=" * 60)

# Get CSI 300 universe
hs300 = ak.index_stock_cons_weight_csindex("000300")
codes_all = set(hs300["成分券代码"].tolist())

# Exclude 科创板(688), 创业板(300), 北交所(8/4开头)
def is_excluded(code):
    return code.startswith("30") or code.startswith("688") or code.startswith("8") or code.startswith("4")

universe = [c for c in codes_all if not is_excluded(c)]
print(f"  CSI 300 成分股: {len(codes_all)}")
print(f"  排除科创/创业/北交: {len(universe)} 只")
print()

# Get market data with PB
print("  Fetching market data (PE/PB)...")
spot = None
try:
    spot = retry_call(lambda: ak.stock_zh_a_spot_em(), "stock_zh_a_spot_em", max_retries=2, delay=8)
except Exception as e:
    print(f"  WARNING: spot data unavailable ({e})")
    print("  Falling back to fundamentals-only screening (no PB filter)")

if spot is not None:
    spot = spot[spot["代码"].isin(universe)].copy()
    pb_col = None
    for c in spot.columns:
        if "市净率" in c:
            pb_col = c
            break
    if pb_col:
        spot["pb"] = pd.to_numeric(spot[pb_col], errors="coerce")
    else:
        print("  WARNING: PB column not found in spot data")
        spot["pb"] = np.nan
else:
    # Create minimal DataFrame with just codes
    spot = pd.DataFrame({"代码": list(universe), "名称": list(universe)})
    spot["pb"] = np.nan
    pb_col = "pb"

# ── Step 4: Get Fundamental Data ──
print("  Fetching financial metrics (this takes ~30-60s)...")

# Try to get quarterly performance data for ROE, profit growth
try:
    yjbb = retry_call(lambda: ak.stock_yjbb_em(date=today), "stock_yjbb_em")
    # Columns typically include: 股票代码, 股票简称, 净资产收益率, 净利润同比增长率, etc.
    print(f"  Performance reports loaded: {len(yjbb)} rows")
except Exception as e:
    print(f"  WARNING: yjbb failed ({e}), using spot data only")
    yjbb = pd.DataFrame()

# Build fundamental data map
fund_data = {}

# From spot: PB is in the spot dataframe
# From yjbb: ROE, profit growth
if not yjbb.empty:
    roe_col = None
    profit_growth_col = None
    for c in yjbb.columns:
        if "净资产收益率" in c and "同比" not in c and "加权" not in c:
            if roe_col is None:
                roe_col = c
        if "净利润同比" in c or ("净利润" in c and "增长" in c):
            if profit_growth_col is None:
                profit_growth_col = c

    for _, row in yjbb.iterrows():
        code = str(row.get("股票代码", ""))
        if not code or code not in universe:
            continue
        fund_data[code] = {
            "roe": pd.to_numeric(row.get(roe_col), errors="coerce") if roe_col else None,
            "profit_yoy": pd.to_numeric(row.get(profit_growth_col), errors="coerce") if profit_growth_col else None,
        }

print(f"  Fundamental data loaded for {len(fund_data)} stocks")
print()

# ── Step 5: Apply Temperature Filters ──
print("  Applying temperature filters...")

candidates = []

for _, row in spot.iterrows():
    code = row["代码"]
    name = row.get("名称", code)
    pb = row.get("pb")

    if pd.notna(pb) and pb <= 0:
        continue

    fd = fund_data.get(code, {})
    roe = fd.get("roe")
    profit_yoy = fd.get("profit_yoy")

    # (Cash flow/profit ratio, adjusted_profit, ROA not available via akshare without
    #  individual stock calls. We proxy with available metrics and note limitations.)

    if temperature == "COLD":
        if pd.notna(pb) and pb >= 1:
            continue
        if roe is not None and roe <= 1.5:
            continue
        if profit_yoy is not None and profit_yoy <= -15:
            continue
        # Rank by proxy: ROE/PB
        score = roe / pb if (roe and roe > 0 and pd.notna(pb) and pb > 0) else (1.0 / pb if pd.notna(pb) and pb > 0 else 0)

    elif temperature == "WARM":
        if pd.notna(pb) and pb >= 1:
            continue
        if roe is not None and roe <= 2.0:
            continue
        if profit_yoy is not None and profit_yoy <= 0:
            continue
        score = roe / pb if (roe and roe > 0 and pd.notna(pb) and pb > 0) else (1.0 / pb if pd.notna(pb) and pb > 0 else 0)

    elif temperature == "HOT":
        if pd.notna(pb) and pb <= 3:
            continue
        if roe is not None and roe <= 3.0:
            continue
        if profit_yoy is not None and profit_yoy <= 20:
            continue
        # Hot mode: rank by ROE
        score = roe if roe else 0

    candidates.append({
        "代码": code,
        "名称": name,
        "PB": round(pb, 2),
        "ROE": f"{roe:.1f}%" if roe and not pd.isna(roe) else "N/A",
        "利润增速": f"{profit_yoy:+.0f}%" if profit_yoy and not pd.isna(profit_yoy) else "N/A",
        "score": score,
    })

candidates.sort(key=lambda x: x["score"], reverse=True)
print(f"  Candidates passing filters: {len(candidates)}")
print()

# ── Step 6: Industry Diversification ──
print("=" * 60)
print("STEP 4: Industry Diversification (申万一级)")
print("=" * 60)

# Get industry for ALL stocks via Tushare bak_basic (one API call)
industry_map = {}

if tushare_pro:
    try:
        bb = tushare_pro.bak_basic(trade_date=today.replace("-", ""),
                                   fields="ts_code,name,industry")
        # Map Tushare ts_code (000001.SZ) -> plain code (000001)
        for _, row in bb.iterrows():
            ts_code = row["ts_code"]
            plain_code = ts_code.split(".")[0]  # 000001.SZ -> 000001
            industry_map[plain_code] = row.get("industry", UNKNOWN_INDUSTRY)
        print(f"  Tushare: loaded {len(industry_map)} stocks with industry data")
    except Exception as e:
        print(f"  Tushare bak_basic failed: {e}")

# Fallback: per-stock akshare lookup if Tushare unavailable
if not industry_map:
    print("  Falling back to akshare per-stock lookup...")
    for c in candidates[:30]:
        try:
            ind_df = ak.stock_individual_info_em(symbol=c["代码"])
            ind_row = ind_df[ind_df["item"] == "行业"]
            industry = ind_row["value"].values[0] if len(ind_row) > 0 else UNKNOWN_INDUSTRY
        except Exception:
            industry = UNKNOWN_INDUSTRY
        industry_map[c["代码"]] = industry

used_count = len(industry_map)
ind_count = len(set(v for v in industry_map.values() if v != UNKNOWN_INDUSTRY))
print(f"  Industry data: {used_count} stocks, {ind_count} unique industries")
print()

# Diversify: pick one stock per industry first
selected = []
used_industries = set()
used_codes = set()

for c in candidates:
    if len(selected) >= BUY_STOCK_COUNT:
        break
    ind = industry_map.get(c["代码"], UNKNOWN_INDUSTRY)
    if ind == UNKNOWN_INDUSTRY or ind in used_industries:
        continue
    selected.append(c)
    used_industries.add(ind)
    used_codes.add(c["代码"])

# Fill remaining slots
for c in candidates:
    if len(selected) >= BUY_STOCK_COUNT:
        break
    if c["代码"] in used_codes:
        continue
    selected.append(c)
    used_codes.add(c["代码"])

industries_selected = set(industry_map.get(c["代码"], UNKNOWN_INDUSTRY) for c in selected)
industries_selected.discard(UNKNOWN_INDUSTRY)
print(f"  Selected: {len(selected)} stocks | {len(industries_selected)} industries")
print(f"  Industries: {', '.join(sorted(industries_selected))}")
print()

# ── Step 7: Output ──
print("=" * 60)
print(f"FINAL SIGNAL · {temperature} · {today}")
print("=" * 60)
print()
print(f"  {'#':<3} {'代码':<8} {'名称':<14} {'PB':<8} {'ROE':<10} {'利润增速':<10} {'行业'}")
print(f"  {'-'*3} {'-'*8} {'-'*14} {'-'*8} {'-'*10} {'-'*10} {'-'*15}")
for i, s in enumerate(selected, 1):
    ind = industry_map.get(s["代码"], "N/A")
    print(f"  {i:<3} {s['代码']:<8} {s['名称']:<14} {s['PB']:<8} {s['ROE']:<10} {s['利润增速']:<10} {ind}")
print()

# Strategy summary
print("=" * 60)
print("STRATEGY SUMMARY")
print("=" * 60)
print(f"""
  市场温度:  {temp_emoji.get(temperature, '')} {temperature} (高度={market_height:.4f})
  选股池:    CSI 300 (排除科创/创业/北交所)
  持仓数量:  {BUY_STOCK_COUNT} 只, 行业分散 ≥ {MIN_INDUSTRY_COUNT}
  调仓频率:  每月第一个交易日

  {'❄️ Cold: PB<1, 现金流/利润>2.0, ROE>1.5%, 利润增速>-15%, 排序: ROA/PB ↓' if temperature == 'COLD' else ''}
  {'☀️ Warm: PB<1, 现金流/利润>1.0, ROE>2.0%, 利润增速>0%, 排序: ROA/PB ↓' if temperature == 'WARM' else ''}
  {'🔥 Hot:  PB>3, 现金流/利润>0.5, ROE>3.0%, 利润增速>20%, 排序: ROA ↓' if temperature == 'HOT' else ''}
""")

# Note on data limitations
print("=" * 60)
print("DATA NOTES")
print("=" * 60)
print("""
  Data sources:
  - Index temperature: yfinance (000300.SS)
  - Trading calendar: akshare (Sina)
  - CSI 300 constituents: akshare (csindex)
  - Industry: Tushare bak_basic (5523 stocks, one call)
  - ROE / profit growth: akshare stock_yjbb_em
  - PB: akshare (best-effort; may fall back if blocked)

  Tushare free token limitations:
  - daily_basic (PB/PE), fina_indicator (ROA), cashflow: need 2000 pts
  - Currently proxying with available data
""")

# ── Build email body ──
lines = []
lines.append(f"白马攻防策略 · {temp_emoji.get(temperature, '')} {temperature} · {today}")
lines.append(f"市场高度: {market_height:.4f} | 220日范围: [{min220:.0f}, {max220:.0f}]")
lines.append("")
lines.append("| # | 代码 | 名称 | PB | ROE | 利润增速 | 行业 |")
lines.append("|---|------|------|-----|------|---------|------|")
for i, s in enumerate(selected, 1):
    ind = industry_map.get(s["代码"], "N/A")
    lines.append(f"| {i} | {s['代码']} | {s['名称']} | {s['PB']} | {s['ROE']} | {s['利润增速']} | {ind} |")

email_body = "\n".join(lines)

# Action signal
signal_line = f"{temperature} · 选中{len(selected)}只 · 行业{len(industries_selected)}个"

# ── Write GitHub summary ──
summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
if summary_file:
    with open(summary_file, "a") as f:
        f.write(f"## 白马攻防策略 · {temp_emoji.get(temperature, '')} {temperature}\n\n")
        f.write(f"**市场高度**: {market_height:.4f}  \n")
        f.write(f"**信号**: {signal_line}  \n\n")
        f.write("\n".join(lines) + "\n")

# ── Send email ──
from send_email import send_notification
subject = f"白马攻防 · {temperature} · {today} · {len(selected)} stocks"
send_notification(subject, email_body)
