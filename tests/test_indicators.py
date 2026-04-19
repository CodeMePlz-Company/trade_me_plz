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
    calc_bollinger, calc_macd, calc_atr,
    calc_stochastic, calc_adx, calc_volume_profile,
    get_all_indicators,
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
        assert set(result["signals"].keys()) == {
            "rsi", "bb", "macd", "ma", "stoch", "adx", "vp"
        }
        assert result["consensus"] in ("buy", "sell", "neutral")

    def test_uptrend_gives_bullish_ma_signal(self):
        """ราคาขึ้นต่อเนื่อง → SMA20 > SMA50 → ma = buy"""
        candles = self._fake_candles(100)
        with patch("brain.indicators.get_ohlcv", return_value=candles):
            result = get_all_indicators("BTC_THB")
        assert result["signals"]["ma"] == "buy"

    def test_buy_count_plus_sell_count_leq_7(self):
        candles = self._fake_candles(100)
        with patch("brain.indicators.get_ohlcv", return_value=candles):
            result = get_all_indicators("BTC_THB")
        assert result["buy_count"] + result["sell_count"] <= 7

    def test_includes_extended_indicators(self):
        candles = self._fake_candles(100)
        with patch("brain.indicators.get_ohlcv", return_value=candles):
            result = get_all_indicators("BTC_THB")
        for key in ("atr", "stoch", "adx", "vp",
                    "is_trending", "is_sideways"):
            assert key in result


# ========== ATR ==========

class TestCalcATR:
    def test_first_period_values_are_none(self):
        n = 30
        highs = [100 + i for i in range(n)]
        lows  = [ 99 + i for i in range(n)]
        closes = [ 99.5 + i for i in range(n)]
        atr = calc_atr(highs, lows, closes, period=14)
        assert all(v is None for v in atr[:14])
        assert atr[14] is not None

    def test_returns_positive_atr(self):
        n = 30
        highs = [100 + i for i in range(n)]
        lows  = [ 99 + i for i in range(n)]
        closes = [ 99.5 + i for i in range(n)]
        atr = calc_atr(highs, lows, closes, period=14)
        assert atr[-1] > 0

    def test_insufficient_data_all_none(self):
        atr = calc_atr([1, 2], [1, 2], [1, 2], period=14)
        assert all(v is None for v in atr)

    def test_mismatched_lengths_all_none(self):
        atr = calc_atr([1, 2, 3], [1, 2], [1, 2, 3], period=14)
        assert all(v is None for v in atr)

    def test_higher_volatility_higher_atr(self):
        n = 30
        lowvol_h  = [100 + i * 0.1 for i in range(n)]
        lowvol_l  = [ 99.9 + i * 0.1 for i in range(n)]
        lowvol_c  = [100 + i * 0.1 for i in range(n)]
        highvol_h = [100 + i * 2 + (i % 2) * 5 for i in range(n)]
        highvol_l = [ 95 + i * 2 - (i % 2) * 5 for i in range(n)]
        highvol_c = [ 98 + i * 2             for i in range(n)]

        a_low  = calc_atr(lowvol_h,  lowvol_l,  lowvol_c,  period=14)
        a_high = calc_atr(highvol_h, highvol_l, highvol_c, period=14)
        assert a_high[-1] > a_low[-1]


# ========== Stochastic ==========

class TestCalcStochastic:
    def test_flat_prices_k_equals_50(self):
        h = [100] * 20; l = [100] * 20; c = [100] * 20
        result = calc_stochastic(h, l, c, k_period=14, d_period=3)
        assert result[-1]["k"] == 50.0

    def test_uptrend_k_near_100(self):
        h = [100 + i for i in range(20)]
        l = [ 99 + i for i in range(20)]
        c = [100 + i for i in range(20)]
        result = calc_stochastic(h, l, c, k_period=14, d_period=3)
        assert result[-1]["k"] >= 90

    def test_downtrend_k_near_0(self):
        h = [120 - i for i in range(20)]
        l = [119 - i for i in range(20)]
        c = [119 - i for i in range(20)]
        result = calc_stochastic(h, l, c, k_period=14, d_period=3)
        assert result[-1]["k"] <= 10

    def test_early_values_are_none(self):
        h = [100 + i for i in range(20)]
        l = [ 99 + i for i in range(20)]
        c = [100 + i for i in range(20)]
        result = calc_stochastic(h, l, c, k_period=14, d_period=3)
        assert all(result[i]["k"] is None for i in range(13))

    def test_has_both_k_and_d(self):
        h = [100 + i for i in range(20)]
        l = [ 99 + i for i in range(20)]
        c = [100 + i for i in range(20)]
        result = calc_stochastic(h, l, c, k_period=14, d_period=3)
        assert result[-1]["k"] is not None
        assert result[-1]["d"] is not None


# ========== ADX ==========

class TestCalcADX:
    def test_early_rows_all_none(self):
        n = 60
        h = [100 + i * 0.5 for i in range(n)]
        l = [ 99 + i * 0.5 for i in range(n)]
        c = [100 + i * 0.5 for i in range(n)]
        result = calc_adx(h, l, c, period=14)
        assert all(result[i]["adx"] is None for i in range(14))

    def test_uptrend_plus_di_higher(self):
        n = 60
        h = [100 + i * 0.5 for i in range(n)]
        l = [ 99 + i * 0.5 for i in range(n)]
        c = [100 + i * 0.5 for i in range(n)]
        result = calc_adx(h, l, c, period=14)
        assert result[-1]["plus_di"] > result[-1]["minus_di"]

    def test_downtrend_minus_di_higher(self):
        n = 60
        h = [150 - i * 0.5 for i in range(n)]
        l = [149 - i * 0.5 for i in range(n)]
        c = [149.5 - i * 0.5 for i in range(n)]
        result = calc_adx(h, l, c, period=14)
        assert result[-1]["minus_di"] > result[-1]["plus_di"]

    def test_short_data_all_none(self):
        result = calc_adx([1, 2, 3], [1, 2, 3], [1, 2, 3], period=14)
        assert all(r["adx"] is None for r in result)

    def test_trend_has_adx_value(self):
        n = 60
        h = [100 + i * 0.5 for i in range(n)]
        l = [ 99 + i * 0.5 for i in range(n)]
        c = [100 + i * 0.5 for i in range(n)]
        result = calc_adx(h, l, c, period=14)
        assert result[-1]["adx"] is not None


# ========== Volume Profile ==========

class TestCalcVolumeProfile:
    def test_returns_poc_vah_val(self):
        h = [105, 103, 107, 110, 108]
        l = [100,  98, 102, 105, 103]
        v = [1000, 500, 1000, 100, 200]
        result = calc_volume_profile(h, l, v, num_bins=10)
        assert "poc" in result
        assert "vah" in result
        assert "val" in result

    def test_val_le_poc_le_vah(self):
        h = [105, 103, 107, 110, 108]
        l = [100,  98, 102, 105, 103]
        v = [1000, 500, 1000, 100, 200]
        result = calc_volume_profile(h, l, v, num_bins=10)
        assert result["val"] <= result["poc"] <= result["vah"]

    def test_empty_returns_empty_dict(self):
        assert calc_volume_profile([], [], []) == {}

    def test_flat_price_returns_empty(self):
        """ราคาแบนทั้งหมด → bin_size = 0 → {}"""
        assert calc_volume_profile([100] * 5, [100] * 5, [1] * 5) == {}

    def test_bin_count_matches_arg(self):
        h = [110, 115, 120]
        l = [100, 105, 110]
        v = [50, 60, 70]
        result = calc_volume_profile(h, l, v, num_bins=5)
        assert len(result["bins"]) == 5

    def test_bin_low_equals_min_low(self):
        h = [110, 115]; l = [100, 105]; v = [50, 60]
        result = calc_volume_profile(h, l, v, num_bins=5)
        assert abs(result["bin_low"] - 100) < 0.01

    def test_mismatched_lengths_returns_empty(self):
        assert calc_volume_profile([1, 2], [1], [1, 2]) == {}
