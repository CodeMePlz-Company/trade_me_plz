from dataclasses import dataclass
from typing import Literal

@dataclass
class RiskAssessment:
    approved:     bool
    reason:       str
    position_size: float  # จำนวน THB ที่อนุมัติให้ใช้

class RiskManager:
    """
    ควบคุมความเสี่ยงก่อนส่ง order ทุกครั้ง
    """

    def __init__(self,
                 max_position_pct: float = 0.10,   # ใช้เงินไม่เกิน 10% ต่อ order
                 max_daily_loss:   float = 0.05,   # ขาดทุนไม่เกิน 5% ต่อวัน
                 stop_loss_pct:    float = 0.03,   # stop-loss 3%
                 min_confidence:   float = 0.50):  # confidence ต่ำสุดที่ยอมรับ
        self.max_position_pct = max_position_pct
        self.max_daily_loss   = max_daily_loss
        self.stop_loss_pct    = stop_loss_pct
        self.min_confidence   = min_confidence

        self.daily_loss       = 0.0   # ขาดทุนสะสมวันนี้
        self.open_positions   = {}    # symbol → entry_price

    def calc_position_size(self, balance_thb: float) -> float:
        """คำนวณขนาด position ที่เหมาะสม"""
        return round(balance_thb * self.max_position_pct, 2)

    def calc_stop_loss(self, entry_price: float,
                       side: Literal["buy", "sell"]) -> float:
        """คำนวณราคา stop-loss"""
        if side == "buy":
            return round(entry_price * (1 - self.stop_loss_pct), 2)
        else:
            return round(entry_price * (1 + self.stop_loss_pct), 2)

    def approve(self,
                symbol:     str,
                action:     Literal["buy", "sell"],
                confidence: float,
                balance_thb: float,
                current_price: float) -> RiskAssessment:
        """
        ตรวจสอบว่าควรเทรดหรือไม่
        คืนค่า RiskAssessment พร้อมเหตุผล
        """
        # 1. confidence ต่ำเกินไป
        if confidence < self.min_confidence:
            return RiskAssessment(False,
                f"confidence {confidence} < minimum {self.min_confidence}", 0)

        # 2. ขาดทุนวันนี้เกิน limit
        daily_loss_pct = self.daily_loss / max(balance_thb, 1)
        if daily_loss_pct >= self.max_daily_loss:
            return RiskAssessment(False,
                f"daily loss {daily_loss_pct:.1%} เกิน limit {self.max_daily_loss:.1%}", 0)

        # 3. ถือ position นี้อยู่แล้ว
        if action == "buy" and symbol in self.open_positions:
            return RiskAssessment(False,
                f"มี open position ของ {symbol} อยู่แล้ว", 0)

        # 4. balance น้อยเกินไป
        position_size = self.calc_position_size(balance_thb)
        if position_size < 20:
            return RiskAssessment(False,
                f"balance {balance_thb:.2f} THB น้อยเกินไป", 0)

        # ผ่านทุกเงื่อนไข
        if action == "buy":
            self.open_positions[symbol] = current_price

        stop_price = self.calc_stop_loss(current_price, action)
        return RiskAssessment(True,
            f"approved | stop-loss @ {stop_price:,}", position_size)

    def record_loss(self, loss_thb: float):
        """บันทึกขาดทุน — เรียกเมื่อปิด position ขาดทุน"""
        self.daily_loss += loss_thb

    def close_position(self, symbol: str):
        """ลบ open position เมื่อปิด order"""
        self.open_positions.pop(symbol, None)

    def should_stop_loss(self, symbol: str, current_price: float) -> bool:
        """ตรวจว่าถึงราคา stop-loss แล้วหรือยัง"""
        entry = self.open_positions.get(symbol)
        if not entry:
            return False
        loss_pct = (entry - current_price) / entry
        return loss_pct >= self.stop_loss_pct

    def reset_daily(self):
        """รีเซ็ตทุกวัน — เรียกตอนเที่ยงคืน"""
        self.daily_loss = 0.0
        print("[RISK] reset daily loss counter")