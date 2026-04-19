import time
import schedule
import threading
from datetime import datetime

import config
from data.collector        import DataCollector
from brain.strategy        import run_strategy
from execution.risk_manager import RiskManager
from execution.order_manager import (
    get_thb_balance, get_crypto_balance,
    place_buy_market, place_sell_market
)
from execution.portfolio   import Portfolio
from execution.notifier    import (
    notify_buy, notify_sell,
    notify_stop_loss, notify_take_profit, notify_trailing_stop,
    notify_error, notify_summary
)

# ========== Init ==========
collector  = DataCollector(config.SYMBOLS)
risk       = RiskManager(
    max_position_pct  = config.MAX_POSITION_PCT,
    max_daily_loss    = config.MAX_DAILY_LOSS,
    stop_loss_pct     = config.STOP_LOSS_PCT,
    take_profit_pct   = config.TAKE_PROFIT_PCT,
    trailing_stop_pct = config.TRAILING_STOP_PCT,
    min_confidence    = config.MIN_CONFIDENCE,
)
portfolio  = Portfolio()

# ========== Core Loop ==========

def run_scan():
    """รอบหลัก — สแกน + ตัดสินใจ + execute"""
    print(f"\n{'='*50}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] รันรอบใหม่...")

    try:
        balance = get_thb_balance()
        print(f"  THB balance: {balance:,.2f}")

        signals = run_strategy(
            symbols    = config.SYMBOLS,
            mode       = config.STRATEGY_MODE,
            resolution = config.RESOLUTION,
        )

        for signal in signals:
            if signal.action == "buy":
                _handle_buy(signal, balance)
            elif signal.action == "sell":
                _handle_sell(signal)

    except Exception as e:
        print(f"[ERROR] run_scan: {e}")
        notify_error(str(e))


def _handle_buy(signal, balance: float):
    """จัดการ buy signal"""

    # 1. ขอ approval จาก risk manager
    assessment = risk.approve(
        symbol        = signal.symbol,
        action        = "buy",
        confidence    = signal.confidence,
        balance_thb   = balance,
        current_price = signal.price,
    )

    if not assessment.approved:
        print(f"  [RISK] {signal.symbol} ถูกปฏิเสธ — {assessment.reason}")
        return

    amount_thb = assessment.position_size
    print(f"  [BUY] {signal.symbol} {amount_thb:.2f} THB @ {signal.price:,} "
          f"(confidence={signal.confidence})")

    if config.SIMULATION_MODE:
        print(f"  [SIM] จำลอง BUY — ไม่ส่ง order จริง")
        portfolio.record_buy(
            symbol        = signal.symbol,
            price         = signal.price,
            amount_thb    = amount_thb,
            fee           = amount_thb * 0.0025,   # Bitkub fee 0.25%
            balance_after = balance - amount_thb,
        )
    else:
        result = place_buy_market(signal.symbol, amount_thb)
        if result.get("error") == 0:
            portfolio.record_buy(
                symbol        = signal.symbol,
                price         = signal.price,
                amount_thb    = amount_thb,
                fee           = amount_thb * 0.0025,
                balance_after = balance - amount_thb,
            )
            notify_buy(signal.symbol, signal.price,
                       amount_thb, signal.confidence)
        else:
            print(f"  [ERROR] BUY failed: {result}")
            notify_error(f"BUY {signal.symbol} failed: {result}")


def _handle_sell(signal):
    """จัดการ sell signal"""
    amount_crypto = get_crypto_balance(signal.symbol)

    if amount_crypto <= 0:
        print(f"  [SELL] {signal.symbol} ไม่มี crypto ที่จะขาย")
        return

    print(f"  [SELL] {signal.symbol} {amount_crypto:.8f} @ {signal.price:,}")

    if config.SIMULATION_MODE:
        print(f"  [SIM] จำลอง SELL — ไม่ส่ง order จริง")
        balance = get_thb_balance()
        pnl = portfolio.record_sell(
            symbol        = signal.symbol,
            price         = signal.price,
            amount_crypto = amount_crypto,
            fee           = amount_crypto * signal.price * 0.0025,
            balance_after = balance + amount_crypto * signal.price,
        )
        risk.close_position(signal.symbol)
    else:
        result = place_sell_market(signal.symbol, amount_crypto)
        if result.get("error") == 0:
            balance = get_thb_balance()
            pnl = portfolio.record_sell(
                symbol        = signal.symbol,
                price         = signal.price,
                amount_crypto = amount_crypto,
                fee           = amount_crypto * signal.price * 0.0025,
                balance_after = balance,
            )
            risk.close_position(signal.symbol)
            notify_sell(signal.symbol, signal.price,
                        pnl, portfolio.get_summary()["win_rate"])
            if pnl < 0:
                risk.record_loss(abs(pnl))
        else:
            print(f"  [ERROR] SELL failed: {result}")
            notify_error(f"SELL {signal.symbol} failed: {result}")


def check_exits():
    """
    เช็ค exit conditions ทุก 10 วินาที
    Priority: take-profit > trailing-stop > stop-loss
    """
    for symbol in list(risk.open_positions.keys()):
        try:
            snap  = collector.get_snapshot(symbol)
            price = snap.get("ticker", {}).get("last", 0)
            if not price:
                continue

            price = float(price)

            # ใช้ check_exit แทนการเช็คทีละเงื่อนไข
            decision = risk.check_exit(symbol, price)
            if not decision.should_exit:
                continue

            reason = decision.reason
            entry  = decision.entry_price
            peak   = decision.peak_price

            change_pct = (price - entry) / entry * 100
            print(f"  [{reason.upper()}] {symbol} @ {price:,} "
                  f"entry={entry:,} peak={peak:,} change={change_pct:+.2f}%")

            amount_crypto = get_crypto_balance(symbol)
            if amount_crypto <= 0:
                risk.close_position(symbol)
                continue

            if not config.SIMULATION_MODE:
                place_sell_market(symbol, amount_crypto)

            balance = get_thb_balance()
            pnl = portfolio.record_sell(
                symbol        = symbol,
                price         = price,
                amount_crypto = amount_crypto,
                fee           = amount_crypto * price * 0.0025,
                balance_after = balance,
            )
            risk.close_position(symbol)

            # ส่ง notification ตาม reason
            if reason == "take-profit":
                notify_take_profit(symbol, entry, price, pnl)
            elif reason == "trailing-stop":
                notify_trailing_stop(symbol, entry, peak, price, pnl)
            else:    # stop-loss
                notify_stop_loss(symbol, entry, price, abs(pnl))
                if pnl < 0:
                    risk.record_loss(abs(pnl))

        except Exception as e:
            print(f"[ERROR] exit check {symbol}: {e}")


# เก็บ alias เดิมเพื่อ backward compat ถ้ามีโค้ดเรียก check_stop_loss
check_stop_loss = check_exits


def send_daily_summary():
    """ส่งสรุปประจำวัน + รีเซ็ต daily loss"""
    summary = portfolio.get_summary()
    portfolio.print_summary()
    notify_summary(summary)
    risk.reset_daily()


# ========== Scheduler ==========

def start_scheduler():
    schedule.every(config.SCAN_INTERVAL_SEC).seconds.do(run_scan)
    schedule.every(config.STOP_LOSS_CHECK_SEC).seconds.do(check_exits)
    schedule.every().day.at(f"{config.SUMMARY_HOUR:02d}:00").do(send_daily_summary)

    while True:
        schedule.run_pending()
        time.sleep(1)


# ========== Entry Point ==========

if __name__ == "__main__":
    print("=" * 50)
    print("  Bitkub Trading Bot")
    print(f"  Mode: {'SIMULATION' if config.SIMULATION_MODE else 'LIVE'}")
    print(f"  Symbols: {config.SYMBOLS}")
    print(f"  Strategy: {config.STRATEGY_MODE}")
    print("=" * 50)

    # เริ่ม data collector (WebSocket)
    collector.start()
    time.sleep(3)   # รอ WS connect

    # รันรอบแรกทันที
    run_scan()

    # เริ่ม scheduler ใน background
    scheduler_thread = threading.Thread(
        target=start_scheduler, daemon=True
    )
    scheduler_thread.start()

    # keep alive + แสดง summary ทุก 5 นาที
    try:
        while True:
            time.sleep(300)
            portfolio.print_summary()
    except KeyboardInterrupt:
        print("\n[BOT] หยุดการทำงาน")
        portfolio.print_summary()