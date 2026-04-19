"""
Tests for brain/indicators.py

ครอบคลุม:
- calc_sma       — Simple Moving Average
- calc_ema       — Exponential Moving Average
- calc_rsi       — Relative Strength Index (มี edge cases)
- calc_bollinger — Bollinger Bands
- calc_macd      — MACD
- get_all_indicators — ใช้ mock เพราะต้องเรียก API

หมายเหตุ: ใช้ ค่า expected ที่คำนวณด้วยมือหรือ reference ที่รู้แน่ชัด
"""
import pytest
from unittest.mock import patch
from brain.indicators import (
    calc_sma, calc_ema, calc_rsi,
    calc_bollinger, calc_macd, get_all_indicators,
)


# ========== SMA ==========

class TestCalcSMA:
    def test_first_values_are_none_when_not_enough_data(self):
        result = calc_sma([1, 2, 3, 4, 5], period=3)
        assert result[:2] == [None, None]

    def test_sma_computes_correct_average(self):
        result = calc_sma([1, 2, 3, 4, 5], period=3)
        # index 2: avg(1,2,3) = 2
        # index 3: avg(2,3,4) = 3
        # index 4: avg(3,4,5) = 4
        assert result[2] == 2
        assert result[3] == 3
        assert result[4] == 4

    def test_sma_period_1_equals_input(self):
        result = calc_sma([10, 20, 30], period=1)
        assert result == [10, 20, 30]


# ========== EMA ==========

class TestCalcEMA:
    def test_first_value_equals_first_input(self):
        result = calc_ema([100, 110, 120], period=10)
        assert result[0] == 100

    def test_ema_weight_formula(self):
        # k = 2/(period+1) = 2/3 สำหรับ period=2
        # ema[1] = 110 * 2/3 + 100 * 1/3 = 73.33 + 33.33 = 106.66
        result = calc_ema([100, 110], period=2)
        assert result[1] == pytest.approx(106.666, rel=1e-3)

    def test_ema_follows_trend_up(self):
        result = calc_ema([10, 20, 30, 40, 50], period=3)
        # ค่าควรเพิ่มขึ้นเรื่อย ๆ
        for i in range(1, len(result)):
            assert result[i] > result[i - 1]


# ========== RSI ==========

class TestCalcRSI:
    def test_rsi_returns_none_for_first_period_values(self):
        closes = [float(i) for i in range(1, 20)]   # 19 values
        result = calc_rsi(closes, period=14)
        assert result[:14] == [None] * 14

    def test_rsi_all_gains_is_100(self):
        """เมื่อทุก bar ขึ้น (no loss) → RSI = 100"""
        closes = [float(i) for i in range(1, 20)]   # ขึ้นตลอด
        result = calc_rsi(closes, period=14)
        assert result[-1] == 100

    def test_rsi_returns_value_in_valid_range(self):
        # สลับ up-down
        closes = [100, 102, 101, 103, 102, 104, 103, 105, 104,
                  106, 105, 107, 106, 108, 107, 109, 108, 110]
        result = calc_rsi(closes, period=14)
        last = result[-1]
        assert 0 <= last <= 100

    def test_rsi_insufficient_data(self):
        """ข้อมูลน้อยกว่า period → คืน list ของ None"""
        result = calc_rsi([100, 101, 102], period=14)
        assert all(v is None for v in result)


# ========== Bollinger Bands ==========

class TestCalcBollinger:
    def test_early_values_are_none(self):
        closes = [100] * 10
        result = calc_bollinger(closes, period=20)
        assert result[0] == {"mid": None, "upper": None, "lower": None}

    def test_constant_prices_give_zero_width_bands(self):
        """ราคานิ่ง (std=0) → upper = lower = mid"""
        closes = [100] * 25
        result = calc_bollinger(closes, period=20)
        last = result[-1]
        assert last["mid"] == 100
        assert last["upper"] == 100
        assert last["lower"] == 100

    def test_upper_above_mid_above_lower(self):
        import random
        random.seed(42)
        closes = [100 + random.gauss(0, 5) for _ in range(30)]
        result = calc_bollinger(closes, period=20)
        last = result[-1]
        assert last["upper"] > last["mid"] > last["lower"]


# ========== MACD ==========

class TestCalcMACD:
    def test_macd_output_structure(self):
        closes = [float(i) for i in range(1, 50)]
        result = calc_macd(closes)
        last = result[-1]
        assert "macd" in last
        assert "signal" in last
        assert "histogram" in last

    def test_macd_equals_signal_plus_histogram(self):
        closes = [100 + i * 0.5 for i in range(50)]
        result = calc_macd(closes)
        for r in result:
            # macd = signal + histogram (ภายในขอบเขต round error)
            assert r["macd"] == pytest.approx(
                r["signal"] + r["histogram"], abs=0.01
            )

    def test_macd_length_matches_input(self):
        closes = [float(i) for i in range(1, 51)]
        result = calc_macd(closes)
        assert len(result) == len(closes)


# ========== get_all_indicators (mocked) ==========

class TestGetAllIndicators:
    def _fake_candles(self, n: int = 100) -> list[dict]:
        """สร้าง OHLCV ปลอมแบบ trending-up เล็กน้อย"""
        return [
            {"close": 100 + i * 0.5,
             "open": 100 + i * 0.5,
             "high": 101 + i * 0.5,
             "low":  99  + i * 0.5,
             "volume": 1000}
            for i in range(n)
        ]

    def test_returns_empty_dict_when_no_data(self):
        with patch("brain.indicators.get_ohlcv", return_value=[]):
            assert get_all_indicators("BTC_THB") == {}

    def test_returns_full_structure(self):
        candles = self._fake_candles(100)
        with patch("brain.indicators.get_ohlcv", return_value=candles):
            result = get_all_indicators("BTC_THB")

        assert result["symbol"] == "BTC_THB"
        assert "price" in result
        assert "signals" in result
        assert set(result["signals"].keys()) == {"rsi", "bb", "macd", "ma"}
        assert result["consensus"] in ("buy", "sell", "neutral")

    def test_uptrend_gives_bullish_ma_signal(self):
        """ราคาขึ้นต่อเนื่อง → SMA20 > SMA50 → ma = buy"""
        candles = self._fake_candles(100)
        with patch("brain.indicators.get_ohlcv", return_value=candles):
            result = get_all_indicators("BTC_THB")
        assert result["signals"]["ma"] == "buy"

    def test_buy_count_plus_sell_count_leq_4(self):
        candles = self._fake_candles(100)
        with patch("brain.indicators.get_ohlcv", return_value=candles):
            result = get_all_indicators("BTC_THB")
        assert result["buy_count"] + result["sell_count"] <= 4
