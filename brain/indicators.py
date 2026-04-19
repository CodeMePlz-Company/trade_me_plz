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


def calc_stochastic(highs:  list[float],
                    lows:   list[float],
                    closes: list[float],
                    k_period: int = 14,
                    d_period: int = 3) -> list[dict]:
    """
    Stochastic Oscillator (%K, %D)
        %K = 100 × (close − lowest_low_N) / (highest_high_N − lowest_low_N)
        %D = SMA(%K, d_period)
    > 80 = overbought (sell zone)
    < 20 = oversold   (buy zone)
    """
    n = len(closes)
    k_vals: list = [None] * n
    for i in range(k_period - 1, n):
        window_h = highs[i - k_period + 1: i + 1]
        window_l = lows [i - k_period + 1: i + 1]
        hh = max(window_h)
        ll = min(window_l)
        if hh == ll:                        # flat window → 50 (neutral)
            k_vals[i] = 50.0
        else:
            k_vals[i] = 100.0 * (closes[i] - ll) / (hh - ll)

    d_vals: list = [None] * n
    for i in range(k_period + d_period - 2, n):
        window = [k_vals[j] for j in range(i - d_period + 1, i + 1)
                  if k_vals[j] is not None]
        if len(window) == d_period:
            d_vals[i] = sum(window) / d_period

    return [
        {
            "k": round(k_vals[i], 2) if k_vals[i] is not None else None,
            "d": round(d_vals[i], 2) if d_vals[i] is not None else None,
        }
        for i in range(n)
    ]


def calc_adx(highs:  list[float],
             lows:   list[float],
             closes: list[float],
             period: int = 14) -> list[dict]:
    """
    ADX — Average Directional Index (Wilder 1978)
        +DI / −DI  — ทิศทางของ trend
        ADX        — ความแรงของ trend (ไม่สนทิศ)

    Interpretation:
        ADX > 25  — strong trend (indicator-based strategy ใช้ได้)
        ADX < 20  — sideways market (mean-reversion strategy เหมาะกว่า)
        +DI > −DI — bullish direction
        −DI > +DI — bearish direction

    คืนค่า list ของ dict { adx, plus_di, minus_di }
    """
    n = len(closes)
    blank = [{"adx": None, "plus_di": None, "minus_di": None}] * n
    if n < 2 * period + 1 or len(highs) != n or len(lows) != n:
        return blank

    # 1. True Range + directional movement
    tr       = [0.0]
    plus_dm  = [0.0]
    minus_dm = [0.0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i]  - closes[i - 1])
        tr.append(max(hl, hc, lc))

        up = highs[i]     - highs[i - 1]
        dn = lows[i - 1]  - lows[i]
        plus_dm.append (up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)

    # 2. Wilder's smoothing ของ TR, +DM, −DM
    atr_s : list = [None] * n
    pdi_s : list = [None] * n
    mdi_s : list = [None] * n
    atr_s[period] = sum(tr      [1: period + 1]) / period
    pdi_s[period] = sum(plus_dm [1: period + 1]) / period
    mdi_s[period] = sum(minus_dm[1: period + 1]) / period
    for i in range(period + 1, n):
        atr_s[i] = (atr_s[i - 1] * (period - 1) + tr[i])       / period
        pdi_s[i] = (pdi_s[i - 1] * (period - 1) + plus_dm[i])  / period
        mdi_s[i] = (mdi_s[i - 1] * (period - 1) + minus_dm[i]) / period

    # 3. DI± + DX
    dx: list = [None] * n
    for i in range(period, n):
        if atr_s[i] and atr_s[i] > 0:
            plus_di  = 100 * pdi_s[i] / atr_s[i]
            minus_di = 100 * mdi_s[i] / atr_s[i]
            s = plus_di + minus_di
            dx[i] = 100 * abs(plus_di - minus_di) / s if s > 0 else 0.0

    # 4. ADX = Wilder smoothing of DX
    adx: list = [None] * n
    if n > 2 * period:
        # first ADX = SMA ของ DX ตั้งแต่ index `period` ถึง `2*period-1`
        seed_window = [dx[i] for i in range(period, 2 * period) if dx[i] is not None]
        if len(seed_window) == period:
            adx[2 * period - 1] = sum(seed_window) / period
            for i in range(2 * period, n):
                if dx[i] is not None and adx[i - 1] is not None:
                    adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    result = []
    for i in range(n):
        p_di = round(100 * pdi_s[i] / atr_s[i], 2) \
               if (atr_s[i] and atr_s[i] > 0) else None
        m_di = round(100 * mdi_s[i] / atr_s[i], 2) \
               if (atr_s[i] and atr_s[i] > 0) else None
        result.append({
            "adx":      round(adx[i], 2) if adx[i] is not None else None,
            "plus_di":  p_di,
            "minus_di": m_di,
        })
    return result


def calc_volume_profile(highs:   list[float],
                        lows:    list[float],
                        volumes: list[float],
                        num_bins: int = 20,
                        value_area_pct: float = 0.70) -> dict:
    """
    Volume Profile — distribution ของ volume ตามราคา

    Returns:
        poc       — Point of Control (ราคาที่ volume เยอะสุด = "magnet")
        vah / val — Value Area High/Low (ขอบเขตที่ครอบคลุม 70% ของ volume)
        bins      — list ของ volume ต่อ price bin (ไว้ plot)
        bin_low   — ราคาขอบล่างสุด
        bin_size  — ขนาดของแต่ละ bin (ในหน่วย THB)

    Signal interpretation:
        close ≥ vah  — ขยับเหนือ value area (อาจ breakout หรือ overextend)
        close ≤ val  — ต่ำกว่า value area  (อาจ bounce จากโซนดี)
        close ≈ poc  — "fair value" — ต้องรอ confirmation
    """
    if not highs or not lows or not volumes:
        return {}
    n = len(highs)
    if len(lows) != n or len(volumes) != n:
        return {}

    p_lo = min(lows)
    p_hi = max(highs)
    if p_hi <= p_lo:
        return {}

    bin_size = (p_hi - p_lo) / num_bins
    bins = [0.0] * num_bins

    for i in range(n):
        lo_idx = int((lows[i]  - p_lo) / bin_size)
        hi_idx = int((highs[i] - p_lo) / bin_size)
        lo_idx = max(0, min(lo_idx, num_bins - 1))
        hi_idx = max(0, min(hi_idx, num_bins - 1))
        span   = hi_idx - lo_idx + 1
        per    = volumes[i] / span
        for b in range(lo_idx, hi_idx + 1):
            bins[b] += per

    # POC = bin ที่ volume สูงสุด
    poc_idx   = max(range(num_bins), key=lambda i: bins[i])
    poc_price = p_lo + (poc_idx + 0.5) * bin_size

    # Value Area = โซนรอบ POC ที่รวม 70% ของ total volume
    total  = sum(bins)
    target = total * value_area_pct
    lo_idx, hi_idx = poc_idx, poc_idx
    accum  = bins[poc_idx]
    while accum < target and (lo_idx > 0 or hi_idx < num_bins - 1):
        up = bins[hi_idx + 1] if hi_idx < num_bins - 1 else -1
        dn = bins[lo_idx - 1] if lo_idx > 0            else -1
        if up >= dn:
            hi_idx += 1
            accum  += up
        else:
            lo_idx -= 1
            accum  += dn

    return {
        "poc":      round(poc_price, 2),
        "vah":      round(p_lo + (hi_idx + 1) * bin_size, 2),
        "val":      round(p_lo + lo_idx * bin_size, 2),
        "bins":     [round(b, 4) for b in bins],
        "bin_low":  round(p_lo, 2),
        "bin_size": round(bin_size, 4),
    }


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

    รวม indicators:
        RSI, Bollinger, MACD, SMA20/50 (trend/momentum)
        ATR              (volatility — ใช้ใน position sizing)
        Stochastic (K,D) (overbought/oversold)
        ADX (+DI,−DI)    (trend strength + direction)
        Volume Profile   (POC / VAH / VAL)
    """
    candles = get_ohlcv(symbol, resolution=resolution, limit=100)
    if not candles:
        return {}

    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    closes  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]
    last    = closes[-1]

    rsi_vals  = calc_rsi(closes)
    bb_vals   = calc_bollinger(closes)
    macd_vals = calc_macd(closes)
    sma20     = calc_sma(closes, 20)
    sma50     = calc_sma(closes, 50)
    atr_vals  = calc_atr(highs, lows, closes)
    stoch_vals = calc_stochastic(highs, lows, closes)
    adx_vals  = calc_adx(highs, lows, closes)
    vp        = calc_volume_profile(highs, lows, volumes)

    rsi_now   = rsi_vals [-1]
    bb_now    = bb_vals  [-1]
    macd_now  = macd_vals[-1]
    atr_now   = atr_vals [-1]
    stoch_now = stoch_vals[-1]
    adx_now   = adx_vals [-1]

    # ---- Stochastic signal ----
    k = stoch_now.get("k")
    stoch_sig = ("buy"  if k is not None and k < 20
                 else "sell" if k is not None and k > 80
                 else "neutral")

    # ---- ADX trend strength + direction ----
    adx_v    = adx_now.get("adx")
    plus_di  = adx_now.get("plus_di")
    minus_di = adx_now.get("minus_di")
    is_trending = adx_v is not None and adx_v > 25
    is_sideways = adx_v is not None and adx_v < 20
    if is_trending and plus_di is not None and minus_di is not None:
        adx_sig = "buy" if plus_di > minus_di else "sell"
    else:
        adx_sig = "neutral"

    # ---- Volume Profile signal ----
    # ถ้าราคาต่ำกว่า VAL → มักเด้งกลับมา (buy)
    # ถ้าราคาสูงกว่า VAH → มัก pullback (sell)
    if vp and vp.get("val") and vp.get("vah"):
        if   last <= vp["val"]: vp_sig = "buy"
        elif last >= vp["vah"]: vp_sig = "sell"
        else:                   vp_sig = "neutral"
    else:
        vp_sig = "neutral"

    # สรุป signal แต่ละตัว
    signals = {
        "rsi":   "buy"     if rsi_now and rsi_now < 30
                 else "sell"    if rsi_now and rsi_now > 70
                 else "neutral",
        "bb":    "buy"     if bb_now["lower"] and last < bb_now["lower"]
                 else "sell"    if bb_now["upper"] and last > bb_now["upper"]
                 else "neutral",
        "macd":  "buy"     if macd_now["macd"] > macd_now["signal"]
                 else "sell"    if macd_now["macd"] < macd_now["signal"]
                 else "neutral",
        "ma":    "buy"     if sma20[-1] and sma50[-1] and sma20[-1] > sma50[-1]
                 else "sell"    if sma20[-1] and sma50[-1] and sma20[-1] < sma50[-1]
                 else "neutral",
        "stoch": stoch_sig,
        "adx":   adx_sig,
        "vp":    vp_sig,
    }

    # นับคะแนน buy/sell (threshold เพิ่มตามจำนวน indicators ใหม่)
    buy_count  = sum(1 for v in signals.values() if v == "buy")
    sell_count = sum(1 for v in signals.values() if v == "sell")
    # 7 indicators → majority ≥ 4 → consensus
    consensus  = "buy"  if buy_count >= 4 \
            else "sell" if sell_count >= 4 \
            else "neutral"

    return {
        "symbol":      symbol,
        "price":       last,
        "rsi":         round(rsi_now, 2) if rsi_now else None,
        "bb":          bb_now,
        "macd":        macd_now,
        "sma20":       round(sma20[-1], 2) if sma20[-1] else None,
        "sma50":       round(sma50[-1], 2) if sma50[-1] else None,
        "atr":         round(atr_now, 2) if atr_now else None,
        "stoch":       stoch_now,
        "adx":         adx_now,          # {adx, plus_di, minus_di}
        "vp":          vp,               # {poc, vah, val, ...}
        "is_trending": is_trending,      # ADX > 25
        "is_sideways": is_sideways,      # ADX < 20
        "signals":     signals,
        "consensus":   consensus,        # buy / sell / neutral
        "buy_count":   buy_count,
        "sell_count":  sell_count,
    }


if __name__ == "__main__":
    result = get_all_indicators("BTC_THB", resolution="60")
    print(f"BTC_THB @ {result['price']:,}")
    print(f"RSI:      {result['rsi']}")
    print(f"BB upper: {result['bb']['upper']}  lower: {result['bb']['lower']}")
    print(f"MACD:     {result['macd']['macd']}  signal: {result['macd']['signal']}")
    print(f"SMA20:    {result['sma20']}  SMA50: {result['sma50']}")
    print(f"ATR:      {result['atr']}")
    print(f"Stoch:    K={result['stoch']['k']}  D={result['stoch']['d']}")
    print(f"ADX:      {result['adx']['adx']}  +DI={result['adx']['plus_di']}  "
          f"−DI={result['adx']['minus_di']}  "
          f"({'trending' if result['is_trending'] else 'sideways' if result['is_sideways'] else 'mixed'})")
    if result["vp"]:
        print(f"VP:       POC={result['vp']['poc']:,}  VAH={result['vp']['vah']:,}  "
              f"VAL={result['vp']['val']:,}")
    print(f"\nSignals:  {result['signals']}")
    print(f"Consensus: {result['consensus']} "
          f"({result['buy_count']} buy / {result['sell_count']} sell / 7)")