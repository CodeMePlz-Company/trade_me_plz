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
                              calc_bollinger, calc_macd, calc_atr,
                              calc_stochastic, calc_adx, calc_volume_profile,
                              get_all_indicators)

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
          and set(res["signals"].keys())
              == {"rsi", "bb", "macd", "ma", "stoch", "adx", "vp"})
    check("uptrend → ma signal = buy", res["signals"]["ma"] == "buy")
    check("buy+sell count ≤ 7",
          res["buy_count"] + res["sell_count"] <= 7)
    check("result includes atr/stoch/adx/vp",
          "atr" in res and "stoch" in res and "adx" in res and "vp" in res)
    check("is_trending / is_sideways flags exist",
          "is_trending" in res and "is_sideways" in res)


# ---------- Stochastic ----------
print("\n[STOCHASTIC]")
# constant prices → %K = 50 (flat window)
h = [100] * 20; l = [100] * 20; c = [100] * 20
st = calc_stochastic(h, l, c, k_period=14, d_period=3)
check("stoch early indices = None",
      all(st[i]["k"] is None for i in range(13)))
check("stoch flat prices → K=50",
      st[-1]["k"] == 50.0)

# perfect uptrend → K ≈ 100
h = [100 + i for i in range(20)]
l = [99  + i for i in range(20)]
c = [100 + i for i in range(20)]
st = calc_stochastic(h, l, c, k_period=14, d_period=3)
check("stoch uptrend → K ≈ 100", st[-1]["k"] >= 90)
check("stoch has both K and D",
      st[-1]["k"] is not None and st[-1]["d"] is not None)

# perfect downtrend → K ≈ 0
h = [120 - i for i in range(20)]
l = [119 - i for i in range(20)]
c = [119 - i for i in range(20)]
st = calc_stochastic(h, l, c, k_period=14, d_period=3)
check("stoch downtrend → K ≤ 10", st[-1]["k"] <= 10)


# ---------- ADX ----------
print("\n[ADX]")
# uptrend → +DI > −DI; ADX rising
n = 60
h = [100 + i * 0.5 for i in range(n)]
l = [ 99 + i * 0.5 for i in range(n)]
c = [100 + i * 0.5 for i in range(n)]
a = calc_adx(h, l, c, period=14)
check("ADX early rows = None",
      all(a[i]["adx"] is None for i in range(14)))
last = a[-1]
check("ADX uptrend → +DI > −DI",
      last["plus_di"] is not None and last["minus_di"] is not None
      and last["plus_di"] > last["minus_di"])
check("ADX uptrend → adx is not None",
      last["adx"] is not None)

# downtrend → −DI > +DI
h = [150 - i * 0.5 for i in range(n)]
l = [149 - i * 0.5 for i in range(n)]
c = [149.5 - i * 0.5 for i in range(n)]
a = calc_adx(h, l, c, period=14)
last = a[-1]
check("ADX downtrend → −DI > +DI",
      last["minus_di"] > last["plus_di"])

# short data → all None
a = calc_adx([1, 2, 3], [1, 2, 3], [1, 2, 3], period=14)
check("ADX short data → all None",
      all(x["adx"] is None for x in a))


# ---------- Volume Profile ----------
print("\n[VOLUME PROFILE]")
h = [105, 103, 107, 110, 108]
l = [100, 98,  102, 105, 103]
v = [1000, 500, 1000, 100, 200]
vp = calc_volume_profile(h, l, v, num_bins=10)
check("VP returns poc/vah/val",
      "poc" in vp and "vah" in vp and "val" in vp)
check("VAL ≤ POC ≤ VAH",
      vp["val"] <= vp["poc"] <= vp["vah"])
check("VP bin count = 10", len(vp["bins"]) == 10)
check("VP bin_low = min(lows)",
      abs(vp["bin_low"] - 98) < 0.01)

# degenerate: empty or flat
check("VP empty input → {}",
      calc_volume_profile([], [], []) == {})
check("VP flat price → {}",
      calc_volume_profile([100] * 5, [100] * 5, [1] * 5) == {})


# ---------- ATR (quick sanity — extended earlier) ----------
print("\n[ATR]")
highs = [100 + i * 0.5 for i in range(30)]
lows  = [ 99 + i * 0.5 for i in range(30)]
closes = [ 99.5 + i * 0.5 for i in range(30)]
atr_vals = calc_atr(highs, lows, closes, period=14)
check("ATR first 14 = None",
      all(atr_vals[i] is None for i in range(14)))
check("ATR[14] is a float",
      isinstance(atr_vals[14], float) and atr_vals[14] > 0)
check("ATR positive at end", atr_vals[-1] > 0)


# ---------- PositionSizer ----------
print("\n[POSITION SIZER]")
from execution.position_sizer import PositionSizer

# fixed
ps = PositionSizer(mode="fixed", max_position_pct=0.1, min_position_thb=20.0)
r = ps.size(10_000)
check("fixed 10% of 10_000 = 1000",
      r.size_thb == 1000.0 and r.mode_used == "fixed")

# below min
r = ps.size(100)
check("fixed below min → 0",
      r.size_thb == 0.0)

# kelly with insufficient trades → fallback
ps_k = PositionSizer(mode="kelly", kelly_min_trades=20,
                     max_position_pct=0.1)
r = ps_k.size(10_000, stats={"total_sells": 5,
                             "win_rate_pct": 60,
                             "avg_win": 100, "avg_loss": 50})
check("kelly fallback when trades < min",
      "fallback" in r.mode_used)

# kelly with good stats
r = ps_k.size(10_000, stats={"total_sells": 50,
                             "win_rate_pct": 60,
                             "avg_win": 100, "avg_loss": 50})
check("kelly with good stats uses kelly mode",
      r.mode_used == "kelly" and r.kelly_frac is not None)
check("kelly never exceeds ceiling",
      r.size_thb <= 10_000 * 0.1 + 0.01)

# atr mode
ps_a = PositionSizer(mode="atr", atr_risk_per_trade_pct=0.01,
                     atr_stop_multiplier=2.0, max_position_pct=0.1)
r = ps_a.size(10_000, price=1_000_000, atr=10_000)
check("atr mode computes size",
      r.size_thb > 0 and r.mode_used == "atr")
check("atr respects ceiling",
      r.size_thb <= 10_000 * 0.1 + 0.01)

# atr no data → fallback
r = ps_a.size(10_000, price=0, atr=None)
check("atr fallback when no data",
      "fallback" in r.mode_used)


# ---------- Take-Profit / Trailing-Stop ----------
print("\n[TP / TRAILING]")
r = RiskManager(take_profit_pct=0.05, trailing_stop_pct=0.02,
                stop_loss_pct=0.03)
r.open_positions["BTC_THB"] = 1_000_000
r.highest_prices["BTC_THB"] = 1_000_000

check("TP triggers at +5%",
      r.should_take_profit("BTC_THB", 1_050_000) is True)
check("TP no trigger at +4%",
      r.should_take_profit("BTC_THB", 1_040_000) is False)

# trailing stop
r.update_peak("BTC_THB", 1_080_000)       # peak = 1.08M
check("trailing no trigger when peak close",
      r.should_trailing_stop("BTC_THB", 1_075_000) is False)
check("trailing triggers at >2% from peak",
      r.should_trailing_stop("BTC_THB", 1_055_000) is True)

# check_exit priority: TP beats trailing beats SL
r2 = RiskManager(take_profit_pct=0.05, trailing_stop_pct=0.02,
                 stop_loss_pct=0.03)
r2.open_positions["BTC_THB"] = 1_000_000
r2.highest_prices["BTC_THB"] = 1_000_000
dec = r2.check_exit("BTC_THB", 1_060_000)
check("check_exit → take-profit wins",
      dec.should_exit and dec.reason == "take-profit")

r3 = RiskManager(take_profit_pct=0.10, trailing_stop_pct=0.02,
                 stop_loss_pct=0.03)
r3.open_positions["BTC_THB"] = 1_000_000
r3.update_peak("BTC_THB", 1_080_000)
dec = r3.check_exit("BTC_THB", 1_050_000)   # not at TP (10%), but trailing
check("check_exit → trailing-stop wins over SL",
      dec.should_exit and dec.reason == "trailing-stop")

r4 = RiskManager(take_profit_pct=0.10, trailing_stop_pct=0.05,
                 stop_loss_pct=0.03)
r4.open_positions["BTC_THB"] = 1_000_000
r4.highest_prices["BTC_THB"] = 1_000_000
dec = r4.check_exit("BTC_THB", 960_000)     # −4% → SL
check("check_exit → stop-loss when no TP/trailing",
      dec.should_exit and dec.reason == "stop-loss")


# ---------- Multi-Timeframe ----------
print("\n[MULTI-TIMEFRAME]")
from brain.multi_timeframe import confirm as mtf_confirm

def _htf(consensus, buy=0, sell=0):
    return {"consensus": consensus, "buy_count": buy, "sell_count": sell,
            "adx": {"adx": 30, "plus_di": 25, "minus_di": 15}}

# hold → always allow
d = mtf_confirm("BTC_THB", "hold", _indicator_fn=lambda s, resolution: {})
check("MTF hold always allows", d.allow)

# missing data
d = mtf_confirm("BTC_THB", "buy", mode="strict",
                _indicator_fn=lambda s, resolution: {})
check("MTF strict rejects missing", not d.allow)

d = mtf_confirm("BTC_THB", "buy", mode="lenient",
                _indicator_fn=lambda s, resolution: {})
check("MTF lenient allows missing", d.allow)

# agree
d = mtf_confirm("BTC_THB", "buy",
                _indicator_fn=lambda s, resolution: _htf("buy", 5))
check("MTF buy confirmed by HTF buy", d.allow and d.confidence_delta > 0)

# oppose
d = mtf_confirm("BTC_THB", "buy", mode="lenient",
                _indicator_fn=lambda s, resolution: _htf("sell", 0, 5))
check("MTF buy blocked by HTF sell (lenient)",
      not d.allow and d.confidence_delta < 0)

d = mtf_confirm("BTC_THB", "sell",
                _indicator_fn=lambda s, resolution: _htf("buy", 5))
check("MTF sell blocked by HTF buy", not d.allow)

# neutral
d = mtf_confirm("BTC_THB", "buy", mode="strict",
                _indicator_fn=lambda s, resolution: _htf("neutral", 2, 2))
check("MTF neutral HTF blocks (strict)", not d.allow)

d = mtf_confirm("BTC_THB", "buy", mode="lenient",
                _indicator_fn=lambda s, resolution: _htf("neutral", 2, 2))
check("MTF neutral HTF passes (lenient) with delta=0",
      d.allow and d.confidence_delta == 0.0)

# custom boost/penalty
d = mtf_confirm("BTC_THB", "buy", boost=0.25,
                _indicator_fn=lambda s, resolution: _htf("buy", 5))
check("MTF custom boost = 0.25", d.confidence_delta == 0.25)

d = mtf_confirm("BTC_THB", "buy", penalty=0.40,
                _indicator_fn=lambda s, resolution: _htf("sell", 0, 5))
check("MTF custom penalty = −0.40", d.confidence_delta == -0.40)

# resolution passed through
captured = {}
def _spy(symbol, resolution):
    captured["r"] = resolution
    return _htf("buy", 5)
mtf_confirm("BTC_THB", "buy", higher_resolution="1D", _indicator_fn=_spy)
check("MTF passes higher_resolution to indicator_fn",
      captured.get("r") == "1D")


# ---------- Backtest engine wiring with sizer ----------
print("\n[BACKTEST + SIZER]")
from backtest.engine import BacktestEngine
from backtest.data_loader import generate_synthetic

candles = generate_synthetic(n_bars=200, regime="uptrend", seed=42)

# default (no sizer passed)
eng_default = BacktestEngine(starting_cash=100_000)
res_d = eng_default.run(candles, "BTC_THB")
check("backtest runs with default sizer",
      res_d.end_equity > 0 and hasattr(res_d, "trades"))

# explicit fixed sizer
from execution.position_sizer import PositionSizer
eng_fixed = BacktestEngine(starting_cash=100_000,
                           sizer=PositionSizer(mode="fixed",
                                               max_position_pct=0.1))
res_f = eng_fixed.run(candles, "BTC_THB")
check("backtest runs with fixed sizer",
      res_f.end_equity > 0)

# atr sizer
eng_atr = BacktestEngine(starting_cash=100_000,
                         sizer=PositionSizer(mode="atr",
                                             atr_risk_per_trade_pct=0.01,
                                             atr_stop_multiplier=2.0,
                                             max_position_pct=0.10))
res_a = eng_atr.run(candles, "BTC_THB")
check("backtest runs with atr sizer",
      res_a.end_equity > 0)

# hybrid sizer
eng_h = BacktestEngine(starting_cash=100_000,
                       sizer=PositionSizer(mode="hybrid",
                                           kelly_fraction=0.25,
                                           kelly_min_trades=5,
                                           max_position_pct=0.10))
res_h = eng_h.run(candles, "BTC_THB")
check("backtest runs with hybrid sizer",
      res_h.end_equity > 0)

# trade reason carries sizer info
if res_f.trades:
    buy_trades = [t for t in res_f.trades if t.action == "buy"]
    check("buy trade reason includes sz=fixed",
          bool(buy_trades) and "sz=" in buy_trades[0].reason)


# ---------- Strategy with MTF enabled ----------
print("\n[STRATEGY + MTF]")
from brain import strategy as strat_mod

# fake indicators for two resolutions
def _fake_indicators(symbol, resolution="60"):
    if resolution == "60":
        # lower TF signals buy
        return {
            "symbol": symbol, "price": 1_000_000,
            "signals": {"rsi": "buy", "bb": "buy", "macd": "buy",
                        "ma": "buy", "stoch": "buy",
                        "adx": "buy", "vp": "neutral"},
            "consensus": "buy", "buy_count": 6, "sell_count": 0,
            "is_trending": True, "is_sideways": False,
            "rsi": 25, "bb": {"upper": 1, "lower": 1, "mid": 1},
            "macd": {"macd": 0, "signal": 0}, "sma20": 1, "sma50": 1,
            "atr": 1000, "stoch": {"k": 15, "d": 20},
            "adx": {"adx": 40, "plus_di": 30, "minus_di": 10},
            "vp": None,
        }
    if resolution == "240":
        # higher TF agrees → buy
        return {"consensus": "buy", "buy_count": 4, "sell_count": 0,
                "adx": {"adx": 35, "plus_di": 30, "minus_di": 10}}
    return {}

# agree case
_orig = strat_mod.get_all_indicators
strat_mod.get_all_indicators = _fake_indicators
try:
    from brain.multi_timeframe import confirm as _c
    import brain.multi_timeframe as mtf_mod
    _orig_mtf = mtf_mod.get_all_indicators
    mtf_mod.get_all_indicators = _fake_indicators
    try:
        sig = strat_mod.strategy_indicator("BTC_THB", "60", mtf_enabled=True)
        check("strategy+MTF buy passes when HTF agrees",
              sig.action == "buy" and sig.confidence > 0)

        # HTF oppose case
        def _fake_oppose(symbol, resolution="60"):
            r = _fake_indicators(symbol, resolution)
            if resolution == "240":
                return {"consensus": "sell", "buy_count": 0, "sell_count": 4,
                        "adx": {"adx": 35, "plus_di": 10, "minus_di": 30}}
            return r
        strat_mod.get_all_indicators = _fake_oppose
        mtf_mod.get_all_indicators = _fake_oppose
        sig = strat_mod.strategy_indicator("BTC_THB", "60", mtf_enabled=True)
        check("strategy+MTF buy → hold when HTF opposes",
              sig.action == "hold" and "MTF-block" in sig.reason)
    finally:
        mtf_mod.get_all_indicators = _orig_mtf
finally:
    strat_mod.get_all_indicators = _orig


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

    # enhanced summary fields (SQLite era)
    check("summary has profit_factor", "profit_factor" in s)
    check("summary has expectancy",    "expectancy" in s)
    check("summary has avg_win/avg_loss",
          "avg_win" in s and "avg_loss" in s)
    check("summary has total_fees",    "total_fees" in s)
    check("summary has win_rate_pct alias",
          s["win_rate_pct"] == s["win_rate"])
    check("avg_win > 0",   s["avg_win"] > 0)
    check("avg_loss < 0",  s["avg_loss"] < 0)
    check("profit_factor > 0 for mixed", s["profit_factor"] > 0)


# ========== PORTFOLIO SQLITE ==========
print("\n[PORTFOLIO SQLITE]")
import sqlite3 as _sq
from execution.portfolio import Portfolio, DB_FILE

with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)

    # custom db_path isolation
    p = Portfolio(db_path="logs/test1.db", skip_migration=True)
    check("custom db_path file created",
          os.path.exists("logs/test1.db"))
    check("DB_FILE constant exists", DB_FILE == "logs/trades.db")

    # schema check
    with _sq.connect("logs/test1.db") as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(trades)")]
    check("DB has id column",          "id" in cols)
    check("DB has all 9 data columns", all(c in cols for c in [
        "timestamp", "symbol", "action", "price",
        "amount_thb", "amount_crypto", "fee", "pnl", "balance_after",
    ]))

    # insert via API → row in DB
    p.record_buy("BTC_THB", 1_000_000, 1000, 2.5, 9000)
    with _sq.connect("logs/test1.db") as con:
        cnt = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    check("record_buy writes to DB", cnt == 1)

    c = p.open_trades["BTC_THB"]["amount_crypto"]
    p.record_sell("BTC_THB", 1_100_000, c, 2.75, 10000)
    with _sq.connect("logs/test1.db") as con:
        cnt = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    check("record_sell writes to DB", cnt == 2)

    # get_trades() all
    all_trades = p.get_trades()
    check("get_trades() returns 2", len(all_trades) == 2)
    check("get_trades() returns dicts with columns",
          isinstance(all_trades[0], dict) and "pnl" in all_trades[0])

    # get_trades() filter by symbol
    btc = p.get_trades(symbol="BTC_THB")
    check("get_trades(symbol=) filters", len(btc) == 2)
    eth = p.get_trades(symbol="ETH_THB")
    check("get_trades(symbol= other) = 0", len(eth) == 0)

    # get_trades() filter by action
    buys  = p.get_trades(action="buy")
    sells = p.get_trades(action="sell")
    check("get_trades(action=buy)  = 1", len(buys) == 1)
    check("get_trades(action=sell) = 1", len(sells) == 1)

    # get_trades() limit
    p.record_buy("ETH_THB", 50_000, 1000, 2.5, 9000)
    c2 = p.open_trades["ETH_THB"]["amount_crypto"]
    p.record_sell("ETH_THB", 45_000, c2, 2.25, 8000)
    limited = p.get_trades(limit=2)
    check("get_trades(limit=2) respects limit", len(limited) == 2)

    # get_pnl_by_symbol()
    by_sym = p.get_pnl_by_symbol()
    check("get_pnl_by_symbol returns 2 rows", len(by_sym) == 2)
    syms = {r["symbol"] for r in by_sym}
    check("contains BTC + ETH", syms == {"BTC_THB", "ETH_THB"})
    btc_row = next(r for r in by_sym if r["symbol"] == "BTC_THB")
    check("BTC aggregate has pnl > 0", btc_row["total_pnl"] > 0)
    check("BTC aggregate sells=1",     btc_row["sells"] == 1)

    # get_all_time_summary()
    ats = p.get_all_time_summary()
    check("all_time_summary total_trades=4", ats["total_trades"] == 4)
    check("all_time_summary total_sells=2", ats["total_sells"]  == 2)
    check("all_time_summary wins=1",        ats["wins"]    == 1)
    check("all_time_summary losses=1",      ats["losses"]  == 1)
    check("all_time_summary win_rate=50",   ats["win_rate"] == 50.0)
    check("all_time_summary has profit_factor", "profit_factor" in ats)

    # persistence across Portfolio instances (same db_path)
    p_again = Portfolio(db_path="logs/test1.db", skip_migration=True)
    check("new instance sees empty self.trades",
          p_again.trades == [])
    loaded = p_again.load_from_db()
    check("load_from_db() restores 4 trades", loaded == 4)
    check("self.trades repopulated", len(p_again.trades) == 4)
    check("restored trades have pnl on sell",
          any(t.pnl != 0 for t in p_again.trades))

    # all-time summary should still show 4 for new instance
    ats2 = p_again.get_all_time_summary()
    check("persistence: all-time same across instances",
          ats2["total_trades"] == 4)

    # export_csv round-trip
    n_exported = p.export_csv("logs/export.csv")
    check("export_csv returns row count", n_exported == 4)
    check("export_csv creates file",
          os.path.exists("logs/export.csv"))
    import csv
    with open("logs/export.csv") as f:
        rows = list(csv.DictReader(f))
    check("exported CSV has 4 rows", len(rows) == 4)
    check("exported CSV has correct fields",
          set(rows[0].keys()) == {
              "timestamp", "symbol", "action", "price",
              "amount_thb", "amount_crypto", "fee", "pnl",
              "balance_after",
          })

    # DB isolation via db_path
    p_iso = Portfolio(db_path="logs/isolated.db", skip_migration=True)
    check("isolated DB has 0 trades",
          p_iso.get_all_time_summary()["total_trades"] == 0)
    check("original DB still has 4 trades",
          p.get_all_time_summary()["total_trades"] == 4)


# ========== PORTFOLIO CSV MIGRATION ==========
print("\n[PORTFOLIO CSV MIGRATION]")
import csv

with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    os.makedirs("logs", exist_ok=True)

    # write a legacy CSV
    legacy = [
        ["timestamp", "symbol", "action", "price",
         "amount_thb", "amount_crypto", "fee", "pnl", "balance_after"],
        ["2025-01-01T00:00:00", "BTC_THB", "buy",
         "1000000", "1000", "0.000997", "2.5", "0", "9000"],
        ["2025-01-02T00:00:00", "BTC_THB", "sell",
         "1100000", "1100", "0.000997", "2.75", "94.5", "10000"],
    ]
    with open("logs/trades.csv", "w", newline="") as f:
        w = csv.writer(f)
        for row in legacy:
            w.writerow(row)

    # fresh DB → should trigger migration
    p_mig = Portfolio(db_path="logs/trades.db")
    ats = p_mig.get_all_time_summary()
    check("CSV migration: 2 rows imported", ats["total_trades"] == 2)
    check("CSV migration: sells=1", ats["total_sells"] == 1)
    check("CSV migration: pnl captured",
          abs(ats["total_pnl"] - 94.5) < 0.1)

    # second construction should NOT re-migrate (DB already has rows)
    p_mig2 = Portfolio(db_path="logs/trades.db")
    check("no duplicate on re-construct",
          p_mig2.get_all_time_summary()["total_trades"] == 2)

    # skip_migration param
    with tempfile.TemporaryDirectory() as tmp2:
        os.chdir(tmp2)
        os.makedirs("logs", exist_ok=True)
        with open("logs/trades.csv", "w", newline="") as f:
            w = csv.writer(f)
            for row in legacy:
                w.writerow(row)
        p_skip = Portfolio(db_path="logs/skip.db", skip_migration=True)
        check("skip_migration=True bypasses import",
              p_skip.get_all_time_summary()["total_trades"] == 0)


# ========== Summary ==========
print(f"\n{'='*50}")
print(f"  ผลลัพธ์: {passed} ผ่าน / {failed} ล้มเหลว  (รวม {passed + failed})")
print("=" * 50)
sys.exit(0 if failed == 0 else 1)
