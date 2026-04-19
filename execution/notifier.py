"""
LINE Messaging API Notifier
────────────────────────────
ส่งแจ้งเตือนผ่าน LINE Messaging API (Push Message)
พร้อม retry logic, error handling, และ fallback log

Docs: https://developers.line.biz/en/reference/messaging-api/#send-push-message
"""
import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_TARGET_ID            = os.getenv("LINE_TARGET_ID", "")

LINE_API_URL   = "https://api.line.me/v2/bot/message/push"
MAX_MSG_LENGTH = 5000    # LINE text message limit
MAX_RETRIES    = 3
FALLBACK_LOG   = "logs/notifications_failed.log"


def _log_fallback(message: str, reason: str) -> None:
    """บันทึกข้อความที่ส่งไม่สำเร็จลง log file"""
    os.makedirs("logs", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(FALLBACK_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] FAILED ({reason})\n{message}\n{'-'*50}\n")


def send_line(message: str) -> bool:
    """
    ส่งแจ้งเตือนผ่าน LINE Messaging API (Push Message)

    Returns:
        True  — ส่งสำเร็จ
        False — ส่งไม่สำเร็จ (เก็บลง fallback log แล้ว)
    """
    # ตรวจสอบ config
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_TARGET_ID:
        print(f"🚫 [NOTIFY] ขาด LINE_CHANNEL_ACCESS_TOKEN หรือ LINE_TARGET_ID")
        print(f"   ข้อความ: {message}")
        _log_fallback(message, "missing_credentials")
        return False

    # ตรวจสอบความยาว (LINE จำกัด 5000 ตัวอักษร)
    if len(message) > MAX_MSG_LENGTH:
        print(f"⚠️  [NOTIFY] ข้อความยาวเกิน {MAX_MSG_LENGTH} ตัวอักษร — ตัดท้าย")
        message = message[: MAX_MSG_LENGTH - 3] + "..."

    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": LINE_TARGET_ID,
        "messages": [{"type": "text", "text": message}],
    }

    # Retry with exponential backoff: 1s, 2s, 4s
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(LINE_API_URL, headers=headers,
                              json=payload, timeout=10)

            # สำเร็จ
            if r.status_code == 200:
                return True

            # จัดการ error codes
            err_body = r.text[:200]
            if r.status_code == 401:
                print(f"🚫 [NOTIFY] 401 Unauthorized — LINE_CHANNEL_ACCESS_TOKEN หมดอายุหรือผิด")
                _log_fallback(message, "invalid_token")
                return False    # ไม่ retry — token ผิด

            if r.status_code == 403:
                print(f"🚫 [NOTIFY] 403 Forbidden — ไม่มีสิทธิ์ส่งให้ LINE_TARGET_ID={LINE_TARGET_ID}")
                _log_fallback(message, "forbidden")
                return False    # ไม่ retry

            if r.status_code == 429:
                # Rate limit — รอแล้วลองใหม่
                wait = 2 ** attempt
                print(f"⏳ [NOTIFY] 429 Rate Limit — รอ {wait}s แล้วลองใหม่ (ครั้งที่ {attempt})")
                time.sleep(wait)
                continue

            # 4xx/5xx อื่น ๆ
            print(f"⚠️  [NOTIFY] HTTP {r.status_code}: {err_body}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue

            _log_fallback(message, f"http_{r.status_code}")
            return False

        except requests.exceptions.Timeout:
            print(f"⏱️  [NOTIFY] timeout (ครั้งที่ {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            _log_fallback(message, "timeout")
            return False

        except requests.exceptions.RequestException as e:
            print(f"🚫 [NOTIFY] RequestException: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            _log_fallback(message, f"request_error: {e}")
            return False

    return False


# ========== Notification Templates ==========

def notify_buy(symbol: str, price: float,
               amount_thb: float, confidence: float) -> bool:
    return send_line(
        f"🟢 𝗕𝗨𝗬 : {symbol}\n"
        f"───────────────\n"
        f"💵 ราคา   : {price:,.2f} ฿\n"
        f"💰 ใช้เงิน  : {amount_thb:,.2f} ฿\n"
        f"🎯 มั่นใจ  : {confidence:.0%}\n"
        f"⏱️ เวลา   : {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_sell(symbol: str, price: float,
                pnl: float, win_rate: float) -> bool:
    pnl_icon = "📈 กำไร" if pnl >= 0 else "📉 ขาดทุน"
    sign     = "+" if pnl >= 0 else ""

    return send_line(
        f"🔴 𝗦𝗘𝗟𝗟 : {symbol}\n"
        f"───────────────\n"
        f"💵 ราคา  : {price:,.2f} ฿\n"
        f"{pnl_icon}   : {sign}{pnl:,.2f} ฿\n"
        f"🏆 Win  : {win_rate}%\n"
        f"⏱️ เวลา  : {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_stop_loss(symbol: str, entry: float,
                     current: float, loss_thb: float) -> bool:
    return send_line(
        f"⚠️ 𝗦𝗧𝗢𝗣-𝗟𝗢𝗦𝗦 : {symbol}\n"
        f"───────────────\n"
        f"🛒 ซื้อที่    : {entry:,.2f} ฿\n"
        f"🔻 ปัจจุบัน  : {current:,.2f} ฿\n"
        f"🩸 ขาดทุน  : {loss_thb:,.2f} ฿\n"
        f"⏱️ เวลา    : {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_take_profit(symbol: str, entry: float,
                       current: float, profit_thb: float) -> bool:
    gain_pct = (current - entry) / entry * 100 if entry else 0
    return send_line(
        f"🎯 𝗧𝗔𝗞𝗘-𝗣𝗥𝗢𝗙𝗜𝗧 : {symbol}\n"
        f"───────────────\n"
        f"🛒 ซื้อที่    : {entry:,.2f} ฿\n"
        f"🚀 ขายที่   : {current:,.2f} ฿  (+{gain_pct:.2f}%)\n"
        f"💰 กำไร    : +{profit_thb:,.2f} ฿\n"
        f"⏱️ เวลา    : {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_trailing_stop(symbol: str, entry: float, peak: float,
                         current: float, pnl_thb: float) -> bool:
    sign = "+" if pnl_thb >= 0 else ""
    drop = (peak - current) / peak * 100 if peak else 0
    return send_line(
        f"🔒 𝗧𝗥𝗔𝗜𝗟𝗜𝗡𝗚 𝗦𝗧𝗢𝗣 : {symbol}\n"
        f"───────────────\n"
        f"🛒 ซื้อที่    : {entry:,.2f} ฿\n"
        f"⛰️ Peak     : {peak:,.2f} ฿\n"
        f"📉 ปัจจุบัน  : {current:,.2f} ฿  (-{drop:.2f}% จาก peak)\n"
        f"💵 P&L     : {sign}{pnl_thb:,.2f} ฿\n"
        f"⏱️ เวลา    : {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_error(error: str) -> bool:
    return send_line(
        f"❌ 𝗘𝗥𝗥𝗢𝗥 𝗔𝗟𝗘𝗥𝗧\n"
        f"───────────────\n"
        f"💬 {error}\n"
        f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
    )


def notify_summary(summary: dict) -> bool:
    pnl_icon = "🟢" if summary["total_pnl"] >= 0 else "🔴"

    return send_line(
        f"📊 𝗗𝗔𝗜𝗟𝗬 𝗦𝗨𝗠𝗠𝗔𝗥𝗬\n"
        f"───────────────\n"
        f"🔄 เทรด    : {summary['total_trades']} ครั้ง\n"
        f"🏆 Win rate: {summary['win_rate']}%\n"
        f"{pnl_icon} P&L     : {summary['total_pnl']:+.2f} ฿\n"
        f"📅 เวลา    : {datetime.now().strftime('%d/%m %H:%M')}"
    )


# ========== Quick test ==========

if __name__ == "__main__":
    print("ทดสอบส่งข้อความผ่าน LINE Messaging API...")
    ok = send_line(
        f"🤖 Trade Me Plz — Test Notification\n"
        f"───────────────\n"
        f"⏱️ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print("✅ สำเร็จ" if ok else "❌ ล้มเหลว (ดู logs/notifications_failed.log)")
