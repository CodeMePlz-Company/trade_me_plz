from data.rest_client import get_ohlcv

def calc_sma(closes: list[float], period: int) -> list[float]:
    """Simple Moving Average"""
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(closes[i - period + 1: i + 1]) / period)
    return result

def calc_ema(closes: list[float], period: int) -> list[float]:
    """Exponential Moving Average"""
    result = []
    k = 2 / (period + 1)
    for i, price in enumerate(closes):
        if i == 0:
            result.append(price)
        else:
            result.append(price * k + result[-1] * (1 - k))
    return result

def calc_rsi(closes: list[float], period: int = 14) -> list[float]:
    """
    Relative Strength Index
    > 70 = overbought (พิจารณาขาย)
    < 30 = oversold   (พิจารณาซื้อ)
    """
    result = [None] * period
    gains, losses = [], []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    if len(gains) < period:
        return result

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi(ag, al):
        if al == 0:
            return 100
        rs = ag / al
        return 100 - (100 / (1 + rs))

    result.append(_rsi(avg_gain, avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result.append(_rsi(avg_gain, avg_loss))

    return result

def calc_bollinger(closes: list[float], period: int = 20, std_dev: float = 2.0) -> list[dict]:
    """
    Bollinger Bands
    ราคาแตะ lower band = โอกาสซื้อ
    ราคาแตะ upper band = โอกาสขาย
    """
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append({"mid": None, "upper": None, "lower": None})
            continue

        window = closes[i - period + 1: i + 1]
        mid    = sum(window) / period
        std    = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
        result.append({
            "mid":   round(mid, 2),
            "upper": round(mid + std_dev * std, 2),
            "lower": round(mid - std_dev * std, 2),
        })
    return result

def calc_atr(highs:  list[float],
             lows:   list[float],
             closes: list[float],
             period: int = 14) -> list[float]:
    """
    Average True Range — วัดความผันผวนสัมบูรณ์ (ในหน่วยราคา)
    ใช้ Wilder's smoothing:
        TR_i = max(high-low, |high-close_prev|, |low-close_prev|)
        ATR  = smooth(TR, period)

    ใช้สำหรับ ATR-based position sizing + dynamic stop-loss
    """
    n = len(closes)
    if n < 2 or len(highs) != n or len(lows) != n:
        return [None] * n

    # True Range: index 0 ไม่มี close_prev → ใช้ high-low
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i]  - closes[i - 1])
        tr.append(max(hl, hc, lc))

    # ATR: index < period → None; index == period → SMA; after → Wilder's
    atr: list[float] = [None] * n
    if n > period:
        first_atr = sum(tr[1:period + 1]) / period
        atr[period] = first_atr
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def calc_macd(closes: list[float],
              fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict]:
    """
    MACD — Moving Average Convergence Divergence
    macd > signal = bullish
    macd < signal = bearish
    """
    ema_fast   = calc_ema(closes, fast)
    ema_slow   = calc_ema(closes, slow)
    macd_line  = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = calc_ema(macd_line, signal)
    histogram  = [m - s for m, s in zip(macd_line, signal_line)]

    return [
        {
            "macd":      round(macd_line[i], 4),
            "signal":    round(signal_line[i], 4),
            "histogram": round(histogram[i], 4),
        }
        for i in range(len(closes))
    ]

def get_all_indicators(symbol: str = "BTC_THB",
                       resolution: str = "60") -> dict:
    """
    คำนวณ indicators ทั้งหมดจาก OHLCV
    ส่งคืนค่าล่าสุด (index -1) พร้อม signal
    """
    candles = get_ohlcv(symbol, resolution=resolution, limit=100)
    if not candles:
        return {}

    closes = [c["close"] for c in candles]
    last   = closes[-1]

    rsi_vals  = calc_rsi(closes)
    bb_vals   = calc_bollinger(closes)
    macd_vals = calc_macd(closes)
    sma20     = calc_sma(closes, 20)
    sma50     = calc_sma(closes, 50)

    rsi_now  = rsi_vals[-1]
    bb_now   = bb_vals[-1]
    macd_now = macd_vals[-1]

    # สรุป signal แต่ละตัว
    signals = {
        "rsi":  "buy"     if rsi_now and rsi_now < 30
                else "sell"    if rsi_now and rsi_now > 70
                else "neutral",
        "bb":   "buy"     if bb_now["lower"] and last < bb_now["lower"]
                else "sell"    if bb_now["upper"] and last > bb_now["upper"]
                else "neutral",
        "macd": "buy"     if macd_now["macd"] > macd_now["signal"]
                else "sell"    if macd_now["macd"] < macd_now["signal"]
                else "neutral",
        "ma":   "buy"     if sma20[-1] and sma50[-1] and sma20[-1] > sma50[-1]
                else "sell"    if sma20[-1] and sma50[-1] and sma20[-1] < sma50[-1]
                else "neutral",
    }

    # นับคะแนน buy/sell
    buy_count  = sum(1 for v in signals.values() if v == "buy")
    sell_count = sum(1 for v in signals.values() if v == "sell")
    consensus  = "buy"  if buy_count >= 3 \
            else "sell" if sell_count >= 3 \
            else "neutral"

    return {
        "symbol":    symbol,
        "price":     last,
        "rsi":       round(rsi_now, 2) if rsi_now else None,
        "bb":        bb_now,
        "macd":      macd_now,
        "sma20":     round(sma20[-1], 2) if sma20[-1] else None,
        "sma50":     round(sma50[-1], 2) if sma50[-1] else None,
        "signals":   signals,
        "consensus": consensus,   # buy / sell / neutral
        "buy_count": buy_count,
        "sell_count": sell_count,
    }


if __name__ == "__main__":
    result = get_all_indicators("BTC_THB", resolution="60")
    print(f"BTC_THB @ {result['price']:,}")
    print(f"RSI:      {result['rsi']}")
    print(f"BB upper: {result['bb']['upper']}  lower: {result['bb']['lower']}")
    print(f"MACD:     {result['macd']['macd']}  signal: {result['macd']['signal']}")
    print(f"SMA20:    {result['sma20']}  SMA50: {result['sma50']}")
    print(f"\nSignals:  {result['signals']}")
    print(f"Consensus: {result['consensus']} ({result['buy_count']} buy / {result['sell_count']} sell)")