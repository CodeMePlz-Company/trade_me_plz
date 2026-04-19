"""
Tests for execution/risk_manager.py

ครอบคลุม:
- calc_position_size  — ขนาด position ถูกต้องตาม %
- calc_stop_loss      — ราคา stop-loss ทั้งฝั่ง buy/sell
- approve             — ทุก ๆ เงื่อนไข reject + path ที่อนุมัติ
- should_stop_loss    — trigger เมื่อราคาตกเกิน threshold
- record_loss         — สะสม daily_loss ถูก
- close_position      — ลบ open_positions
- reset_daily         — reset daily_loss
"""
import pytest
from execution.risk_manager import RiskManager, RiskAssessment


@pytest.fixture
def risk():
    """Fresh RiskManager กับ default config ของระบบ"""
    return RiskManager(
        max_position_pct = 0.10,
        max_daily_loss   = 0.05,
        stop_loss_pct    = 0.03,
        min_confidence   = 0.50,
    )


# ========== calc_position_size ==========

class TestCalcPositionSize:
    def test_size_is_10_percent_of_balance(self, risk):
        assert risk.calc_position_size(10_000) == 1_000.0

    def test_size_rounds_to_2_decimals(self, risk):
        # 1234.567 * 0.10 = 123.4567 → 123.46
        assert risk.calc_position_size(1234.567) == 123.46

    def test_zero_balance_gives_zero(self, risk):
        assert risk.calc_position_size(0) == 0.0


# ========== calc_stop_loss ==========

class TestCalcStopLoss:
    def test_buy_stop_loss_is_below_entry(self, risk):
        # entry 1000, stop_loss 3% → 970
        assert risk.calc_stop_loss(1000, "buy") == 970.0

    def test_sell_stop_loss_is_above_entry(self, risk):
        # entry 1000, stop_loss 3% → 1030
        assert risk.calc_stop_loss(1000, "sell") == 1030.0

    def test_stop_loss_rounded_to_2_decimals(self, risk):
        result = risk.calc_stop_loss(1234.567, "buy")
        assert result == round(1234.567 * 0.97, 2)


# ========== approve ==========

class TestApprove:
    def test_reject_low_confidence(self, risk):
        result = risk.approve(
            symbol="BTC_THB", action="buy",
            confidence=0.3,        # < min_confidence 0.5
            balance_thb=10_000, current_price=1_000_000,
        )
        assert result.approved is False
        assert "confidence" in result.reason
        assert result.position_size == 0

    def test_reject_when_daily_loss_exceeded(self, risk):
        # จำลองว่าขาดทุนวันนี้ไปแล้ว 600 THB จาก 10,000 = 6% > 5%
        risk.daily_loss = 600
        result = risk.approve(
            symbol="BTC_THB", action="buy",
            confidence=0.9,
            balance_thb=10_000, current_price=1_000_000,
        )
        assert result.approved is False
        assert "daily loss" in result.reason

    def test_reject_when_position_already_open(self, risk):
        # เปิด position BTC_THB ไว้ก่อน
        risk.open_positions["BTC_THB"] = 1_000_000

        result = risk.approve(
            symbol="BTC_THB", action="buy",
            confidence=0.9,
            balance_thb=10_000, current_price=1_100_000,
        )
        assert result.approved is False
        assert "BTC_THB" in result.reason

    def test_reject_when_balance_too_small(self, risk):
        # balance 100 → 10% = 10 THB < 20 THB minimum
        result = risk.approve(
            symbol="BTC_THB", action="buy",
            confidence=0.9,
            balance_thb=100, current_price=1_000_000,
        )
        assert result.approved is False
        assert "น้อยเกินไป" in result.reason

    def test_approve_happy_path(self, risk):
        result = risk.approve(
            symbol="BTC_THB", action="buy",
            confidence=0.8,
            balance_thb=10_000, current_price=1_000_000,
        )
        assert result.approved is True
        assert result.position_size == 1_000.0      # 10% ของ 10,000
        assert "BTC_THB" in risk.open_positions     # บันทึกเป็น open position
        assert risk.open_positions["BTC_THB"] == 1_000_000

    def test_approve_at_exactly_min_confidence(self, risk):
        """confidence = min_confidence ควรอนุมัติได้ (ไม่ใช่ <)"""
        result = risk.approve(
            symbol="BTC_THB", action="buy",
            confidence=0.50,
            balance_thb=10_000, current_price=1_000_000,
        )
        assert result.approved is True


# ========== should_stop_loss ==========

class TestShouldStopLoss:
    def test_triggers_when_loss_exceeds_threshold(self, risk):
        risk.open_positions["BTC_THB"] = 1_000_000
        # ราคาตก 4% (> 3% threshold)
        assert risk.should_stop_loss("BTC_THB", 960_000) is True

    def test_does_not_trigger_below_threshold(self, risk):
        risk.open_positions["BTC_THB"] = 1_000_000
        # ราคาตกแค่ 2% (< 3% threshold)
        assert risk.should_stop_loss("BTC_THB", 980_000) is False

    def test_triggers_at_exact_threshold(self, risk):
        risk.open_positions["BTC_THB"] = 1_000_000
        # ลง 3% พอดี → >= threshold → trigger
        assert risk.should_stop_loss("BTC_THB", 970_000) is True

    def test_no_trigger_when_position_not_open(self, risk):
        assert risk.should_stop_loss("BTC_THB", 500_000) is False

    def test_no_trigger_when_price_goes_up(self, risk):
        risk.open_positions["BTC_THB"] = 1_000_000
        assert risk.should_stop_loss("BTC_THB", 1_100_000) is False


# ========== record_loss / reset_daily ==========

class TestDailyLossTracking:
    def test_record_loss_accumulates(self, risk):
        risk.record_loss(100)
        risk.record_loss(50)
        assert risk.daily_loss == 150

    def test_reset_daily_zeros_loss(self, risk):
        risk.daily_loss = 500
        risk.reset_daily()
        assert risk.daily_loss == 0.0


# ========== close_position ==========

class TestClosePosition:
    def test_close_removes_from_open_positions(self, risk):
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.close_position("BTC_THB")
        assert "BTC_THB" not in risk.open_positions

    def test_close_nonexistent_position_is_safe(self, risk):
        # ต้องไม่ throw exception
        risk.close_position("DOGE_THB")
        assert risk.open_positions == {}
