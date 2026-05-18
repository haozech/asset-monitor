"""
VOO 200 SMA Weekly Monitor
Checks VOO closing price against 200-day SMA with 3% buffer.
Runs weekly on GitHub Actions.
"""
import yfinance as yf
import os
import sys
from datetime import datetime, date

# ── Config ──
SYMBOL = "VOO"
SMA_PERIOD = 200
BUFFER = 0.03  # 3% buffer zone

# ── Fetch Data ──
print(f"[{datetime.now().isoformat()}] Fetching {SYMBOL} data...")
voo = yf.Ticker(SYMBOL)
hist = voo.history(period="1y")

if len(hist) < SMA_PERIOD:
    print(f"ERROR: Only {len(hist)} data points, need {SMA_PERIOD}")
    sys.exit(1)

close_prices = hist["Close"]
sma200 = close_prices.tail(SMA_PERIOD).mean()
latest_close = close_prices.iloc[-1]
latest_date = close_prices.index[-1].strftime("%Y-%m-%d")
ratio = latest_close / sma200

# ── Signal ──
if ratio < (1 - BUFFER):
    signal = "BELOW"
    action = "减仓 · VOO/QQQ 各降至 17.5% · 减出加至 GLD"
elif ratio > (1 + BUFFER):
    signal = "ABOVE"
    action = "恢复 · 维持基准 VOO35/QQQ35/GLD15/TLT15"
else:
    signal = "NEAR"
    action = "不动 · 在缓冲带内，维持当前持仓"

# ── Output ──
print(f"\n══════ VOO 200 SMA 监控 ══════")
print(f"日期:     {latest_date}")
print(f"收盘价:   ${latest_close:.2f}")
print(f"200 SMA:  ${sma200:.2f}")
print(f"比值:     {ratio:.4f}  ({((ratio-1)*100):+.1f}%)")
print(f"信号:     {signal}")
print(f"操作:     {action}")
print(f"══════════════════════════════\n")

# ── Build email body ──
email_body = f"""
VOO 200 SMA 周线监控

📅 数据日期: {latest_date}
💰 收盘价:   ${latest_close:.2f}
📊 200 SMA:  ${sma200:.2f}
📐 偏离:     {((ratio-1)*100):+.1f}%

{'🟢' if signal == 'ABOVE' else '🔴' if signal == 'BELOW' else '🟡'} 信号: {signal}
📋 操作: {action}

缓冲带: ±{BUFFER*100:.0f}%  |  判断: 周线 · 每月检查一次
"""

# Write output for GitHub Actions log
summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
if summary_file:
    with open(summary_file, "a") as f:
        f.write(f"## VOO 200 SMA: {signal}\n")
        f.write(f"| 指标 | 值 |\n|------|------|\n")
        f.write(f"| 日期 | {latest_date} |\n")
        f.write(f"| 收盘价 | ${latest_close:.2f} |\n")
        f.write(f"| 200 SMA | ${sma200:.2f} |\n")
        f.write(f"| 偏离 | {((ratio-1)*100):+.1f}% |\n")
        f.write(f"| 信号 | {signal} |\n")
        f.write(f"| 操作 | {action} |\n")

# ── Send email ──
from send_email import send_notification
subject = f"VOO 200SMA · {signal} · Close=${latest_close:.0f} SMA200=${sma200:.0f}"
send_notification(subject, email_body)
