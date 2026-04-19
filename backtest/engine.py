"""
engine.py — BacktestEngine หลัก + SimPortfolio

เดิน walk-forward ทีละ bar:
    1. mark-to-market ทุก open position
    2. เช็ค stop-loss (ถ้าโดน → ขายที่ราคา stop)
    3. คำนวณ indicators บน window ถึง bar ปัจจุบัน
    4. ถ้ามี signal → ตรวจ risk → (sim) ส่ง order
    5. บันทึก equity curve

สมมุติฐาน:
    - ใช้ close ของ bar เป็นราคา execution (realistic สำหรับ 1H/4H)
    - fee ทั้ง 2 ฝั่ง 0.25% ตาม Bitkub
    - 1 สัญลักษณ์ ถือได้ 1 position ในเวลาเดียวกัน
    - ไม่มี slippage (สำหรับ 1H frame พอรับได้; ควรเพิ่มถ้าย้ายไป 1-5 นาที)
"""
from dataclasses import dataclass, field
from typing import Literal

from brain.indicators import calc_rsi, calc_bollinger, calc_macd, calc_sma

FEE_RATE    = 0.0025   # 0.25% Bitkub
MIN_WARMUP  = 50       # ต้องมี bar ≥ 50 ก่อนเริ่มเทรด (สำหรับ SMA50)


# ========== Data classes ==========

@dataclass
class Trade:
    """บันทึกหนึ่ง trade (buy หรือ sell)"""
    time:          int
    symbol:        str
    action:        Literal["buy", "sell"]
    price:         float
    amount_thb:    float
    amount_crypto: float
    fee:           float
    pnl:           float = 0.0
    reason:        str = ""


@dataclass
class Position:
    """Position ที่เปิดอยู่"""
    symbol:        str
    entry_price:   float
    amount_crypto: float
    amount_thb:    float  # ต้นทุนที่จ่ายรวมค่าธรรมเนียม
    entry_time:    int


@dataclass
class BacktestResult:
    symbol:       str
    start_cash:   float
    end_cash:     float
    end_equity:   float       # cash + mark-to-market ณ bar สุดท้าย
    trades:       list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)   # (time, equity)
    stop_loss_hits: int = 0
    rejected_signals: int = 0


# ========== Simulated Portfolio ==========

class SimPortfolio:
    """Portfolio จำลอง — ไม่เรียก API"""

    def __init__(self, starting_cash: float = 100_000):
        self.cash       = starting_cash
        self.positions: dict[str, Position] = {}
        self.trades:    list[Trade] = []
        self.equity_history: list[tuple[int, float]] = []
        self.stop_loss_hits = 0
        self.rejected       = 0

    # ---------- Actions ----------

    def buy(self, symbol: str, price: float,
            amount_thb: float, ts: int, reason: str = "") -> Trade | None:
        """ซื้อด้วย amount_thb (รวม fee แล้ว ถ้า cash ไม่พอจะล้มเหลว)"""
        if amount_thb > self.cash:
            return None
        if symbol in self.positions:
            return None

        fee           = amount_thb * FEE_RATE
        amount_crypto = (amount_thb - fee) / price if price > 0 else 0

        self.cash -= amount_thb
        self.positions[symbol] = Position(
            symbol        = symbol,
            entry_price   = price,
            amount_crypto = amount_crypto,
            amount_thb    = amount_thb,
            entry_time    = ts,
        )

        trade = Trade(
            time          = ts,
            symbol        = symbol,
            action        = "buy",
            price         = price,
            amount_thb    = amount_thb,
            amount_crypto = amount_crypto,
            fee           = fee,
            reason        = reason,
        )
        self.trades.append(trade)
        return trade

    def sell(self, symbol: str, price: float,
             ts: int, reason: str = "") -> Trade | None:
        """ขายทั้ง position"""
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None

        gross = pos.amount_crypto * price
        fee   = gross * FEE_RATE
        net   = gross - fee
        pnl   = net - pos.amount_thb

        self.cash += net

        trade = Trade(
            time          = ts,
            symbol        = symbol,
            action        = "sell",
            price         = price,
            amount_thb    = gross,
            amount_crypto = pos.amount_crypto,
            fee           = fee,
            pnl           = pnl,
            reason        = reason,
        )
        self.trades.append(trade)
        return trade

    # ---------- Valuation ----------

    def mark_to_market(self, ts: int,
                       prices: dict[str, float]) -> float:
        """คำนวณ equity = cash + value of open positions"""
        equity = self.cash
        for sym, pos in self.positions.items():
            if sym in prices:
                equity += pos.amount_crypto * prices[sym]
        self.equity_history.append((ts, equity))
        return equity


# ========== Signal from indicators ==========

def compute_signal(closes: list[float],
                   min_confidence: float = 0.5) -> dict:
    """
    ใช้ indicators เดียวกับ brain/indicators.py
    แต่ทำงานบน list[float] ที่ให้มา (ไม่เรียก API)

    Return:
        {"action": "buy"/"sell"/"hold", "confidence": 0.0-1.0,
         "reason": str, "indicators": dict}
    """
    if len(closes) < MIN_WARMUP:
        return {"action": "hold", "confidence": 0.0,
                "reason": "warmup", "indicators": {}}

    last = closes[-1]

    rsi_vals  = calc_rsi(closes, 14)
    bb_vals   = calc_bollinger(closes, 20)
    macd_vals = calc_macd(closes)
    sma20     = calc_sma(closes, 20)
    sma50     = calc_sma(closes, 50)

    rsi_now  = rsi_vals[-1]
    bb_now   = bb_vals[-1]
    macd_now = macd_vals[-1]
    sma20_n  = sma20[-1]
    sma50_n  = sma50[-1]

    signals = {
        "rsi":  "buy"  if rsi_now and rsi_now < 30
             else "sell" if rsi_now and rsi_now > 70
             else "neutral",
        "bb":   "buy"  if bb_now["lower"] and last < bb_now["lower"]
             else "sell" if bb_now["upper"] and last > bb_now["upper"]
             else "neutral",
        "macd": "buy"  if macd_now["macd"] > macd_now["signal"]
             else "sell" if macd_now["macd"] < macd_now["signal"]
             else "neutral",
        "ma":   "buy"  if sma20_n and sma50_n and sma20_n > sma50_n
             else "sell" if sma20_n and sma50_n and sma20_n < sma50_n
             else "neutral",
    }

    buy_count  = sum(1 for v in signals.values() if v == "buy")
    sell_count = sum(1 for v in signals.values() if v == "sell")

    consensus = ("buy"  if buy_count >= 3
                 else "sell" if sell_count >= 3
                 else "hold")
    confidence = max(buy_count, sell_count) / 4.0

    if consensus == "hold" or confidence < min_confidence:
        return {"action": "hold", "confidence": confidence,
                "reason": f"consensus={consensus} conf={confidence:.2f}",
                "indicators": signals}

    reason = ", ".join(f"{k}={v}" for k, v in signals.items() if v != "neutral")
    return {"action": consensus, "confidence": confidence,
            "reason": reason, "indicators": signals}


# ========== BacktestEngine ==========

class BacktestEngine:
    """
    Engine หลักสำหรับรัน backtest symbol เดียว
    ใช้ parameter เดียวกับ config.py ของ production
    """

    def __init__(self,
                 starting_cash:    float = 100_000,
                 max_position_pct: float = 0.10,
                 stop_loss_pct:    float = 0.03,
                 min_confidence:   float = 0.50,
                 max_daily_loss:   float = 0.05):
        self.starting_cash    = starting_cash
        self.max_position_pct = max_position_pct
        self.stop_loss_pct    = stop_loss_pct
        self.min_confidence   = min_confidence
        self.max_daily_loss   = max_daily_loss

    def run(self,
            candles: list[dict],
            symbol:  str = "BTC_THB",
            verbose: bool = False) -> BacktestResult:
        """เดินผ่านทุก candle แบบ walk-forward"""
        portfolio = SimPortfolio(self.starting_cash)
        closes    = [c["close"] for c in candles]

        # daily loss tracker — reset ทุก 24H
        day_loss  = 0.0
        day_anchor = candles[0]["time"] if candles else 0

        for i, bar in enumerate(candles):
            price = bar["close"]
            ts    = bar["time"]

            # reset daily loss ทุก 86400 วินาที
            if ts - day_anchor >= 86400:
                day_loss = 0.0
                day_anchor = ts

            # ----- 1. check stop-loss บน open position -----
            if symbol in portfolio.positions:
                pos     = portfolio.positions[symbol]
                loss_pct = (pos.entry_price - price) / pos.entry_price
                if loss_pct >= self.stop_loss_pct:
                    trade = portfolio.sell(symbol, price, ts,
                                           reason="stop-loss")
                    portfolio.stop_loss_hits += 1
                    if trade and trade.pnl < 0:
                        day_loss += abs(trade.pnl)
                    if verbose:
                        print(f"  [{i}] STOP-LOSS {symbol} @ {price:,.2f} "
                              f"loss={loss_pct:.2%} pnl={trade.pnl:+.2f}")

            # ----- 2. ต้องมี warmup พอ -----
            if i < MIN_WARMUP:
                portfolio.mark_to_market(ts, {symbol: price})
                continue

            # ----- 3. daily loss limit -----
            if day_loss / max(self.starting_cash, 1) >= self.max_daily_loss:
                portfolio.rejected += 1
                portfolio.mark_to_market(ts, {symbol: price})
                continue

            # ----- 4. compute signal จาก window -----
            signal = compute_signal(closes[: i + 1],
                                    min_confidence=self.min_confidence)

            # ----- 5. execute -----
            if signal["action"] == "buy" and symbol not in portfolio.positions:
                balance    = portfolio.cash
                order_size = round(balance * self.max_position_pct, 2)
                if order_size >= 20:       # Bitkub minimum
                    trade = portfolio.buy(symbol, price, order_size, ts,
                                          reason=signal["reason"])
                    if verbose and trade:
                        print(f"  [{i}] BUY  {symbol} @ {price:,.2f} "
                              f"size={order_size:.0f} "
                              f"conf={signal['confidence']:.2f}")

            elif signal["action"] == "sell" and symbol in portfolio.positions:
                trade = portfolio.sell(symbol, price, ts,
                                       reason=signal["reason"])
                if trade and trade.pnl < 0:
                    day_loss += abs(trade.pnl)
                if verbose and trade:
                    print(f"  [{i}] SELL {symbol} @ {price:,.2f} "
                          f"pnl={trade.pnl:+.2f}")

            # ----- 6. mark-to-market -----
            portfolio.mark_to_market(ts, {symbol: price})

        # ----- จบลูป — ปิด open position ที่ราคาสุดท้าย -----
        if symbol in portfolio.positions:
            last = candles[-1]
            portfolio.sell(symbol, last["close"], last["time"],
                           reason="end-of-test")
            portfolio.mark_to_market(last["time"], {symbol: last["close"]})

        end_equity = (portfolio.equity_history[-1][1]
                      if portfolio.equity_history else portfolio.cash)

        return BacktestResult(
            symbol         = symbol,
            start_cash     = self.starting_cash,
            end_cash       = portfolio.cash,
            end_equity     = end_equity,
            trades         = portfolio.trades,
            equity_curve   = portfolio.equity_history,
            stop_loss_hits = portfolio.stop_loss_hits,
            rejected_signals = portfolio.rejected,
        )
