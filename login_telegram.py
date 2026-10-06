# -*- coding: utf-8 -*-
import asyncio
import sys
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError
)

API_ID = 33946669
API_HASH = "d88d388e5810305e722af0cc61a3a80a"
SESSION_NAME = "session_master"

async def login():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()
    
    if await client.is_user_authorized():
        me = await client.get_me()
        print("\n" + "="*50)
        print("🎉 BẠN ĐÃ ĐĂNG NHẬP SẴN RỒI!")
        print(f"👤 Tài khoản: {me.first_name} (@{me.username or 'No Username'})")
        print(f"📱 SĐT: +{me.phone}")
        print("="*50)
        await client.disconnect()
        return

    print("\n" + "="*50)
    print("      HƯỚNG DẪN ĐĂNG NHẬP TELEGRAM AN TOÀN")
    print("="*50)
    print("⚠️ LƯU Ý QUAN TRỌNG:")
    print("1. Số điện thoại PHẢI có tiền tố +84 (Ví dụ: +84987654321)")
    print("2. Mã OTP sẽ được gửi vào APP TELEGRAM (Điện thoại hoặc PC), KHÔNG PHẢI QUA SMS SIM!")
    print("="*50)

    phone = input("\n👉 Nhập số điện thoại (Ví dụ +84912345678): ").strip()
    if not phone.startswith("+"):
        if phone.startswith("0"):
            phone = "+84" + phone[1:]
        elif phone.startswith("84"):
            phone = "+" + phone
        else:
            phone = "+84" + phone
    
    print(f"\n[*] Đang gửi yêu cầu mã OTP tới số: {phone} ...")
    try:
        sent_code = await client.send_code_request(phone)
        print("\n" + "-"*50)
        print("✅ YÊU CẦU ĐÃ GỬI THÀNH CÔNG!")
        print("📱 HÃY MỞ ỨNG DỤNG TELEGRAM TRÊN ĐIỆN THOẠI/PC:")
        print("👉 Tìm tin nhắn từ cuộc trò chuyện chính thức có tên 'Telegram'")
        print("👉 Lấy mã xác nhận 5 chữ số và nhập vào dưới đây:")
        print("-"*50)
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
    # Loại bỏ khoảng trắng hoặc ký tự lạ nếu có
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
    print("\n" + "="*50)
    print("🎉 ĐĂNG NHẬP THÀNH CÔNG RỰC RỠ!")
    print(f"👤 Chào mừng: {me.first_name} (@{me.username or 'No Username'})")
    print(f"📱 SĐT: +{me.phone}")
    print("💾 Đã lưu phiên đăng nhập vào file 'session_master.session'.")
    print("="*50)
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(login())
