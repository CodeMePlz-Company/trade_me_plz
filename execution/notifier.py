import requests
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_TARGET_ID = os.getenv("LINE_TARGET_ID", "") 

def send_line(message: str) -> bool:
    """ส่งแจ้งเตือนผ่าน LINE Messaging API (Push Message)"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_TARGET_ID:
        print(f"🚫 [NOTIFY] ขาด LINE_CHANNEL_ACCESS_TOKEN หรือ LINE_TARGET_ID\nข้อความ: {message}")
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    
    payload = {
        "to": LINE_TARGET_ID,
        "messages": [
            {
                "type": "text",
                "text": message
            }
        ]
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=5)
        r.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"🚫 [NOTIFY] แจ้งเตือนล้มเหลว: {e}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"ℹ️ สาเหตุ: {e.response.text}")
        return False

def notify_buy(symbol: str, price: float, amount_thb: float, confidence: float):
    send_line(
        f"🟢 𝗕𝗨𝗬 : {symbol}\n"
        f"───────────────\n"
        f"💵 ราคา   : {price:,.2f} ฿\n"
        f"💰 ใช้เงิน  : {amount_thb:,.2f} ฿\n"
        f"🎯 มั่นใจ  : {confidence:.0%}\n"
        f"⏱️ เวลา   : {datetime.now().strftime('%H:%M:%S')}"
    )

def notify_sell(symbol: str, price: float, pnl: float, win_rate: float):
    # เปลี่ยนไอคอนและข้อความตามกำไร/ขาดทุน
    pnl_icon = "📈 กำไร" if pnl >= 0 else "📉 ขาดทุน"
    sign = "+" if pnl >= 0 else ""
    
    send_line(
        f"🔴 𝗦𝗘𝗟𝗟 : {symbol}\n"
        f"───────────────\n"
        f"💵 ราคา  : {price:,.2f} ฿\n"
        f"{pnl_icon}   : {sign}{pnl:,.2f} ฿\n"
        f"🏆 Win  : {win_rate}%\n"
        f"⏱️ เวลา  : {datetime.now().strftime('%H:%M:%S')}"
    )

def notify_stop_loss(symbol: str, entry: float, current: float, loss_thb: float):
    send_line(
        f"⚠️ 𝗦𝗧𝗢𝗣-𝗟𝗢𝗦𝗦 : {symbol}\n"
        f"───────────────\n"
        f"🛒 ซื้อที่    : {entry:,.2f} ฿\n"
        f"🔻 ปัจจุบัน  : {current:,.2f} ฿\n"
        f"🩸 ขาดทุน  : {loss_thb:,.2f} ฿\n"
        f"⏱️ เวลา    : {datetime.now().strftime('%H:%M:%S')}"
    )

def notify_error(error: str):
    send_line(
        f"❌ 𝗘𝗥𝗥𝗢𝗥 𝗔𝗟𝗘𝗥𝗧\n"
        f"───────────────\n"
        f"💬 {error}\n"
        f"⏱️ {datetime.now().strftime('%H:%M:%S')}"
    )

def notify_summary(summary: dict):
    # ปรับสีกำไร/ขาดทุนรวม
    pnl_icon = "🟢" if summary['total_pnl'] >= 0 else "🔴"
    
    send_line(
        f"📊 𝗗𝗔𝗜𝗟𝗬 𝗦𝗨𝗠𝗠𝗔𝗥𝗬\n"
        f"───────────────\n"
        f"🔄 เทรด    : {summary['total_trades']} ครั้ง\n"
        f"🏆 Win rate: {summary['win_rate']}%\n"
        f"{pnl_icon} P&L     : {summary['total_pnl']:+.2f} ฿\n"
        f"📅 เวลา    : {datetime.now().strftime('%d/%m %H:%M')}"
    )