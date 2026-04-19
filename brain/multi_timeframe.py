"""
multi_timeframe.py — Multi-timeframe confirmation

กรอง entry signal ของ timeframe หลัก (เช่น 60 min)
ด้วย consensus จาก timeframe ใหญ่กว่า (เช่น 240 min)

หลักการ:
    - Intraday entry ที่สวนทิศ swing trend มักโดน whipsaw
    - Higher TF = ภาพรวมของ trend → ใช้เป็น "bias filter"
    - เข้า buy บน 1H ได้เมื่อ 4H ไม่ bearish
    - เข้า sell บน 1H ได้เมื่อ 4H ไม่ bullish

Modes:
    strict  — HTF ต้อง consensus ทิศเดียวกัน (buy/buy, sell/sell)
    lenient — HTF neutral ก็ผ่าน, ห้ามเฉพาะ HTF consensus ตรงข้าม
"""
from dataclasses import dataclass
from typing import Literal, Optional

from brain.indicators import get_all_indicators


@dataclass
class MTFDecision:
    """ผลลัพธ์จากการ confirm multi-timeframe"""
    allow:              bool
    confidence_delta:   float         # ± ที่จะบวกเข้า confidence เดิม
    reason:             str
    higher_tf:          str
    higher_consensus:   str           # buy / sell / neutral / missing
    higher_buy_count:   int = 0
    higher_sell_count:  int = 0
    higher_adx:         Optional[float] = None


def confirm(symbol:             str,
            lower_action:        Literal["buy", "sell", "hold"],
            higher_resolution:   str = "240",
            mode:                Literal["strict", "lenient"] = "lenient",
            boost:               float = 0.15,
            penalty:             float = 0.30,
            _indicator_fn=None) -> MTFDecision:
    """
    ตรวจสอบว่า signal ของ TF หลัก (lower_action) ได้รับ confirm จาก HTF ไหม

    Parameters:
        symbol            — คู่เหรียญ เช่น "BTC_THB"
        lower_action      — signal จาก TF หลัก: "buy" / "sell" / "hold"
        higher_resolution — TF ใหญ่ที่ใช้ confirm เช่น "240" (4H)
        mode              — strict: ต้อง agree | lenient: ห้าม oppose
        boost             — confidence delta เมื่อ HTF agree
        penalty           — confidence delta (ลบ) เมื่อ HTF ขัด
        _indicator_fn     — เผื่อใช้ inject mock ใน test

    Returns:
        MTFDecision(allow, confidence_delta, reason, ...)

    Rules:
        lower=hold        → allow=True  delta=0    (ไม่มีอะไรต้อง confirm)
        HTF ไม่มี data   → strict:reject / lenient:allow delta=0
        HTF agree         → allow=True  delta=+boost
        HTF neutral       → strict:reject / lenient:allow delta=0
        HTF oppose        → allow=False delta=-penalty  (ทั้ง 2 mode)
    """
    # ถ้า TF หลักไม่ signal อะไร — ไม่มีอะไรต้อง confirm
    if lower_action == "hold":
        return MTFDecision(True, 0.0,
            "no signal to confirm", higher_resolution, "neutral")

    # runtime lookup — อนุญาตให้ test patch module-level ได้
    fn = _indicator_fn if _indicator_fn is not None else get_all_indicators
    ind = fn(symbol, resolution=higher_resolution)
    if not ind or "consensus" not in ind:
        reason = "HTF data missing"
        if mode == "strict":
            return MTFDecision(False, -penalty, reason,
                higher_resolution, "missing")
        return MTFDecision(True, 0.0, reason,
            higher_resolution, "missing")

    htf_consensus = ind.get("consensus", "neutral")
    htf_adx       = None
    if ind.get("adx"):
        htf_adx = ind["adx"].get("adx")

    base = dict(
        higher_tf         = higher_resolution,
        higher_consensus  = htf_consensus,
        higher_buy_count  = ind.get("buy_count",  0),
        higher_sell_count = ind.get("sell_count", 0),
        higher_adx        = htf_adx,
    )

    # HTF ขัดทิศ → block ทั้ง strict + lenient
    if (lower_action == "buy"  and htf_consensus == "sell") or \
       (lower_action == "sell" and htf_consensus == "buy"):
        return MTFDecision(
            allow            = False,
            confidence_delta = -penalty,
            reason           = f"HTF({higher_resolution}) opposes: {htf_consensus}",
            **base,
        )

    # HTF agree ทิศเดียวกัน → boost
    if htf_consensus == lower_action:
        return MTFDecision(
            allow            = True,
            confidence_delta = +boost,
            reason           = f"HTF({higher_resolution}) confirms {htf_consensus}",
            **base,
        )

    # HTF neutral
    if mode == "strict":
        return MTFDecision(
            allow            = False,
            confidence_delta = -penalty,
            reason           = f"HTF({higher_resolution}) neutral (strict mode)",
            **base,
        )
    # lenient — ผ่านโดยไม่บวก/ลบ
    return MTFDecision(
        allow            = True,
        confidence_delta = 0.0,
        reason           = f"HTF({higher_resolution}) neutral (lenient pass)",
        **base,
    )
