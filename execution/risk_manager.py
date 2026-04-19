from dataclasses import dataclass
from typing import Literal, Optional

from execution.position_sizer import PositionSizer, SizingResult

@dataclass
class RiskAssessment:
    approved:      bool
    reason:        str
    position_size: float   # จำนวน THB ที่อนุมัติให้ใช้
    sizing_info:   Optional[SizingResult] = None   # รายละเอียด sizing (สำหรับ log)


@dataclass
class ExitDecision:
    should_exit: bool
    reason:      str        # "take-profit" / "trailing-stop" / "stop-loss" / ""
    entry_price: float = 0.0
    peak_price:  float = 0.0


class RiskManager:
    """
    ควบคุมความเสี่ยงก่อนส่ง order ทุกครั้ง + จัดการ exit logic:

    Exit priority (เรียงจากสำคัญที่สุด):
        1. take-profit   — ล็อคกำไรถ้าราคาวิ่งถึง target
        2. trailing-stop — ล็อคกำไรที่เดินตามราคา peak
        3. stop-loss     — จำกัดขาดทุนแบบตายตัว
    """

    def __init__(self,
                 max_position_pct:  float = 0.10,
                 max_daily_loss:    float = 0.05,
                 stop_loss_pct:     float = 0.03,
                 take_profit_pct:   float = 0.05,
                 trailing_stop_pct: float = 0.02,
                 min_confidence:    float = 0.50,
                 sizer:             Optional[PositionSizer] = None):
        self.max_position_pct  = max_position_pct
        self.max_daily_loss    = max_daily_loss
        self.stop_loss_pct     = stop_loss_pct
        self.take_profit_pct   = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.min_confidence    = min_confidence

        # default sizer = fixed mode ด้วย max_position_pct เดียวกัน
        self.sizer = sizer or PositionSizer(
            mode             = "fixed",
            max_position_pct = max_position_pct,
        )

        self.daily_loss      = 0.0   # ขาดทุนสะสมวันนี้
        self.open_positions  = {}    # symbol → entry_price
        self.highest_prices  = {}    # symbol → highest price seen (สำหรับ trailing)

    # ========== Position sizing / stop-loss price ==========

    def calc_position_size(self, balance_thb: float,
                           price: float = 0,
                           atr: Optional[float] = None,
                           stats: Optional[dict] = None) -> float:
        """
        คำนวณขนาด position ผ่าน PositionSizer
        (backward-compat: ถ้าเรียกแบบเดิมด้วย arg เดียว → ใช้ fixed mode)
        """
        result = self.sizer.size(balance_thb, price=price, atr=atr, stats=stats)
        return result.size_thb

    def calc_stop_loss(self, entry_price: float,
                       side: Literal["buy", "sell"]) -> float:
        """คำนวณราคา stop-loss (ฝั่ง buy = ลงไป %, ฝั่ง sell = ขึ้นไป %)"""
        if side == "buy":
            return round(entry_price * (1 - self.stop_loss_pct), 2)
        else:
            return round(entry_price * (1 + self.stop_loss_pct), 2)

    def calc_take_profit(self, entry_price: float) -> float:
        """คำนวณราคา take-profit (buy-side)"""
        return round(entry_price * (1 + self.take_profit_pct), 2)

    # ========== Approval ==========

    def approve(self,
                symbol:        str,
                action:        Literal["buy", "sell"],
                confidence:    float,
                balance_thb:   float,
                current_price: float,
                atr:           Optional[float] = None,
                stats:         Optional[dict] = None) -> RiskAssessment:
        """
        ตรวจสอบว่าควรเทรดหรือไม่

        atr / stats เป็น optional — ส่งมาเพื่อให้ PositionSizer ใช้ได้
        เมื่อใช้ mode "atr"/"kelly"/"hybrid"
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

        # 4. คำนวณขนาด position ผ่าน PositionSizer (รองรับ fixed/kelly/atr/hybrid)
        sizing = self.sizer.size(balance_thb,
                                 price=current_price, atr=atr, stats=stats)
        if sizing.size_thb < 20:   # Bitkub minimum
            return RiskAssessment(False,
                f"position {sizing.size_thb:.2f} THB ต่ำกว่า minimum "
                f"(mode={sizing.mode_used})", 0,
                sizing_info=sizing)

        # ผ่านทุกเงื่อนไข — เปิด position ใหม่
        if action == "buy":
            self.open_positions[symbol]  = current_price
            self.highest_prices[symbol]  = current_price    # seed peak

        sl_price = self.calc_stop_loss(current_price, action)
        tp_price = self.calc_take_profit(current_price)
        return RiskAssessment(True,
            f"approved [{sizing.mode_used}] | SL={sl_price:,} TP={tp_price:,} "
            f"| {sizing.reason}",
            sizing.size_thb,
            sizing_info=sizing)

    # ========== Exit logic (TP / Trailing / SL) ==========

    def update_peak(self, symbol: str, current_price: float) -> None:
        """เรียกทุก tick — update peak price สำหรับ trailing stop"""
        if symbol not in self.open_positions:
            return
        prev = self.highest_prices.get(symbol, self.open_positions[symbol])
        if current_price > prev:
            self.highest_prices[symbol] = current_price

    def should_take_profit(self, symbol: str, current_price: float) -> bool:
        """ขาย TP เมื่อราคาถึง entry * (1 + take_profit_pct)"""
        entry = self.open_positions.get(symbol)
        if not entry or self.take_profit_pct <= 0:
            return False
        gain_pct = (current_price - entry) / entry
        return gain_pct >= self.take_profit_pct

    def should_trailing_stop(self, symbol: str, current_price: float) -> bool:
        """
        Trailing stop — ล็อคกำไรเมื่อราคาตกจาก peak เกิน trailing_pct
        เริ่มใช้งานเฉพาะเมื่อ peak > entry (ตำแหน่งเข้าทิศกำไรแล้ว)
        """
        if self.trailing_stop_pct <= 0:
            return False
        entry = self.open_positions.get(symbol)
        peak  = self.highest_prices.get(symbol)
        if not entry or not peak:
            return False
        if peak <= entry:                    # ยังไม่แตะกำไรจริง ๆ
            return False
        drop_from_peak = (peak - current_price) / peak
        return drop_from_peak >= self.trailing_stop_pct

    def should_stop_loss(self, symbol: str, current_price: float) -> bool:
        """Hard stop-loss จาก entry (behavior เดิม — เก็บไว้ backward compat)"""
        entry = self.open_positions.get(symbol)
        if not entry:
            return False
        loss_pct = (entry - current_price) / entry
        return loss_pct >= self.stop_loss_pct

    def check_exit(self, symbol: str,
                   current_price: float) -> ExitDecision:
        """
        จุดเดียวที่ควรเรียก — จะ update peak + เช็คทุกเงื่อนไขตามลำดับความสำคัญ
        Priority: take-profit > trailing-stop > stop-loss

        Returns ExitDecision(should_exit, reason, entry_price, peak_price)
        """
        if symbol not in self.open_positions:
            return ExitDecision(False, "")

        # update peak ก่อนเสมอ
        self.update_peak(symbol, current_price)

        entry = self.open_positions[symbol]
        peak  = self.highest_prices.get(symbol, entry)

        if self.should_take_profit(symbol, current_price):
            return ExitDecision(True, "take-profit", entry, peak)

        if self.should_trailing_stop(symbol, current_price):
            return ExitDecision(True, "trailing-stop", entry, peak)

        if self.should_stop_loss(symbol, current_price):
            return ExitDecision(True, "stop-loss", entry, peak)

        return ExitDecision(False, "", entry, peak)

    # ========== State mutations ==========

    def record_loss(self, loss_thb: float):
        """บันทึกขาดทุน — เรียกเมื่อปิด position ขาดทุน"""
        self.daily_loss += loss_thb

    def close_position(self, symbol: str):
        """ลบ open position + peak tracking เมื่อปิด order"""
        self.open_positions.pop(symbol, None)
        self.highest_prices.pop(symbol, None)

    def reset_daily(self):
        """รีเซ็ตทุกวัน — เรียกตอนเที่ยงคืน"""
        self.daily_loss = 0.0
        print("[RISK] reset daily loss counter")
