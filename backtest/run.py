"""
run.py — CLI entry สำหรับรัน backtest

Examples:
    # ใช้ cache/API (ข้อมูลจริง 90 วัน)
    python -m backtest.run --symbol BTC_THB --days 90

    # ใช้ synthetic data (offline)
    python -m backtest.run --symbol BTC_THB --synthetic uptrend --bars 500

    # เปลี่ยน resolution / config
    python -m backtest.run --symbol ETH_THB --resolution 240 --cash 200000
"""
import argparse
import sys
from pathlib import Path

# รองรับทั้งการรันเป็น module และสคริปต์ตรง
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.data_loader import get_or_fetch, generate_synthetic
from backtest.engine      import BacktestEngine
from backtest.metrics     import compute_metrics
from backtest.report      import (format_text_report, save_html_report,
                                   save_trades_csv)

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def _bars_per_year(resolution: str) -> int:
    """annualization factor สำหรับ Sharpe"""
    if resolution == "1D":
        return 365
    mins = int(resolution)
    return int(365 * 24 * 60 / mins)


def main():
    p = argparse.ArgumentParser(description="Trade Me Plz Backtest")
    p.add_argument("--symbol", default="BTC_THB")
    p.add_argument("--resolution", default="60",
                   help="1 / 5 / 15 / 60 / 240 / 1D (นาที)")
    p.add_argument("--days", type=int, default=90,
                   help="จำนวนวันย้อนหลัง (ถ้าใช้ข้อมูลจริง)")
    p.add_argument("--cash", type=float, default=100_000,
                   help="เงินเริ่มต้น (THB)")
    p.add_argument("--synthetic",
                   choices=["uptrend", "downtrend", "sideways", "volatile"],
                   help="ใช้ข้อมูล synthetic แทนการ fetch จาก Bitkub")
    p.add_argument("--bars", type=int, default=500,
                   help="จำนวน bars สำหรับ synthetic data")
    p.add_argument("--no-cache", action="store_true",
                   help="ข้าม cache และ fetch ใหม่เสมอ")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--stop-loss", type=float, default=0.03)
    p.add_argument("--min-confidence", type=float, default=0.50)
    p.add_argument("--max-position-pct", type=float, default=0.10)
    args = p.parse_args()

    # ----- 1. โหลดข้อมูล -----
    if args.synthetic:
        print(f"[DATA] ใช้ synthetic {args.synthetic} {args.bars} bars")
        candles = generate_synthetic(n_bars=args.bars, regime=args.synthetic)
    else:
        candles = get_or_fetch(args.symbol, args.resolution,
                                args.days, use_cache=not args.no_cache)

    if not candles:
        print("❌ ไม่มีข้อมูลสำหรับ backtest")
        return 1

    print(f"[DATA] candles = {len(candles)} bars")
    print(f"       period  = {candles[0]['time']} → {candles[-1]['time']}")

    # ----- 2. รัน engine -----
    engine = BacktestEngine(
        starting_cash    = args.cash,
        max_position_pct = args.max_position_pct,
        stop_loss_pct    = args.stop_loss,
        min_confidence   = args.min_confidence,
    )
    print(f"[ENGINE] เริ่มรัน backtest...")
    result = engine.run(candles, symbol=args.symbol, verbose=args.verbose)

    # ----- 3. คำนวณ metrics -----
    metrics = compute_metrics(result,
                              bars_per_year=_bars_per_year(args.resolution))

    # ----- 4. แสดง + save -----
    print()
    print(format_text_report(metrics))

    REPORTS_DIR.mkdir(exist_ok=True)
    tag = args.synthetic or "live"
    prefix = f"{args.symbol}_{args.resolution}_{tag}"

    html_path = REPORTS_DIR / f"{prefix}.html"
    csv_path  = REPORTS_DIR / f"{prefix}_trades.csv"

    save_html_report(result, metrics, html_path)
    save_trades_csv(result, csv_path)

    print(f"\n📄 HTML report: {html_path}")
    print(f"📄 Trades CSV : {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
