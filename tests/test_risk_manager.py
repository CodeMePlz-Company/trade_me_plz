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

    def test_close_also_clears_peak_tracking(self, risk):
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_100_000
        risk.close_position("BTC_THB")
        assert "BTC_THB" not in risk.highest_prices


# ========== Take Profit ==========

class TestTakeProfit:
    def test_triggers_at_exact_target(self, risk):
        # take_profit_pct default = 0.05 (5%)
        risk = RiskManager(take_profit_pct=0.05)
        risk.open_positions["BTC_THB"] = 1_000_000
        # ราคาขึ้น 5% พอดี → trigger
        assert risk.should_take_profit("BTC_THB", 1_050_000) is True

    def test_does_not_trigger_below_target(self, risk):
        risk = RiskManager(take_profit_pct=0.05)
        risk.open_positions["BTC_THB"] = 1_000_000
        # ขึ้น 4% < 5%
        assert risk.should_take_profit("BTC_THB", 1_040_000) is False

    def test_no_trigger_when_position_closed(self, risk):
        risk = RiskManager(take_profit_pct=0.05)
        assert risk.should_take_profit("BTC_THB", 1_500_000) is False

    def test_disabled_when_pct_is_zero(self):
        risk = RiskManager(take_profit_pct=0)
        risk.open_positions["BTC_THB"] = 1_000_000
        # ราคาขึ้น 50% — ถ้า disabled ต้องไม่ trigger
        assert risk.should_take_profit("BTC_THB", 1_500_000) is False


# ========== Trailing Stop ==========

class TestTrailingStop:
    def test_update_peak_tracks_highest(self):
        risk = RiskManager(trailing_stop_pct=0.02)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_000_000

        risk.update_peak("BTC_THB", 1_050_000)
        assert risk.highest_prices["BTC_THB"] == 1_050_000

        # ราคาต่ำกว่า peak — peak ไม่ควรลด
        risk.update_peak("BTC_THB", 1_020_000)
        assert risk.highest_prices["BTC_THB"] == 1_050_000

    def test_no_trigger_when_price_never_went_above_entry(self):
        """trailing stop ไม่ควรทำงานถ้าราคายังไม่เคยผ่าน entry"""
        risk = RiskManager(trailing_stop_pct=0.02)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_000_000    # peak == entry
        # ราคาตก 5% — ไม่ควร trigger trailing (ใช้ hard stop-loss แทน)
        assert risk.should_trailing_stop("BTC_THB", 950_000) is False

    def test_triggers_when_price_drops_from_peak(self):
        risk = RiskManager(trailing_stop_pct=0.02)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_100_000    # peak 10% กำไร

        # ราคาตกจาก peak 2.5% (> 2%)
        assert risk.should_trailing_stop("BTC_THB", 1_072_500) is True

    def test_does_not_trigger_when_drop_smaller_than_pct(self):
        risk = RiskManager(trailing_stop_pct=0.02)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_100_000

        # ตกจาก peak แค่ 1% < 2%
        assert risk.should_trailing_stop("BTC_THB", 1_089_000) is False

    def test_disabled_when_pct_is_zero(self):
        risk = RiskManager(trailing_stop_pct=0)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_100_000
        assert risk.should_trailing_stop("BTC_THB", 1_050_000) is False


# ========== check_exit (priority) ==========

class TestCheckExit:
    def test_no_open_position_returns_false(self):
        risk = RiskManager()
        decision = risk.check_exit("BTC_THB", 1_000_000)
        assert decision.should_exit is False
        assert decision.reason == ""

    def test_take_profit_has_highest_priority(self):
        """ถ้าราคาทั้ง TP ถึง + อยู่ในโซน trailing → ต้องเลือก TP ก่อน"""
        risk = RiskManager(take_profit_pct=0.05,
                           trailing_stop_pct=0.02, stop_loss_pct=0.03)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_200_000

        # ราคา 1,050,000 = +5% (TP hit) + ก็ยังตกจาก peak 12.5%
        decision = risk.check_exit("BTC_THB", 1_050_000)
        assert decision.should_exit is True
        assert decision.reason == "take-profit"

    def test_trailing_beats_stop_loss_when_both_apply(self):
        """ถ้า trailing + SL ทริกเกอร์พร้อมกัน เลือก trailing ก่อน"""
        risk = RiskManager(take_profit_pct=0.10,
                           trailing_stop_pct=0.02, stop_loss_pct=0.03)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_050_000   # peak +5%

        # ราคา 950,000: trailing = (1050-950)/1050 = 9.5% > 2%
        # SL       = (1000-950)/1000 = 5% > 3%
        decision = risk.check_exit("BTC_THB", 950_000)
        assert decision.should_exit is True
        assert decision.reason == "trailing-stop"

    def test_stop_loss_when_price_never_went_up(self):
        """ราคาไม่เคยขึ้นเลย → ใช้ stop-loss"""
        risk = RiskManager(take_profit_pct=0.05,
                           trailing_stop_pct=0.02, stop_loss_pct=0.03)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_000_000

        decision = risk.check_exit("BTC_THB", 965_000)   # -3.5%
        assert decision.should_exit is True
        assert decision.reason == "stop-loss"

    def test_no_exit_when_in_safe_zone(self):
        """ราคาลอยใน band ปลอดภัย → ไม่ออก"""
        risk = RiskManager(take_profit_pct=0.05,
                           trailing_stop_pct=0.02, stop_loss_pct=0.03)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_010_000

        decision = risk.check_exit("BTC_THB", 1_005_000)
        assert decision.should_exit is False

    def test_check_exit_updates_peak(self):
        """check_exit ต้อง update peak ให้ด้วย"""
        risk = RiskManager(trailing_stop_pct=0.02)
        risk.open_positions["BTC_THB"] = 1_000_000
        risk.highest_prices["BTC_THB"] = 1_000_000

        risk.check_exit("BTC_THB", 1_080_000)    # ควร update peak
        assert risk.highest_prices["BTC_THB"] == 1_080_000
