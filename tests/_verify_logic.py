"""
_verify_logic.py — stdlib-only test harness (ใช้ได้ไม่ต้องมี pytest)
รันด้วย: python -m tests._verify_logic
ใช้สำหรับ sanity check ใน environment ที่ไม่มี pytest
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Inject ROOT into sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# stub dotenv ถ้าไม่มี
try:
    import dotenv  # noqa
except ImportError:
    sys.modules["dotenv"] = type(sys)("dotenv")
    sys.modules["dotenv"].load_dotenv = lambda *a, **kw: None

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


# ========== RISK MANAGER ==========
print("\n[RISK MANAGER]")
from execution.risk_manager import RiskManager

r = RiskManager(max_position_pct=0.10, max_daily_loss=0.05,
                stop_loss_pct=0.03, min_confidence=0.50)

check("position_size 10% of 10_000 = 1000",
      r.calc_position_size(10_000) == 1000.0)
check("stop_loss buy 1000 = 970",
      r.calc_stop_loss(1000, "buy") == 970.0)
check("stop_loss sell 1000 = 1030",
      r.calc_stop_loss(1000, "sell") == 1030.0)

res = r.approve("BTC_THB", "buy", 0.3, 10_000, 1_000_000)
check("approve rejects low confidence",
      not res.approved and "confidence" in res.reason)

r2 = RiskManager()
r2.daily_loss = 600
res = r2.approve("BTC_THB", "buy", 0.9, 10_000, 1_000_000)
check("approve rejects when daily loss exceeded", not res.approved)

r3 = RiskManager()
r3.open_positions["BTC_THB"] = 1_000_000
res = r3.approve("BTC_THB", "buy", 0.9, 10_000, 1_100_000)
check("approve rejects already-open position", not res.approved)

r4 = RiskManager()
res = r4.approve("BTC_THB", "buy", 0.9, 100, 1_000_000)
check("approve rejects when balance too small", not res.approved)

r5 = RiskManager()
res = r5.approve("BTC_THB", "buy", 0.8, 10_000, 1_000_000)
check("approve happy path", res.approved and res.position_size == 1000.0)
check("open position recorded", r5.open_positions["BTC_THB"] == 1_000_000)

r6 = RiskManager()
r6.open_positions["BTC_THB"] = 1_000_000
check("should_stop_loss triggers at 4% drop",
      r6.should_stop_loss("BTC_THB", 960_000) is True)
check("should_stop_loss no trigger at 2% drop",
      r6.should_stop_loss("BTC_THB", 980_000) is False)
check("should_stop_loss triggers at exact 3%",
      r6.should_stop_loss("BTC_THB", 970_000) is True)
check("should_stop_loss safe when no open position",
      r6.should_stop_loss("DOGE_THB", 100) is False)

r7 = RiskManager()
r7.record_loss(100); r7.record_loss(50)
check("record_loss accumulates", r7.daily_loss == 150)
r7.reset_daily()
check("reset_daily zeros out", r7.daily_loss == 0.0)

r7.open_positions["BTC_THB"] = 1_000_000
r7.close_position("BTC_THB")
check("close_position removes entry", "BTC_THB" not in r7.open_positions)
r7.close_position("NONEXISTENT")  # ต้องไม่ throw
check("close_position safe on missing key", True)


# ========== INDICATORS ==========
print("\n[INDICATORS]")
from brain.indicators import (calc_sma, calc_ema, calc_rsi,
                              calc_bollinger, calc_macd, get_all_indicators)

sma = calc_sma([1, 2, 3, 4, 5], period=3)
check("SMA first 2 are None", sma[:2] == [None, None])
check("SMA[2]=avg(1,2,3)=2", sma[2] == 2)
check("SMA[3]=avg(2,3,4)=3", sma[3] == 3)

ema = calc_ema([100, 110], period=2)
check("EMA[0] = first input", ema[0] == 100)
check("EMA[1] ≈ 106.666", abs(ema[1] - 106.666) < 0.01)

rsi_all_up = calc_rsi([float(i) for i in range(1, 20)], period=14)
check("RSI first 14 = None", rsi_all_up[:14] == [None] * 14)
check("RSI all-gains = 100", rsi_all_up[-1] == 100)

rsi_short = calc_rsi([100, 101, 102], period=14)
check("RSI insufficient data → all None",
      all(v is None for v in rsi_short))

bb = calc_bollinger([100] * 25, period=20)
last = bb[-1]
check("Bollinger constant prices → upper=mid=lower",
      last["mid"] == 100 and last["upper"] == 100 and last["lower"] == 100)

macd = calc_macd([float(i) for i in range(1, 50)])
last = macd[-1]
check("MACD has macd/signal/histogram keys",
      all(k in last for k in ("macd", "signal", "histogram")))
check("MACD = signal + histogram (±0.01)",
      abs(last["macd"] - (last["signal"] + last["histogram"])) < 0.01)

fake_candles = [
    {"close": 100 + i * 0.5, "open": 100 + i * 0.5,
     "high": 101 + i * 0.5, "low": 99 + i * 0.5, "volume": 1000}
    for i in range(100)
]
with patch("brain.indicators.get_ohlcv", return_value=[]):
    check("get_all_indicators empty data → {}",
          get_all_indicators("BTC_THB") == {})

with patch("brain.indicators.get_ohlcv", return_value=fake_candles):
    res = get_all_indicators("BTC_THB")
    check("get_all_indicators has full structure",
          res["symbol"] == "BTC_THB" and "signals" in res
          and set(res["signals"].keys()) == {"rsi", "bb", "macd", "ma"})
    check("uptrend → ma signal = buy", res["signals"]["ma"] == "buy")
    check("buy+sell count ≤ 4",
          res["buy_count"] + res["sell_count"] <= 4)


# ========== PORTFOLIO ==========
print("\n[PORTFOLIO]")
from execution.portfolio import Portfolio, LOG_FILE

with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    p = Portfolio()

    check("log file created",
          os.path.exists(LOG_FILE))
    check("trades starts empty", p.trades == [])
    check("open_trades starts empty", p.open_trades == {})

    p.record_buy("BTC_THB", price=1_000_000,
                 amount_thb=1000, fee=2.5, balance_after=9000)
    check("record_buy adds to open_trades",
          "BTC_THB" in p.open_trades)
    check("crypto calc = (1000-2.5)/1_000_000",
          p.open_trades["BTC_THB"]["amount_crypto"] == (1000 - 2.5) / 1_000_000)
    check("trades list has 1 entry", len(p.trades) == 1)
    check("buy trade has pnl=0", p.trades[0].pnl == 0.0)

    # edge: zero price
    p2 = Portfolio()
    p2.record_buy("ETH_THB", 0, 1000, 2.5, 9000)
    check("zero price doesn't div-by-zero",
          p2.open_trades["ETH_THB"]["amount_crypto"] == 0)

    # profitable sell
    p3 = Portfolio()
    p3.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
    crypto = p3.open_trades["BTC_THB"]["amount_crypto"]
    pnl = p3.record_sell("BTC_THB", 1_100_000, crypto, 2.75, 10000)
    check("profitable sell → pnl > 0", pnl > 0)
    check("pnl ≈ 94.5", abs(pnl - 94.5) < 0.1)
    check("sell removes from open_trades",
          "BTC_THB" not in p3.open_trades)

    # losing sell
    p4 = Portfolio()
    p4.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
    c = p4.open_trades["BTC_THB"]["amount_crypto"]
    pnl_loss = p4.record_sell("BTC_THB", 900_000, c, 2.25, 8000)
    check("losing sell → pnl < 0", pnl_loss < 0)

    # sell without buy
    p5 = Portfolio()
    pnl = p5.record_sell("BTC_THB", 1_100_000, 0.001, 2.75, 10000)
    check("sell without open trade → pnl=0", pnl == 0.0)

    # summary stats
    p6 = Portfolio()
    check("empty summary all zeros",
          p6.get_summary()["total_trades"] == 0
          and p6.get_summary()["win_rate"] == 0)

    # mixed trades
    p7 = Portfolio()
    p7.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
    c1 = p7.open_trades["BTC_THB"]["amount_crypto"]
    p7.record_sell("BTC_THB", 1_100_000, c1, 2.75, 10000)

    p7.record_buy("ETH_THB", 50_000, 1000, 2.5, 9000)
    c2 = p7.open_trades["ETH_THB"]["amount_crypto"]
    p7.record_sell("ETH_THB", 45_000, c2, 2.25, 8000)

    s = p7.get_summary()
    check("summary counts sells=2", s["total_sells"] == 2)
    check("summary wins=1 losses=1",
          s["wins"] == 1 and s["losses"] == 1)
    check("win_rate = 50%", s["win_rate"] == 50.0)
    check("best_trade > worst_trade",
          s["best_trade"] > s["worst_trade"])


# ========== Summary ==========
print(f"\n{'='*50}")
print(f"  ผลลัพธ์: {passed} ผ่าน / {failed} ล้มเหลว  (รวม {passed + failed})")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)
