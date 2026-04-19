"""
report.py — สร้างรายงาน backtest แบบ text + HTML

HTML report ใช้ Chart.js (CDN) วาด equity curve + trade markers
ไม่ต้องติดตั้ง lib เพิ่ม
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backtest.engine import BacktestResult


def format_text_report(metrics: dict) -> str:
    """รายงาน text สั้น ๆ"""
    pf = metrics["profit_factor"]
    lines = [
        "=" * 55,
        f"  BACKTEST REPORT — {metrics['symbol']}",
        "=" * 55,
        f"  เงินเริ่มต้น     : {metrics['start_cash']:>15,.2f} THB",
        f"  equity สุดท้าย   : {metrics['end_equity']:>15,.2f} THB",
        f"  Total Return    : {metrics['total_return_pct']:>15.2f} %",
        f"  CAGR            : {metrics['cagr_pct']:>15.2f} %",
        f"  Max Drawdown    : {metrics['max_drawdown_pct']:>15.2f} %",
        "-" * 55,
        f"  Sharpe          : {metrics['sharpe']:>15.2f}",
        f"  Sortino         : {metrics['sortino']:>15.2f}",
        f"  Profit Factor   : {str(pf):>15}",
        f"  Expectancy      : {metrics['expectancy']:>15.2f} THB/trade",
        "-" * 55,
        f"  รวมเทรด         : {metrics['total_trades']:>15,} ครั้ง",
        f"  Completed sells : {metrics['total_sells']:>15,}",
        f"  Win rate        : {metrics['win_rate_pct']:>14.1f} %",
        f"  Wins / Losses   : {str(metrics['wins']) + ' / ' + str(metrics['losses']):>15}",
        f"  Avg win         : {metrics['avg_win']:>15,.2f} THB",
        f"  Avg loss        : {metrics['avg_loss']:>15,.2f} THB",
        f"  Best trade      : {metrics['best_trade']:>15,.2f} THB",
        f"  Worst trade     : {metrics['worst_trade']:>15,.2f} THB",
        f"  Stop-loss hits  : {metrics['stop_loss_hits']:>15,}",
        f"  Total fees paid : {metrics['total_fees']:>15,.2f} THB",
        "=" * 55,
    ]
    return "\n".join(lines)


def save_trades_csv(result, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "iso", "symbol", "action", "price",
                         "amount_thb", "amount_crypto", "fee", "pnl", "reason"])
        for t in result.trades:
            writer.writerow([
                t.time,
                datetime.fromtimestamp(t.time).isoformat(),
                t.symbol, t.action,
                f"{t.price:.2f}", f"{t.amount_thb:.2f}",
                f"{t.amount_crypto:.8f}", f"{t.fee:.4f}",
                f"{t.pnl:.2f}", t.reason,
            ])


def save_html_report(result, metrics: dict, path: Path) -> None:
    """รายงาน HTML พร้อมกราฟ equity curve (Chart.js from CDN)"""
    path.parent.mkdir(parents=True, exist_ok=True)

    equity_data = [
        {"x": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
         "y": round(eq, 2)}
        for ts, eq in result.equity_curve
    ]

    buy_markers  = [
        {"x": datetime.fromtimestamp(t.time).strftime("%Y-%m-%d %H:%M"),
         "y": round(t.price, 2)}
        for t in result.trades if t.action == "buy"
    ]
    sell_markers = [
        {"x": datetime.fromtimestamp(t.time).strftime("%Y-%m-%d %H:%M"),
         "y": round(t.price, 2)}
        for t in result.trades if t.action == "sell"
    ]

    def _fmt(n, decimals=2, prefix="", suffix=""):
        if isinstance(n, str):
            return n
        return f"{prefix}{n:,.{decimals}f}{suffix}"

    pnl_class = "positive" if metrics["total_return_pct"] >= 0 else "negative"

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>Backtest Report — {metrics['symbol']}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 1200px; margin: 30px auto; padding: 20px;
    background: #f7f8fa; color: #1a1a1a;
}}
h1 {{ margin-top: 0; }}
.subtitle {{ color: #666; margin-bottom: 24px; }}
.grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px; margin-bottom: 28px;
}}
.card {{
    background: #fff; padding: 16px 18px; border-radius: 10px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}}
.card .label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
.card .value {{ font-size: 22px; font-weight: 600; margin-top: 4px; }}
.positive {{ color: #0b8f3a; }}
.negative {{ color: #c63838; }}
.chart-wrap {{
    background: #fff; padding: 20px; border-radius: 10px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 28px;
}}
table {{ width: 100%; border-collapse: collapse; background: #fff;
         border-radius: 10px; overflow: hidden;
         box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #f0f2f5; font-weight: 600; font-size: 13px; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>

<h1>📊 Backtest Report — {metrics['symbol']}</h1>
<div class="subtitle">สร้างเมื่อ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>

<div class="grid">
  <div class="card">
    <div class="label">Total Return</div>
    <div class="value {pnl_class}">{_fmt(metrics['total_return_pct'], 2, suffix=' %')}</div>
  </div>
  <div class="card">
    <div class="label">CAGR</div>
    <div class="value">{_fmt(metrics['cagr_pct'], 2, suffix=' %')}</div>
  </div>
  <div class="card">
    <div class="label">Max Drawdown</div>
    <div class="value negative">{_fmt(metrics['max_drawdown_pct'], 2, suffix=' %')}</div>
  </div>
  <div class="card">
    <div class="label">Sharpe Ratio</div>
    <div class="value">{_fmt(metrics['sharpe'])}</div>
  </div>
  <div class="card">
    <div class="label">Sortino</div>
    <div class="value">{_fmt(metrics['sortino'])}</div>
  </div>
  <div class="card">
    <div class="label">Profit Factor</div>
    <div class="value">{metrics['profit_factor']}</div>
  </div>
  <div class="card">
    <div class="label">Win Rate</div>
    <div class="value">{_fmt(metrics['win_rate_pct'], 1, suffix=' %')}</div>
  </div>
  <div class="card">
    <div class="label">Total Trades</div>
    <div class="value">{metrics['total_trades']:,}</div>
  </div>
</div>

<div class="chart-wrap">
  <canvas id="equityChart" height="90"></canvas>
</div>

<table>
  <thead>
    <tr><th colspan="2">รายละเอียด</th></tr>
  </thead>
  <tbody>
    <tr><td>เงินเริ่มต้น</td><td class="num">{_fmt(metrics['start_cash'])} THB</td></tr>
    <tr><td>Equity สุดท้าย</td><td class="num">{_fmt(metrics['end_equity'])} THB</td></tr>
    <tr><td>Avg win</td><td class="num positive">{_fmt(metrics['avg_win'])} THB</td></tr>
    <tr><td>Avg loss</td><td class="num negative">{_fmt(metrics['avg_loss'])} THB</td></tr>
    <tr><td>Best trade</td><td class="num positive">{_fmt(metrics['best_trade'])} THB</td></tr>
    <tr><td>Worst trade</td><td class="num negative">{_fmt(metrics['worst_trade'])} THB</td></tr>
    <tr><td>Expectancy / trade</td><td class="num">{_fmt(metrics['expectancy'])} THB</td></tr>
    <tr><td>Total fees</td><td class="num">{_fmt(metrics['total_fees'])} THB</td></tr>
    <tr><td>Stop-loss hits</td><td class="num">{metrics['stop_loss_hits']:,}</td></tr>
    <tr><td>Wins / Losses</td><td class="num">{metrics['wins']} / {metrics['losses']}</td></tr>
  </tbody>
</table>

<script>
const ctx = document.getElementById('equityChart');
new Chart(ctx, {{
    type: 'line',
    data: {{
        datasets: [
            {{
                label: 'Equity',
                data: {json.dumps(equity_data)},
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59,130,246,0.08)',
                borderWidth: 2, pointRadius: 0, fill: true, tension: 0.2,
            }},
        ]
    }},
    options: {{
        responsive: true,
        plugins: {{ legend: {{ display: true }}, title: {{ display: true, text: 'Equity Curve' }} }},
        scales: {{
            x: {{ ticks: {{ maxTicksLimit: 10 }} }},
            y: {{ ticks: {{ callback: v => v.toLocaleString() }} }}
        }}
    }}
}});
</script>

</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
