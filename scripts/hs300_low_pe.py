"""
HS300 Low PE Screener
On the first trading day of each month, finds the 10 lowest PE stocks in CSI 300
and analyzes their ROE. Runs monthly on GitHub Actions.
"""
import akshare as ak
import pandas as pd
import os
import sys
from datetime import datetime, date, timedelta

# ── Config ──
TOP_N = 10
INDEX_CODE = "000300"

# ── Step 1: Check if today is a trading day ──
print(f"[{datetime.now().isoformat()}] Checking trading calendar...")
try:
    cal = ak.tool_trade_date_hist_sina()
    trading_days = set(str(d) for d in cal["trade_date"].tolist())
except Exception as e:
    print(f"WARNING: Trading calendar fetch failed ({e}), assuming today is trading day")
    trading_days = None

today = date.today().strftime("%Y-%m-%d")
if trading_days and today not in trading_days:
    print(f"⏭ {today} is not a trading day. Skipping.")
    sys.exit(0)

print(f"✓ {today} is a trading day. Running screener...")

# ── Step 2: Get CSI 300 constituents ──
print("Fetching CSI 300 constituents...")
try:
    hs300 = ak.index_stock_cons_weight_csindex(INDEX_CODE)
    stock_codes = hs300["成分券代码"].tolist()
    # Map code to name
    code_name_map = dict(zip(hs300["成分券代码"], hs300["成分券名称"]))
except Exception as e:
    print(f"ERROR: Failed to get CSI 300 constituents: {e}")
    sys.exit(1)

print(f"✓ Got {len(stock_codes)} constituents")

# ── Step 3: Get PE/PB/ROE data ──
print("Fetching fundamental data (this may take 30-60 seconds)...")

# Use East Money real-time market data which includes PE
try:
    spot_df = ak.stock_zh_a_spot_em()
    spot_df = spot_df[spot_df["代码"].isin(stock_codes)].copy()
    print(f"✓ Got market data for {len(spot_df)} stocks")
except Exception as e:
    print(f"ERROR: Failed to fetch market data: {e}")
    sys.exit(1)

# ── Step 4: Filter and rank by PE ──
# PE column in stock_zh_a_spot_em is '市盈率-动态'
pe_col = None
for col in spot_df.columns:
    if "市盈率" in col:
        pe_col = col
        break

if not pe_col:
    print("ERROR: Could not find PE column")
    sys.exit(1)

# Filter: PE > 0 (exclude negative earnings)
df = spot_df[spot_df[pe_col] > 0].copy()
df = df.dropna(subset=[pe_col])

# Sort by PE ascending, take top N
df_low_pe = df.nsmallest(TOP_N, pe_col)

# ── Step 5: Get ROE for the selected stocks ──
print(f"Fetching ROE for top {TOP_N} low PE stocks...")
results = []

for _, row in df_low_pe.iterrows():
    code = row["代码"]
    name = row.get("名称", code_name_map.get(code, code))
    pe = row[pe_col]

    # Try to get ROE from individual stock info
    try:
        info = ak.stock_individual_info_em(symbol=code)
        roe_row = info[info["item"] == "净资产收益率"]
        roe = float(roe_row["value"].values[0]) if len(roe_row) > 0 else None
    except Exception:
        roe = None

    # Get PB ratio
    pb_col = None
    for col in spot_df.columns:
        if "市净率" in col:
            pb_col = col
            break
    pb = row.get(pb_col) if pb_col else None

    results.append({
        "代码": code,
        "名称": name,
        "PE": round(pe, 2),
        "PB": round(pb, 2) if pb and pd.notna(pb) else "N/A",
        "ROE": f"{roe:.2f}%" if roe else "N/A",
    })

# ── Step 6: Format output ──
df_result = pd.DataFrame(results)
df_result.index = range(1, len(df_result) + 1)

print(f"\n══════ CSI 300 最低 PE Top {TOP_N} ══════")
print(df_result.to_string())
print(f"══════════════════════════════════\n")

# ── Build email body ──
lines = [f"沪深300 最低PE Top {TOP_N} · {today}"]
lines.append("")
lines.append("| # | 代码 | 名称 | PE | PB | ROE |")
lines.append("|---|------|------|-----|-----|------|")
for _, r in df_result.iterrows():
    lines.append(f"| {r.name} | {r['代码']} | {r['名称']} | {r['PE']} | {r['PB']} | {r['ROE']} |")

email_body = "\n".join(lines)

# Write output for GitHub Actions summary
summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
if summary_file:
    with open(summary_file, "a") as f:
        f.write(f"## CSI 300 Lowest PE Top {TOP_N} · {today}\n\n")
        f.write("\n".join(lines) + "\n")

# ── Send email ──
from send_email import send_notification
subject = f"CSI 300 低PE选股 · {today} · Top {TOP_N}"
send_notification(subject, email_body)
