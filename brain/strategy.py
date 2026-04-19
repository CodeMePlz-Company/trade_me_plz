from brain.spread_scanner import scan_spreads, get_order_book_depth
from brain.indicators import get_all_indicators
from dataclasses import dataclass
from typing import Literal

@dataclass
class TradeSignal:
    symbol:     str
    action:     Literal["buy", "sell", "hold"]
    reason:     str
    confidence: float   # 0.0 - 1.0
    price:      float

def strategy_indicator(symbol: str,
                       resolution: str = "60") -> TradeSignal:
    """
    กลยุทธ์ที่ 1 — Indicator-based
    ซื้อเมื่อ indicators ส่วนใหญ่บอก buy
    ขายเมื่อ indicators ส่วนใหญ่บอก sell
    """
    ind = get_all_indicators(symbol, resolution)
    if not ind:
        return TradeSignal(symbol, "hold", "ไม่มีข้อมูล", 0.0, 0)

    consensus  = ind["consensus"]
    buy_count  = ind["buy_count"]
    sell_count = ind["sell_count"]
    confidence = max(buy_count, sell_count) / 4  # 4 indicators

    reason_parts = []
    for name, sig in ind["signals"].items():
        if sig != "neutral":
            reason_parts.append(f"{name}={sig}")
    reason = ", ".join(reason_parts) if reason_parts else "neutral"

    return TradeSignal(
        symbol     = symbol,
        action     = consensus,
        reason     = reason,
        confidence = round(confidence, 2),
        price      = ind["price"],
    )

def strategy_spread(min_spread_pct: float = 0.3) -> list[TradeSignal]:
    """
    กลยุทธ์ที่ 2 — Spread Arbitrage
    หาตลาดที่ spread กว้าง → วาง limit buy ใกล้ bid
    """
    opps = scan_spreads(min_spread_pct)
    signals = []

    for opp in opps[:5]:  # top 5 โอกาสเท่านั้น
        depth = get_order_book_depth(opp.symbol)

        # เข้าเฉพาะเมื่อแรงซื้อแข็ง
        if depth["signal"] == "buy":
            signals.append(TradeSignal(
                symbol     = opp.symbol,
                action     = "buy",
                reason     = f"spread={opp.spread_pct}% + buy pressure ratio={depth['pressure_ratio']}",
                confidence = min(opp.spread_pct / 2, 1.0),
                price      = opp.bid,
            ))

    return signals

def run_strategy(symbols: list[str],
                 mode: Literal["indicator", "spread", "combined"] = "combined",
                 resolution: str = "60") -> list[TradeSignal]:
    """
    รวม strategy ทั้งหมด ส่งคืน signals ที่ผ่านเกณฑ์
    mode:
      indicator — ใช้ RSI/MACD/BB/MA
      spread    — ใช้ bid-ask gap
      combined  — ใช้ทั้งสอง (แนะนำ)
    """
    final_signals = []

    if mode in ("indicator", "combined"):
        for sym in symbols:
            sig = strategy_indicator(sym, resolution)
            if sig.action != "hold" and sig.confidence >= 0.5:
                final_signals.append(sig)
                print(f"[STRATEGY] {sig.symbol} → {sig.action.upper()} "
                      f"(confidence={sig.confidence}) reason: {sig.reason}")

    if mode in ("spread", "combined"):
        spread_signals = strategy_spread()
        for sig in spread_signals:
            if sig.confidence >= 0.3:
                final_signals.append(sig)
                print(f"[SPREAD]   {sig.symbol} → {sig.action.upper()} "
                      f"(confidence={sig.confidence}) reason: {sig.reason}")

    return final_signals


if __name__ == "__main__":
    SYMBOLS = ["BTC_THB", "ETH_THB", "XRP_THB"]

    print("=" * 50)
    print("รัน strategy combined mode")
    print("=" * 50)

    signals = run_strategy(SYMBOLS, mode="combined", resolution="60")

    print(f"\nสรุป: พบ {len(signals)} signal")
    for s in signals:
        print(f"  {s.symbol} | {s.action.upper()} | confidence={s.confidence} | price={s.price:,}")