# -*- coding: utf-8 -*-
"""
Script đăng nhập Telegram an toàn và chống khóa phiên (Lock-Free).
Sử dụng StringSession Telethon trong bộ nhớ (RAM), không gây xung đột khóa file SQLite
kể cả khi server.py và các luồng autoreg đang chạy song song.
"""

import asyncio
import os
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError
)

try:
    from telegram_auth import (
        get_telethon_session,
        save_session_string,
        get_string_session_str,
        DEFAULT_TELEGRAM_SLOT,
        STR_SESSION_FILE,
        SESSION_FILE
    )
except ImportError:
    get_telethon_session = None
    save_session_string = None
    get_string_session_str = None
    DEFAULT_TELEGRAM_SLOT = {}
    STR_SESSION_FILE = "session_master.string_session"
    SESSION_FILE = "session_master.session"

API_ID = 33946669
API_HASH = "d88d388e5810305e722af0cc61a3a80a"

async def login():
    # 1. Kiểm tra session hiện có (dùng in-memory StringSession để không lock SQLite)
    current_sess = get_telethon_session() if get_telethon_session else StringSession()
    client = TelegramClient(current_sess, API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print("\n" + "="*55)
        print("🎉 BẠN ĐÃ ĐĂNG NHẬP SẴN RỒI!")
        print(f"👤 Tài khoản: {me.first_name} {me.last_name or ''} (@{me.username or 'No Username'})")
        print(f"📱 SĐT: +{me.phone}")
        print("🔒 Trạng thái: Session In-Memory hoạt động ổn định (Không bị lock)")
        print("="*55)
        
        # Đảm bảo file session_master.string_session được lưu đồng bộ
        try:
            saved_str = client.session.save()
            if save_session_string:
                save_session_string(saved_str)
        except Exception:
            pass

        choice = input("\n👉 Bạn có muốn ĐĂNG NHẬP TÀI KHOẢN MỚI khác không? (y/N): ").strip().lower()
        if choice not in ['y', 'yes']:
            print("✅ Giữ nguyên phiên đăng nhập hiện tại. Đang thoát.")
            await client.disconnect()
            return
        
        # Nếu muốn đăng nhập lại tài khoản khác:
        await client.disconnect()

    print("\n" + "="*55)
    print("      HƯỚNG DẪN ĐĂNG NHẬP TELEGRAM AN TOÀN")
    print("="*55)
    print("⚠️ LƯU Ý QUAN TRỌNG:")
    print("1. Số điện thoại PHẢI có tiền tố +84 (Ví dụ: +84987654321)")
    print("2. Mã OTP sẽ được gửi vào APP TELEGRAM (Điện thoại hoặc PC), KHÔNG PHẢI QUA SMS SIM!")
    print("3. Cơ chế StringSession mới đảm bảo không bao giờ bị lỗi 'database is locked'.")
    print("="*55)

    phone = input("\n👉 Nhập số điện thoại (Ví dụ +84912345678): ").strip()
    if not phone.startswith("+"):
        if phone.startswith("0"):
            phone = "+84" + phone[1:]
        elif phone.startswith("84"):
            phone = "+" + phone
        else:
            phone = "+84" + phone

    # Dùng StringSession() mới hoàn toàn trong RAM
    new_sess = StringSession()
    client = TelegramClient(new_sess, API_ID, API_HASH)
    await client.connect()

    print(f"\n[*] Đang gửi yêu cầu mã OTP tới số: {phone} ...")
    try:
        sent_code = await client.send_code_request(phone)
        print("\n" + "-"*55)
        print("✅ YÊU CẦU ĐÃ GỬI THÀNH CÔNG!")
        print("📱 HÃY MỞ ỨNG DỤNG TELEGRAM TRÊN ĐIỆN THOẠI/PC:")
        print("👉 Tìm tin nhắn từ cuộc trò chuyện chính thức có tên 'Telegram'")
        print("👉 Lấy mã xác nhận 5 chữ số và nhập vào dưới đây:")
        print("-"*55)
    except PhoneNumberInvalidError:
        print("\n❌ Số điện thoại không hợp lệ! Vui lòng kiểm tra lại.")
        await client.disconnect()
        return
    except FloodWaitError as e:
        print(f"\n❌ Bạn bị Telegram tạm chặn do thao tác quá nhiều lần! Vui lòng chờ {e.seconds} giây.")
        await client.disconnect()
        return
    except Exception as e:
        print(f"\n❌ Lỗi khi gửi yêu cầu mã: {e}")
        await client.disconnect()
        return

    code = input("\n👉 Nhập mã xác nhận (OTP) 5 số từ Telegram: ").strip()
    code = code.replace(" ", "").replace("-", "")

    try:
        await client.sign_in(phone, code, phone_code_hash=sent_code.phone_code_hash)
    except SessionPasswordNeededError:
        print("\n🔒 Tài khoản của bạn có cài MẬT KHẨU 2 LỚP (Two-Step Verification)!")
        password = input("👉 Nhập mật khẩu 2FA của bạn: ").strip()
        try:
            await client.sign_in(password=password)
        except Exception as e:
            print(f"\n❌ Mật khẩu 2FA không đúng: {e}")
            await client.disconnect()
            return
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
        print(f"\n❌ Mã xác nhận không đúng hoặc đã hết hạn: {e}")
        await client.disconnect()
        return
    except Exception as e:
        print(f"\n❌ Đăng nhập thất bại: {e}")
        await client.disconnect()
        return

    me = await client.get_me()
    saved_key = client.session.save()
    if save_session_string:
        save_session_string(saved_key)
    else:
        try:
            with open("session_master.string_session", "w", encoding="utf-8") as f:
                f.write(saved_key)
        except Exception:
            pass

    print("\n" + "="*55)
    print("🎉 ĐĂNG NHẬP THÀNH CÔNG RỰC RỠ!")
    print(f"👤 Chào mừng: {me.first_name} {me.last_name or ''} (@{me.username or 'No Username'})")
    print(f"📱 SĐT: +{me.phone}")
    print("💾 Đã lưu session vào 'session_master.string_session' (Chống khóa 100%)")
    print("="*55)
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(login())
