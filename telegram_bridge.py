# -*- coding: utf-8 -*-
"""
HỆ THỐNG ĐIỀU PHỐI TỰ ĐỘNG TELEGRAM (ORCHESTRATOR BRIDGE)
Kết nối: Bên A (@simclonenpa_bot) <---> Bot B (@sfast_main_bot)
"""

import asyncio
import re
import sys
from telethon import TelegramClient, events

# ==========================================
# CẤU HÌNH THÔNG TIN TELEGRAM
# ==========================================
API_ID = 33946669
API_HASH = "d88d388e5810305e722af0cc61a3a80a"
SESSION_NAME = "session_master"

BOT_A = "@simclonenpa_bot"   # Bot cho thuê SIM / lấy OTP
BOT_B = "@sfast_main_bot"    # Bot reg tài khoản

try:
    from telegram_auth import get_telethon_session
    _sess = get_telethon_session()
except Exception:
    _sess = SESSION_NAME

# Khởi tạo Telegram Client (Lock-free in-memory session)
client = TelegramClient(_sess, API_ID, API_HASH)

def extract_otp(text):
    """Hàm regex trích xuất mã OTP gồm 4 - 8 chữ số trong tin nhắn"""
    # Tìm chuỗi 4 - 8 số
    match = re.search(r'\b\d{4,8}\b', text)
    if match:
        return match.group(0)
    return None

def extract_phone(text):
    """Hàm trích xuất số điện thoại (bắt đầu bằng 0 hoặc 84)"""
    match = re.search(r'(\+?84|0)[3|5|7|8|9][0-9]{8}', text)
    if match:
        return match.group(0)
    return None

async def test_connection():
    """Kiểm tra kết nối và thông tin tài khoản đang đăng nhập"""
    me = await client.get_me()
    print("=" * 60)
    print(f"✅ ĐÃ KẾT NỐI TELEGRAM THÀNH CÔNG!")
    print(f"👤 Tài khoản: {me.first_name} (@{me.username or 'Không có username'})")
    print(f"📱 SĐT: +{me.phone}")
    print("=" * 60)

async def test_chat_with_bots():
    """Hàm kiểm tra gửi tin nhắn và đọc phản hồi từ 2 bot"""
    print("\n[1] Thử gửi tin nhắn kiểm tra tới Bot B (@sfast_main_bot)...")
    try:
        async with client.conversation(BOT_B, timeout=30) as conv:
            await conv.send_message("/start")
            reply = await conv.get_response()
            print(f"👉 Phản hồi từ Bot B:\n{reply.text}\n")
    except Exception as e:
        print(f"⚠️ Chưa nhận được phản hồi từ Bot B: {e}")

    print("\n[2] Thử gửi tin nhắn kiểm tra tới Bot A (@simclonenpa_bot)...")
    try:
        async with client.conversation(BOT_A, timeout=30) as conv:
            await conv.send_message("/start")
            reply = await conv.get_response()
            print(f"👉 Phản hồi từ Bot A:\n{reply.text}\n")
    except Exception as e:
        print(f"⚠️ Chưa nhận được phản hồi từ Bot A: {e}")

async def main():
    # 1. Bắt đầu phiên đăng nhập
    await client.start()
    await test_connection()
    
    print("\n[?] Bạn muốn làm gì?")
    print("1: Test gửi tin nhắn /start tới cả 2 bot để xem phản hồi")
    print("2: Lắng nghe tin nhắn trực tiếp real-time từ 2 bot")
    
    choice = input("Nhập lựa chọn (1 hoặc 2, mặc định là 1): ").strip()
    if choice == "2":
        print("\n[*] Đang bật chế độ lắng nghe tin nhắn... (Nhấn Ctrl+C để dừng)")
        @client.on(events.NewMessage(chats=[BOT_A, BOT_B]))
        async def handler(event):
            sender = await event.get_sender()
            print(f"\n📩 [Tin nhắn mới từ @{sender.username}]:\n{event.raw_text}")
        await client.run_until_disconnected()
    else:
        await test_chat_with_bots()

if __name__ == "__main__":
    client.loop.run_until_complete(main())
