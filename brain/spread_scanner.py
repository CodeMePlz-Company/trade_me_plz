from data.rest_client import get_all_tickers, get_order_book
from dataclasses import dataclass

MIN_VOLUME_THB = 1_000_000  # กรอง coin ที่ volume น้อยเกินออก

@dataclass
class SpreadOpportunity:
    symbol:     str
    bid:        float
    ask:        float
    spread_thb: float   # ส่วนต่าง bid-ask เป็น THB
    spread_pct: float   # ส่วนต่างเป็น %
    volume_24h: float

def scan_spreads(min_spread_pct: float = 0.3) -> list[SpreadOpportunity]:
    """
    สแกนทุก coin หา bid-ask spread กว้างผิดปกติ
    spread กว้าง = โอกาสวาง limit order กินส่วนต่าง
    """
    tickers = get_all_tickers()
    results = []

    for symbol, data in tickers.items():
        try:
            bid    = float(data.get("highestBid", 0))
            ask    = float(data.get("lowestAsk",  0))
            volume = float(data.get("quoteVolume", 0))

            if bid <= 0 or ask <= 0:
                continue
            if volume < MIN_VOLUME_THB:
                continue

            spread_thb = ask - bid
            spread_pct = (spread_thb / bid) * 100

            if spread_pct >= min_spread_pct:
                results.append(SpreadOpportunity(
                    symbol     = symbol,
                    bid        = bid,
                    ask        = ask,
                    spread_thb = round(spread_thb, 4),
                    spread_pct = round(spread_pct, 3),
                    volume_24h = volume,
                ))
        except:
            continue

    return sorted(results, key=lambda x: x.spread_pct, reverse=True)


def get_order_book_depth(symbol: str, levels: int = 5) -> dict:
    """
    วิเคราะห์ความลึกของ order book
    ดูว่า bid side แข็งแค่ไหน เทียบกับ ask side
    """
    book = get_order_book(symbol, limit=levels)
    bids = book.get("bids", [])
    asks = book.get("asks", [])

    total_bid_vol = sum(float(b[1]) for b in bids if b)
    total_ask_vol = sum(float(a[1]) for a in asks if a)

    ratio = (total_bid_vol / total_ask_vol) if total_ask_vol > 0 else 0

    return {
        "symbol":        symbol,
        "bid_volume":    round(total_bid_vol, 6),
        "ask_volume":    round(total_ask_vol, 6),
        "pressure_ratio": round(ratio, 3),
        # ratio > 1.5 = แรงซื้อมาก (bullish signal)
        # ratio < 0.7 = แรงขายมาก (bearish signal)
        "signal": "buy" if ratio > 1.5 else "sell" if ratio < 0.7 else "neutral"
    }


if __name__ == "__main__":
    print("กำลังสแกน spread...")
    opps = scan_spreads(min_spread_pct=0.2)
    print(f"พบ {len(opps)} โอกาส:\n")
    for o in opps[:10]:
        print(f"  {o.symbol:<12} spread={o.spread_pct:.2f}%  bid={o.bid}  ask={o.ask}  vol={o.volume_24h:,.0f}")

    print("\nวิเคราะห์ order book BTC_THB:")
    depth = get_order_book_depth("BTC_THB")
    print(f"  bid_vol={depth['bid_volume']}  ask_vol={depth['ask_volume']}  ratio={depth['pressure_ratio']}  signal={depth['signal']}")