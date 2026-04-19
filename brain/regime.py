"""
regime.py — Market Regime Detection

แยกตลาดออกเป็น 5 regimes ตามสัญญาณจาก ADX + ATR + BB width:

    trending_bull  — ADX > 25 และ +DI > −DI  (tren ขาขึ้นชัด)
    trending_bear  — ADX > 25 และ −DI > +DI  (trend ขาลงชัด)
    ranging        — ADX < 20 และ ความผันผวนปกติ (BB squeeze-ish)
    volatile       — ATR/price สูงกว่า threshold (อันตราย — ลดขนาด)
    mixed          — ADX 20–25 หรือ ambiguous (รอ confirmation)

จากนั้นแนะนำ strategy + ปัจจัยลด position size (position_scale):

    regime         strategy           scale
    trending_bull  trend-following    1.0
    trending_bear  avoid-longs        0.0    (bot long-only → ไม่เข้า)
    ranging        mean-reversion     0.8    (BB/VP bounce play)
    volatile       reduce             0.5
    mixed          wait               0.7

ออกแบบให้:
- ใช้ indicators dict ที่ get_all_indicators() คืนมา (ไม่ต้อง re-fetch)
- แยก pure detect function จาก symbol-level wrapper เพื่อให้ test ได้ง่าย
"""
from dataclasses import dataclass
from typing import Literal, Optional

from brain.indicators import get_all_indicators


Regime = Literal[
    "trending_bull", "trending_bear",
    "ranging", "volatile", "mixed",
]

# ---- mapping regime → strategy + position scale ----
_STRATEGY_MAP = {
    "trending_bull": ("trend-following", 1.0),
    "trending_bear": ("avoid-longs",    0.0),
    "ranging":       ("mean-reversion", 0.8),
    "volatile":      ("reduce",         0.5),
    "mixed":         ("wait",           0.7),
}


@dataclass
class RegimeInfo:
    """ผลลัพธ์ของการตรวจ regime"""
    regime:               Regime
    confidence:           float          # 0.0–1.0 — ความมั่นใจใน classification
    adx:                  Optional[float]
    plus_di:              Optional[float]
    minus_di:             Optional[float]
    atr_pct:              Optional[float]   # ATR as % ของ price ล่าสุด
    bb_width_pct:         Optional[float]   # (upper−lower)/mid × 100
    reason:               str
    recommended_strategy: str               # "trend-following" / "mean-reversion" / ...
    position_scale:       float             # 0.0–1.0 — multiplier สำหรับ position size


def detect_regime(indicators: dict,
                  volatile_atr_pct:    float = 5.0,    # ATR > 5% ของ price = volatile
                  strong_trend_adx:    float = 25.0,
                  weak_trend_adx:      float = 20.0,
                  bb_squeeze_width:    float = 3.0     # BB width < 3% = squeeze
                  ) -> RegimeInfo:
    """
    จำแนก regime จาก indicators dict (output ของ get_all_indicators)

    Priority ของการตัดสิน:
        1. volatile  — ATR/price สูงเกิน threshold (override ทุกอย่าง)
        2. trending  — ADX > strong_trend_adx → bull/bear ตาม DI
        3. ranging   — ADX < weak_trend_adx (ไม่ใช่ volatile)
        4. mixed     — อยู่ระหว่าง weak และ strong (ADX 20–25)

    Parameters:
        indicators       — dict จาก get_all_indicators()
        volatile_atr_pct — เกณฑ์ ATR% สำหรับ classify ว่าเป็น "volatile"
        strong_trend_adx — ADX ขั้นต่ำที่ถือว่า "มี trend จริง"
        weak_trend_adx   — ADX ต่ำกว่าค่านี้ = sideways
    """
    if not indicators:
        return RegimeInfo(
            regime               = "mixed",
            confidence           = 0.0,
            adx=None, plus_di=None, minus_di=None,
            atr_pct=None, bb_width_pct=None,
            reason               = "no data",
            recommended_strategy = "wait",
            position_scale       = 0.0,   # ไม่มีข้อมูล → ไม่เทรด
        )

    price    = indicators.get("price", 0) or 0
    atr_val  = indicators.get("atr")
    adx_info = indicators.get("adx") or {}
    adx      = adx_info.get("adx")
    plus_di  = adx_info.get("plus_di")
    minus_di = adx_info.get("minus_di")
    bb       = indicators.get("bb") or {}

    # -------- คำนวณค่า derived --------
    atr_pct = (atr_val / price * 100) if (atr_val and price > 0) else None

    bb_width_pct = None
    bb_upper = bb.get("upper"); bb_lower = bb.get("lower"); bb_mid = bb.get("mid")
    if bb_upper and bb_lower and bb_mid and bb_mid > 0:
        bb_width_pct = (bb_upper - bb_lower) / bb_mid * 100

    # -------- Rule 1: volatile (มาก่อนทุกอย่าง) --------
    if atr_pct is not None and atr_pct >= volatile_atr_pct:
        strat, scale = _STRATEGY_MAP["volatile"]
        # confidence โตตามความห่างจาก threshold
        conf = min(1.0, atr_pct / (volatile_atr_pct * 2))
        return RegimeInfo(
            regime               = "volatile",
            confidence           = round(conf, 2),
            adx=adx, plus_di=plus_di, minus_di=minus_di,
            atr_pct=round(atr_pct, 3), bb_width_pct=_r(bb_width_pct, 3),
            reason               = (f"ATR={atr_pct:.2f}% ≥ {volatile_atr_pct}% "
                                    f"(high volatility)"),
            recommended_strategy = strat,
            position_scale       = scale,
        )

    # -------- Rule 2: trending (ต้องมี ADX + DI) --------
    if adx is not None and adx >= strong_trend_adx \
       and plus_di is not None and minus_di is not None:
        if plus_di > minus_di:
            regime = "trending_bull"
        else:
            regime = "trending_bear"
        strat, scale = _STRATEGY_MAP[regime]
        # confidence = sigmoid-ish จาก ADX
        conf = min(1.0, (adx - strong_trend_adx) / 25.0 + 0.5)
        return RegimeInfo(
            regime               = regime,
            confidence           = round(conf, 2),
            adx=adx, plus_di=plus_di, minus_di=minus_di,
            atr_pct=_r(atr_pct, 3), bb_width_pct=_r(bb_width_pct, 3),
            reason               = (f"ADX={adx:.1f} ≥ {strong_trend_adx} | "
                                    f"+DI={plus_di:.1f} "
                                    f"{'>' if plus_di > minus_di else '<'} "
                                    f"−DI={minus_di:.1f}"),
            recommended_strategy = strat,
            position_scale       = scale,
        )

    # -------- Rule 3: ranging (ADX อ่อน + ไม่ volatile) --------
    if adx is not None and adx < weak_trend_adx:
        strat, scale = _STRATEGY_MAP["ranging"]
        # BB squeeze → confidence ใน ranging ยิ่งสูง
        squeeze_bonus = 0.0
        if bb_width_pct is not None and bb_width_pct < bb_squeeze_width:
            squeeze_bonus = 0.2
        conf = min(1.0, (weak_trend_adx - adx) / weak_trend_adx + 0.5 + squeeze_bonus)
        return RegimeInfo(
            regime               = "ranging",
            confidence           = round(conf, 2),
            adx=adx, plus_di=plus_di, minus_di=minus_di,
            atr_pct=_r(atr_pct, 3), bb_width_pct=_r(bb_width_pct, 3),
            reason               = (f"ADX={adx:.1f} < {weak_trend_adx} "
                                    f"(sideways)" +
                                    (f" | BB squeeze {bb_width_pct:.1f}%"
                                     if squeeze_bonus else "")),
            recommended_strategy = strat,
            position_scale       = scale,
        )

    # -------- Rule 4: mixed (fallback — ADX 20–25 หรือไม่มีข้อมูล) --------
    strat, scale = _STRATEGY_MAP["mixed"]
    reason = "mixed: "
    if adx is None:
        reason += "ADX unavailable"
    elif weak_trend_adx <= adx < strong_trend_adx:
        reason += f"ADX={adx:.1f} in dead zone [{weak_trend_adx}, {strong_trend_adx})"
    else:
        reason += "ambiguous"
    return RegimeInfo(
        regime               = "mixed",
        confidence           = 0.5,
        adx=adx, plus_di=plus_di, minus_di=minus_di,
        atr_pct=_r(atr_pct, 3), bb_width_pct=_r(bb_width_pct, 3),
        reason               = reason,
        recommended_strategy = strat,
        position_scale       = scale,
    )


def detect_regime_for_symbol(symbol:     str,
                             resolution: str = "60",
                             **kwargs) -> RegimeInfo:
    """
    Convenience — fetch indicators แล้วส่งต่อให้ detect_regime
    kwargs จะส่งตรงไปให้ detect_regime (thresholds etc.)
    """
    ind = get_all_indicators(symbol, resolution=resolution)
    return detect_regime(ind, **kwargs)


def _r(x, d):
    """round-or-None helper"""
    return round(x, d) if x is not None else None
