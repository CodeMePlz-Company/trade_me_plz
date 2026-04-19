"""
tests/test_position_sizer.py — tests สำหรับ PositionSizer
ครอบคลุม fixed / kelly / atr / hybrid + fallback paths + clamping
"""
import pytest

from execution.position_sizer import PositionSizer, SizingResult


# ======================== Fixed ========================

class TestFixedMode:
    def test_returns_max_pct_of_balance(self):
        ps = PositionSizer(mode="fixed", max_position_pct=0.10)
        r = ps.size(10_000)
        assert r.size_thb == 1000.0
        assert r.mode_used == "fixed"

    def test_respects_higher_pct(self):
        ps = PositionSizer(mode="fixed", max_position_pct=0.25)
        assert ps.size(10_000).size_thb == 2500.0

    def test_zero_balance(self):
        ps = PositionSizer(mode="fixed")
        assert ps.size(0).size_thb == 0.0

    def test_below_minimum_floor(self):
        ps = PositionSizer(mode="fixed", max_position_pct=0.10,
                           min_position_thb=50.0)
        # 100 * 0.10 = 10 THB < 50 floor
        assert ps.size(100).size_thb == 0.0

    def test_exactly_at_minimum(self):
        ps = PositionSizer(mode="fixed", max_position_pct=0.01,
                           min_position_thb=20.0)
        # 2000 * 0.01 = 20 == floor → ผ่าน
        assert ps.size(2000).size_thb == 20.0


# ======================== Kelly ========================

class TestKellyMode:
    def test_fallback_when_few_trades(self):
        ps = PositionSizer(mode="kelly", kelly_min_trades=20)
        stats = {"total_sells": 5, "win_rate_pct": 60,
                 "avg_win": 100, "avg_loss": 50}
        r = ps.size(10_000, stats=stats)
        assert "fallback" in r.mode_used
        assert r.size_thb == 1000.0   # falls back to fixed 10%

    def test_fallback_when_no_stats(self):
        ps = PositionSizer(mode="kelly")
        r = ps.size(10_000, stats=None)
        assert "fallback" in r.mode_used

    def test_fallback_when_zero_stats(self):
        ps = PositionSizer(mode="kelly", kelly_min_trades=5)
        stats = {"total_sells": 10, "win_rate_pct": 0,
                 "avg_win": 0, "avg_loss": 0}
        r = ps.size(10_000, stats=stats)
        assert "fallback" in r.mode_used

    def test_kelly_formula_positive_edge(self):
        """p=0.6, b=2 → kelly = (0.6*2 − 0.4) / 2 = 0.4
           fractional * 0.25 = 0.10"""
        ps = PositionSizer(mode="kelly", kelly_fraction=0.25,
                           kelly_min_trades=5, max_position_pct=0.20)
        stats = {"total_sells": 20, "win_rate_pct": 60,
                 "avg_win": 200, "avg_loss": 100}
        r = ps.size(10_000, stats=stats)
        assert r.mode_used == "kelly"
        # raw kelly_frac = 0.4 × 0.25 = 0.10 → 1000 THB
        assert abs(r.size_thb - 1000.0) < 0.01
        assert r.kelly_frac is not None
        assert abs(r.kelly_frac - 0.10) < 0.01

    def test_kelly_clamped_at_ceiling(self):
        """Big edge → clamp ที่ max_position_pct"""
        ps = PositionSizer(mode="kelly", kelly_fraction=1.0,
                           kelly_min_trades=5, max_position_pct=0.05)
        stats = {"total_sells": 20, "win_rate_pct": 80,
                 "avg_win": 500, "avg_loss": 100}
        r = ps.size(10_000, stats=stats)
        assert r.size_thb <= 10_000 * 0.05 + 0.01

    def test_kelly_negative_edge_zero(self):
        """p=0.3, b=1 → negative kelly → 0 → below floor → 0 size"""
        ps = PositionSizer(mode="kelly", kelly_fraction=0.25,
                           kelly_min_trades=5)
        stats = {"total_sells": 20, "win_rate_pct": 30,
                 "avg_win": 100, "avg_loss": 100}
        r = ps.size(10_000, stats=stats)
        assert r.size_thb == 0.0


# ======================== ATR ========================

class TestATRMode:
    def test_fallback_when_no_atr(self):
        ps = PositionSizer(mode="atr")
        r = ps.size(10_000, price=100, atr=None)
        assert "fallback" in r.mode_used

    def test_fallback_when_zero_price(self):
        ps = PositionSizer(mode="atr")
        r = ps.size(10_000, price=0, atr=50)
        assert "fallback" in r.mode_used

    def test_fallback_when_zero_atr(self):
        ps = PositionSizer(mode="atr")
        r = ps.size(10_000, price=100, atr=0)
        assert "fallback" in r.mode_used

    def test_atr_formula(self):
        """
        risk_thb = 10_000 * 0.01 = 100
        stop_dist = 10_000 * 2 = 20_000
        crypto_units = 100 / 20_000 = 0.005
        raw_thb = 0.005 * 1_000_000 = 5000
        clamp at 10% of 10_000 = 1000 → size = 1000
        """
        ps = PositionSizer(mode="atr",
                           atr_risk_per_trade_pct=0.01,
                           atr_stop_multiplier=2.0,
                           max_position_pct=0.10)
        r = ps.size(10_000, price=1_000_000, atr=10_000)
        assert r.mode_used == "atr"
        assert r.size_thb == 1000.0      # clamped
        assert r.atr_value == 10_000.0

    def test_atr_volatile_gives_smaller_size(self):
        """ความผันผวนสูง → position เล็กลง"""
        ps = PositionSizer(mode="atr",
                           atr_risk_per_trade_pct=0.01,
                           atr_stop_multiplier=2.0,
                           max_position_pct=0.99)   # เปิดเพดานให้กว้าง
        low_vol  = ps.size(100_000, price=1_000_000, atr=5_000)
        high_vol = ps.size(100_000, price=1_000_000, atr=50_000)
        assert high_vol.size_thb < low_vol.size_thb


# ======================== Hybrid ========================

class TestHybridMode:
    def test_hybrid_chooses_minimum(self):
        ps = PositionSizer(mode="hybrid",
                           kelly_fraction=0.25,
                           kelly_min_trades=5,
                           max_position_pct=0.30)
        stats = {"total_sells": 20, "win_rate_pct": 70,
                 "avg_win": 200, "avg_loss": 100}
        r = ps.size(10_000, price=1_000_000, atr=10_000, stats=stats)
        assert "hybrid" in r.mode_used

    def test_hybrid_both_fallback_uses_fixed(self):
        ps = PositionSizer(mode="hybrid", kelly_min_trades=20)
        r = ps.size(10_000)   # no stats, no atr
        assert r.mode_used == "fixed"


# ======================== Clamp / Floor ========================

class TestClamping:
    def test_ceiling_never_exceeded(self):
        ps = PositionSizer(mode="kelly", kelly_fraction=10.0,
                           kelly_min_trades=5, max_position_pct=0.05)
        stats = {"total_sells": 20, "win_rate_pct": 99,
                 "avg_win": 1000, "avg_loss": 10}
        r = ps.size(10_000, stats=stats)
        assert r.size_thb <= 10_000 * 0.05 + 0.01

    def test_rounded_to_2dp(self):
        ps = PositionSizer(mode="fixed", max_position_pct=0.1333333)
        r = ps.size(10_000)
        # ควร round เป็น 2 ตำแหน่ง
        assert r.size_thb == round(r.size_thb, 2)


# ======================== Result shape ========================

def test_sizing_result_dataclass():
    ps = PositionSizer(mode="fixed")
    r = ps.size(10_000)
    assert isinstance(r, SizingResult)
    assert hasattr(r, "size_thb")
    assert hasattr(r, "mode_used")
    assert hasattr(r, "reason")
    assert hasattr(r, "kelly_frac")
    assert hasattr(r, "atr_value")
