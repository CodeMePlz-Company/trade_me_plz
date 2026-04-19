"""
position_sizer.py — Dynamic position sizing

4 โหมด:
    fixed  — % คงที่ของ balance (10% default) — ง่ายสุด
    kelly  — Kelly Criterion (ใช้ fractional Kelly เพื่อความปลอดภัย)
    atr    — Risk per trade × balance / (ATR × stop_multiplier)
             → เหรียญผันผวนสูง = position เล็กลงอัตโนมัติ
    hybrid — min(kelly, atr) — conservative ทั้งสองทาง

หลักการสำคัญ:
- ทุกโหมดถูก cap ที่ max_position_pct (กัน Kelly แนะนำเกิน)
- ทุกโหมดมี floor ที่ min_position_thb (กันขนาดเล็กไร้ประโยชน์ จน fee กิน)
- Kelly/ATR ถ้าข้อมูลไม่พอ → fallback เป็น fixed
"""
from dataclasses import dataclass
from typing import Literal, Optional

SizingMode = Literal["fixed", "kelly", "atr", "hybrid"]


@dataclass
class SizingResult:
    """ผลลัพธ์จาก PositionSizer — รวมเหตุผลให้ log ได้ด้วย"""
    size_thb:   float
    mode_used:  str              # อาจไม่ตรง mode ต้องหากถ้า fallback
    reason:     str = ""
    kelly_frac: Optional[float] = None
    atr_value:  Optional[float] = None


class PositionSizer:
    def __init__(self,
                 mode:             SizingMode = "fixed",
                 max_position_pct: float = 0.10,
                 min_position_thb: float = 20.0,
                 # Kelly params
                 kelly_fraction:   float = 0.25,   # 1/4 Kelly = conservative
                 kelly_min_trades: int   = 20,
                 # ATR params
                 atr_risk_per_trade_pct: float = 0.01,  # risk 1% ต่อ trade
                 atr_stop_multiplier:    float = 2.0):  # stop = entry - 2*ATR
        self.mode             = mode
        self.max_position_pct = max_position_pct
        self.min_position_thb = min_position_thb

        self.kelly_fraction   = kelly_fraction
        self.kelly_min_trades = kelly_min_trades

        self.atr_risk_per_trade_pct = atr_risk_per_trade_pct
        self.atr_stop_multiplier    = atr_stop_multiplier

    # ========== Public ==========

    def size(self,
             balance_thb: float,
             price:       float = 0,
             atr:         Optional[float] = None,
             stats:       Optional[dict] = None) -> SizingResult:
        """
        คำนวณขนาด position ที่เหมาะสม

        Parameters:
            balance_thb — cash available
            price       — ราคาปัจจุบัน (จำเป็นสำหรับ atr)
            atr         — ค่า ATR ล่าสุด (จำเป็นสำหรับ atr)
            stats       — portfolio summary dict (จำเป็นสำหรับ kelly)
                          ต้องมี: total_sells, win_rate_pct, avg_win, avg_loss
        """
        if self.mode == "kelly":
            return self._size_kelly(balance_thb, stats)
        if self.mode == "atr":
            return self._size_atr(balance_thb, price, atr)
        if self.mode == "hybrid":
            return self._size_hybrid(balance_thb, price, atr, stats)
        return self._size_fixed(balance_thb)

    # ========== Modes ==========

    def _size_fixed(self, balance_thb: float) -> SizingResult:
        raw = balance_thb * self.max_position_pct
        return SizingResult(
            size_thb  = self._clamp(raw, balance_thb),
            mode_used = "fixed",
            reason    = f"{self.max_position_pct:.0%} of balance",
        )

    def _size_kelly(self, balance_thb: float,
                    stats: Optional[dict]) -> SizingResult:
        if not stats or stats.get("total_sells", 0) < self.kelly_min_trades:
            result = self._size_fixed(balance_thb)
            result.mode_used = "fixed (kelly fallback: not enough trades)"
            return result

        p = stats["win_rate_pct"] / 100.0
        avg_win  = abs(stats["avg_win"])
        avg_loss = abs(stats["avg_loss"])

        if p <= 0 or avg_loss <= 0 or avg_win <= 0:
            result = self._size_fixed(balance_thb)
            result.mode_used = "fixed (kelly fallback: zero stats)"
            return result

        # Kelly formula: f = (p*b - q) / b  where b = win/loss ratio
        b = avg_win / avg_loss
        q = 1 - p
        kelly_frac = (p * b - q) / b

        # Fractional Kelly + กันค่าลบ
        kelly_frac = max(0.0, kelly_frac) * self.kelly_fraction

        raw = balance_thb * kelly_frac
        return SizingResult(
            size_thb   = self._clamp(raw, balance_thb),
            mode_used  = "kelly",
            reason     = f"p={p:.2f} b={b:.2f} frac={kelly_frac:.3f}",
            kelly_frac = round(kelly_frac, 4),
        )

    def _size_atr(self, balance_thb: float,
                  price: float, atr: Optional[float]) -> SizingResult:
        if not atr or not price or atr <= 0:
            result = self._size_fixed(balance_thb)
            result.mode_used = "fixed (atr fallback: no ATR)"
            return result

        # ความเสี่ยงต่อ trade เป็น THB
        risk_thb      = balance_thb * self.atr_risk_per_trade_pct
        # ระยะจาก entry ถึง stop (ในหน่วยราคา)
        stop_distance = atr * self.atr_stop_multiplier

        # ถ้าโดน stop → เสีย (crypto_units × stop_distance) THB = risk_thb
        crypto_units = risk_thb / stop_distance
        raw_thb      = crypto_units * price

        return SizingResult(
            size_thb  = self._clamp(raw_thb, balance_thb),
            mode_used = "atr",
            reason    = (f"risk={risk_thb:.0f} stop={stop_distance:.0f} "
                         f"units={crypto_units:.8f}"),
            atr_value = round(atr, 4),
        )

    def _size_hybrid(self, balance_thb: float, price: float,
                     atr: Optional[float],
                     stats: Optional[dict]) -> SizingResult:
        """เลือกค่าที่น้อยกว่าระหว่าง kelly และ atr — เซฟที่สุด"""
        k = self._size_kelly(balance_thb, stats)
        a = self._size_atr(balance_thb, price, atr)

        # ถ้าทั้งสอง fallback เป็น fixed → ใช้ fixed
        if "fallback" in k.mode_used and "fallback" in a.mode_used:
            return self._size_fixed(balance_thb)

        chosen = k if k.size_thb <= a.size_thb else a
        return SizingResult(
            size_thb   = chosen.size_thb,
            mode_used  = f"hybrid ({'kelly' if chosen is k else 'atr'})",
            reason     = f"kelly={k.size_thb:.0f} atr={a.size_thb:.0f}",
            kelly_frac = k.kelly_frac,
            atr_value  = a.atr_value,
        )

    # ========== Helpers ==========

    def _clamp(self, raw_thb: float, balance_thb: float) -> float:
        """ใส่ ceiling ที่ max_position_pct และ floor ที่ min_position_thb"""
        ceiling = balance_thb * self.max_position_pct
        clamped = min(raw_thb, ceiling)

        # ถ้าต่ำกว่า min → คืน 0 (ไม่พอจะเทรด)
        if clamped < self.min_position_thb:
            return 0.0
        return round(clamped, 2)
