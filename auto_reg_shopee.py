# -*- coding: utf-8 -*-
"""
HỆ THỐNG TỰ ĐỘNG ĐIỀU PHỐI TẠO TÀI KHOẢN SHOPEE (ORCHESTRATOR BRIDGE)
1. Thuê SĐT từ API CMSNPA (otpapi.cmsnpa.com)
2. Bơm lệnh /regsdt vào @sfast_main_bot
3. Bắt OTP real-time từ API + @simclonenpa_bot
4. Bơm lệnh /otp vào @sfast_main_bot
5. Tự động lưu Account, Cookie SPC_F, SPC_ST vào file
"""

import asyncio
import re
import os
import sys
import json
import time
import aiohttp
from datetime import datetime
from telethon import TelegramClient, events

# ========================================================
# CẤU HÌNH HỆ THỐNG
# ========================================================
API_ID = 33946669
API_HASH = "d88d388e5810305e722af0cc61a3a80a"
SESSION_NAME = "session_master"

CMSNPA_KEY = "cmsnpa_Mud47JUcA1fYF8mTSmpABUoNqZvh_fUZjG96oVatiDw"
CMSNPA_BASE = "https://otpapi.cmsnpa.com"

# Các gói Shopee trên CMSNPA
SERVICES = {
    "1": {"id": "dyn_ab1eb87836", "name": "Shopee trâu (3.200đ) [Khuyên dùng]"},
    "2": {"id": "dyn_d8f753cd7c", "name": "Shopee call (2.000đ)"},
    "3": {"id": "dyn_a6903d75a0", "name": "Shopee gà (3.500đ)"},
    "4": {"id": "dyn_a3a3ad627f", "name": "Shopee bò (3.500đ)"}
}

BOT_A = "@simclonenpa_bot"
BOT_B = "@sfast_main_bot"

FILE_TXT = "accounts_reg.txt"
FILE_JSON = "accounts_reg.json"
PROXY_CONFIG_FILE = "proxy_config.json"

try:
    from autoreg_manager import get_kiotproxy_ip
except Exception:
    get_kiotproxy_ip = None

try:
    from telegram_auth import get_telethon_session
    _sess = get_telethon_session()
except Exception:
    _sess = SESSION_NAME

client = TelegramClient(_sess, API_ID, API_HASH)

# ========================================================
# HÀM XỬ LÝ API CMSNPA
# ========================================================
async def get_balance(session):
    """Kiểm tra số dư API"""
    headers = {"Authorization": f"Bearer {CMSNPA_KEY}"}
    try:
        async with session.get(f"{CMSNPA_BASE}/api/v1/balance", headers=headers, timeout=10) as r:
            data = await r.json()
            if data.get("ok"):
                return data.get("credits", 0)
    except Exception as e:
        print(f"[!] Lỗi kiểm tra số dư: {e}")
    return None

async def rent_phone_number(session, server_id):
    """Thuê số điện thoại Shopee qua API"""
    headers = {
        "Authorization": f"Bearer {CMSNPA_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"server": server_id}
    try:
        async with session.post(f"{CMSNPA_BASE}/api/v1/get_number", headers=headers, json=payload, timeout=15) as r:
            data = await r.json()
            if data.get("ResponseCode") == 0:
                res = data.get("Result", {})
                return res.get("Id"), res.get("Number")
            else:
                print(f"[!] Thuê số thất bại: {data.get('Msg', 'Không rõ nguyên nhân')}")
    except Exception as e:
        print(f"[!] Lỗi kết nối thuê số: {e}")
    return None, None

async def check_otp_api(session, rental_id):
    """Hỏi OTP từ API"""
    headers = {
        "Authorization": f"Bearer {CMSNPA_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"id": str(rental_id)}
    try:
        async with session.post(f"{CMSNPA_BASE}/api/v1/check_code", headers=headers, json=payload, timeout=10) as r:
            data = await r.json()
            # Kiểm tra các cấu trúc trả về khả dĩ
            if data.get("ResponseCode") == 0:
                res = data.get("Result", {})
                code = res.get("Code") or res.get("Otp") or res.get("code")
                if code:
                    return str(code).strip()
            # Hoặc định dạng {"ok": true, "code": "..."}
            if data.get("code"):
                return str(data.get("code")).strip()
    except Exception:
        pass
    return None

# ========================================================
# HÀM LƯU TÀI KHOẢN
# ========================================================
def save_account_data(account_raw, spc_st, phone):
    """Lưu tài khoản thành công vào txt và json"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Ghi file text
    with open(FILE_TXT, "a", encoding="utf-8") as f:
        f.write(f"[{now}] {account_raw}\n")
        if spc_st:
            f.write(f"  SPC_ST: {spc_st}\n")
        f.write("-" * 60 + "\n")

    # 2. Ghi file JSON
    existing = []
    if os.path.exists(FILE_JSON):
        try:
            with open(FILE_JSON, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    
    existing.append({
        "time": now,
        "phone": phone,
        "account_raw": account_raw,
        "spc_st": spc_st
    })
    
    with open(FILE_JSON, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

async def cancel_pending_session_on_bot_b():
    """Tìm nút '❌ Hủy Tạo Acc' trên Bot B và bấm hủy"""
    try:
        msgs = await client.get_messages(BOT_B, limit=6)
        for m in msgs:
            if m.buttons:
                for row in m.buttons:
                    for btn in row:
                        if "hủy" in btn.text.lower() or "cancel" in btn.text.lower():
                            print(f"\n[🛑] Đang bấm nút '{btn.text}' để hủy phiên đang chờ trên Bot B...")
                            await btn.click()
                            await asyncio.sleep(2.5)
                            print("[✅] Đã hủy phiên reg trên Bot B thành công!")
                            return True
    except Exception as e:
        print(f"[!] Lỗi khi bấm hủy trên Bot B: {e}")
    return False

async def click_resend_otp_on_bot_b():
    """Tìm nút '📲 Gửi Lại Mã' trên Bot B và bấm gửi lại"""
    try:
        msgs = await client.get_messages(BOT_B, limit=6)
        for m in msgs:
            if m.buttons:
                for row in m.buttons:
                    for btn in row:
                        if "gửi lại" in btn.text.lower() or "resend" in btn.text.lower():
                            print(f"\n[📲] Đang bấm nút '{btn.text}' trên Bot B để gửi lại OTP...")
                            await btn.click()
                            await asyncio.sleep(2)
                            print("[✅] Đã bấm 'Gửi Lại Mã' thành công trên Bot B!")
                            return True
    except Exception as e:
        print(f"[!] Lỗi khi bấm gửi lại mã trên Bot B: {e}")
    return False

# ========================================================
# LUỒNG CHẠY TẠO 1 TÀI KHOẢN (REG CYCLE)
# ========================================================
async def run_single_reg(server_id, kiotproxy_key=""):
    print("\n" + "=" * 60)
    print(f"🚀 BẮT ĐẦU PHIÊN TẠO TÀI KHOẢN SHOPEE...")
    print("=" * 60)

    # Dọn dẹp phiên cũ trên Bot B nếu có
    await cancel_pending_session_on_bot_b()

    async with aiohttp.ClientSession() as http:
        # Bước 1: Kiểm tra số dư
        bal = await get_balance(http)
        if bal is not None:
            print(f"💰 Số dư API CMSNPA hiện tại: {bal:,} đ")
            if bal < 2000:
                print("❌ Số dư không đủ để thuê số! Vui lòng nạp thêm tiền.")
                return False

        # Bước 2: Gọi API lấy số điện thoại
        print(f"[*] Đang yêu cầu thuê số điện thoại Shopee...")
        rental_id, phone = await rent_phone_number(http, server_id)
        if not phone:
            print("❌ Không lấy được số điện thoại. Kết thúc phiên.")
            return False

        # Chuẩn hóa SĐT về dạng 10 số (0...)
        digits = re.sub(r'\D', '', str(phone).strip())
        if digits.startswith("840"):
            phone_clean = "0" + digits[3:]
        elif digits.startswith("84"):
            phone_clean = "0" + digits[2:]
        elif not digits.startswith("0"):
            phone_clean = "0" + digits
        else:
            phone_clean = digits

        print(f"✅ Thuê số thành công!")
        print(f"📱 SĐT: {phone_clean} (Mã phiên thuê: {rental_id})")

        # Bước 3: Xử lý Proxy xoay KiotProxy (nếu có cấu hình)
        proxy_assigned = None
        if kiotproxy_key and get_kiotproxy_ip:
            print("[*] 🌐 Đang gọi KiotProxy xoay IP phiên mới...")
            p_str, p_note, p_err = get_kiotproxy_ip(kiotproxy_key, rotate=True)
            if p_str:
                proxy_assigned = p_str
                print(f"[✅] KiotProxy đã cấp IP: {p_str} ({p_note}) => Gói /regfull (500đ/acc)")
            else:
                print(f"[⚠️] Không lấy được KiotProxy ({p_err}). Dùng IP mặc định của bot (/regsdt)...")

        # Bước 4: Gửi lệnh Reg sang @sfast_main_bot
        if proxy_assigned:
            reg_cmd = f"/regfull {phone_clean}|{proxy_assigned}"
        else:
            reg_cmd = f"/regsdt {phone_clean}"

        print(f"[*] Đang gửi lệnh sang Bot B (@sfast_main_bot): {reg_cmd}")
        sent_msg = await client.send_message(BOT_B, reg_cmd)
        sent_msg_id = sent_msg.id

        # Kiểm tra phản hồi khoa học từ Bot B (Chỉ đọc tin sinh ra SAU tin nhắn vừa gửi)
        print("[*] Đang đợi Bot B xác nhận tiếp nhận đơn...")
        is_accepted = False
        is_rejected = False
        check_start = time.time()

        while time.time() - check_start < 14:
            await asyncio.sleep(2)
            recent_msgs = await client.get_messages(BOT_B, limit=5)
            new_replies = [m for m in recent_msgs if m.id > sent_msg_id and not m.out]

            for m in new_replies:
                txt = (m.text or "").lower()
                if "đã có tài khoản shopee" in txt or "không thể lấy lại" in txt or "dùng sđt khác" in txt:
                    print(f"❌ Bot B từ chối: SĐT {phone_clean} ĐÃ CÓ NICK SHOPEE!")
                    is_rejected = True
                    break
                elif "không hợp lệ" in txt:
                    print(f"❌ Bot B từ chối: SĐT {phone_clean} KHÔNG HỢP LỆ!")
                    is_rejected = True
                    break
                if "đã đưa vào hàng đợi" in txt or "đang tạo account" in txt or "mã phiên" in txt or "gửi mã otp" in txt:
                    print(f"✅ Bot B đã tiếp nhận đơn reg SĐT {phone_clean} thành công!")
                    is_accepted = True
                    break

            if is_rejected or is_accepted:
                break

        if is_rejected:
            print(f"🔄 Bỏ qua số {phone_clean}. Bên A sẽ tự hoàn tiền sau 300s. Đang chuyển sang thuê số mới...")
            await asyncio.sleep(3)
            return False

        if not is_accepted:
            print("[*] Bot B đang xử lý ngầm. Tiếp tục chuyển sang bước chờ OTP.")

        # Bước 4: Lắng nghe OTP song song (Kênh 1: API Polling, Kênh 2: Tin nhắn @simclonenpa_bot)
        # Chờ trọn vẹn chu kỳ 300s của nhà mạng bên A (tối đa 310s)
        print(f"⏳ Đang chờ OTP cho số {phone_clean} (Theo chu kỳ 300s của bên A)...")
        otp_found = None
        is_expired = False
        start_wait = time.time()
        timeout = 310

        captured_otp = {"code": None}
        clean_num = phone_clean.lstrip("0")

        @client.on(events.NewMessage(chats=BOT_A))
        async def bot_a_handler(event):
            nonlocal is_expired
            text = event.raw_text
            if "Đã nhận được OTP" in text:
                if clean_num in text or "Số thuê" not in text:
                    match = re.search(r'Mã OTP:\s*\**(\d{4,8})\**', text)
                    if match:
                        captured_otp["code"] = match.group(1)
            elif "Hoàn tiền thuê số" in text or "Không nhận được OTP" in text:
                if clean_num in text:
                    is_expired = True

        resend_clicked = False

        while time.time() - start_wait < timeout:
            # Tự động bấm '📲 Gửi Lại Mã' trên Bot B sau 100 giây nếu chưa có OTP
            elapsed_wait = time.time() - start_wait
            if elapsed_wait >= 100 and not resend_clicked:
                resend_clicked = True
                print(f"\n[⏰] Đã qua 100 giây chưa có OTP. Đang bấm nút '📲 Gửi Lại Mã' trên Bot B...")
                await click_resend_otp_on_bot_b()

            # 1. Đọc trực tiếp hộp thư Bot A trên Telegram (chống miss event)
            try:
                msgs_a = await client.get_messages(BOT_A, limit=5)
                for m in msgs_a:
                    if m.id > sent_msg_id and not m.out:
                        txt_a = m.text or ""
                        if "Đã nhận được OTP" in txt_a:
                            if clean_num in txt_a or "số thuê" not in txt_a.lower():
                                match = re.search(r'Mã OTP:\s*\**(\d{4,8})\**', txt_a)
                                if match:
                                    otp_found = match.group(1)
                                    print(f"\n⚡ Bắt được OTP từ Bot A (@simclonenpa_bot): {otp_found}")
                                    break
                        elif "Hoàn tiền thuê số" in txt_a or "Không nhận được OTP" in txt_a:
                            if clean_num in txt_a:
                                is_expired = True
                                break
            except Exception:
                pass

            if otp_found:
                break

            if is_expired:
                print(f"\n⚠️ Bot A (@simclonenpa_bot) ĐÃ BÁO: Sim {phone_clean} hết hạn & hoàn tiền!")
                break

            if captured_otp["code"]:
                otp_found = captured_otp["code"]
                print(f"\n⚡ Bắt được OTP từ Bot A (@simclonenpa_bot): {otp_found}")
                break

            # 2. Hỏi qua API CMSNPA
            api_otp = await check_otp_api(http, rental_id)
            if api_otp:
                otp_found = api_otp
                print(f"\n⚡ Bắt được OTP từ API CMSNPA: {otp_found}")
                break

            await asyncio.sleep(3)
            print(".", end="", flush=True)

        # Gỡ bỏ event handler bot A sau khi xong
        client.remove_event_handler(bot_a_handler)

        if not otp_found:
            print(f"\n🛑 Sim {phone_clean} đã hết hạn/hoàn tiền xong.")
            print(f"👉 Đang bấm '❌ Hủy Tạo Acc' bên Bot B (@sfast_main_bot)...")
            await cancel_pending_session_on_bot_b()
            print("⏳ Chờ 5 giây dọn dẹp hàng đợi trước khi bắt đầu phiên mới...")
            await asyncio.sleep(5)
            return False

        # Bước 5: Bơm OTP vào @sfast_main_bot
        otp_cmd = f"/otp {otp_found}"
        print(f"[*] Đang gửi mã OTP vào Bot B: {otp_cmd}")
        sent_otp_msg = await client.send_message(BOT_B, otp_cmd)
        sent_otp_id = sent_otp_msg.id

        # Bước 6: Lắng nghe Bot B trả về kết quả (Chỉ xét tin nhắn sinh ra SAU KHI GỬI /otp)
        print(f"⏳ Đang chờ Bot B hoàn tất tạo tài khoản...")
        account_done = False
        start_result_wait = time.time()

        while time.time() - start_result_wait < 90:
            await asyncio.sleep(3)
            msgs = await client.get_messages(BOT_B, limit=10)
            new_msgs = [m for m in msgs if m.id > sent_otp_id and not m.out]
            for m in new_msgs:
                txt = m.text or ""
                if "TẠO ACCOUNT THÀNH CÔNG" in txt:
                    clean_txt = txt.replace("`", "").strip()
                    print("\n" + "🎉" * 20)
                    print("✅ TẠO ACCOUNT SHOPEE THÀNH CÔNG RỰC RỠ!")
                    print("=" * 60)
                    print(clean_txt)
                    print("=" * 60)

                    acc_match = re.search(r'([a-zA-Z0-9_\-\.]+)\|([^\|\n]+)\|(\d+)\|(SPC_F=[^\s\n\r]+)', clean_txt)
                    spc_st_match = re.search(r'(SPC_ST=[^\s\n\r]+)', clean_txt)

                    acc_raw = acc_match.group(0) if acc_match else f"Acc_{phone_clean}|Shopee"
                    spc_st = spc_st_match.group(1) if spc_st_match else ""

                    save_account_data(acc_raw, spc_st, phone_clean)
                    print(f"💾 Đã lưu thông tin tài khoản vào file: {FILE_TXT} và {FILE_JSON}")
                    account_done = True
                    break
                elif "mã otp nhập không đúng" in txt.lower() or "hết lượt thử" in txt.lower():
                    print(f"\n❌ Bot B báo thất bại: {txt}")
                    return False

            if account_done:
                return True

        print("\n⚠️ Không nhận được phản hồi kết thúc từ Bot B (có thể cần kiểm tra trực tiếp Telegram).")
        return False

# ========================================================
# HÀM CHÍNH (MAIN MENU)
# ========================================================
async def main():
    await client.start()
    me = await client.get_me()
    print("=" * 60)
    print(f"🤖 HỆ THỐNG ĐIỀU PHỐI REG SHOPEE TỰ ĐỘNG (TELEGRAM BRIDGE)")
    print(f"👤 Đang chạy bằng tài khoản: {me.first_name} (+{me.phone})")
    print("=" * 60)

    print("\nChọn loại Server Shopee thuê số:")
    for k, v in SERVICES.items():
        print(f"  [{k}] {v['name']}")
    
    choice_srv = input("👉 Nhập số (1-4, mặc định là 1): ").strip()
    if choice_srv not in SERVICES:
        choice_srv = "1"
    selected_srv = SERVICES[choice_srv]
    print(f"✅ Đã chọn gói: {selected_srv['name']}")

    # Cấu hình KiotProxy
    saved_key = ""
    if os.path.exists(PROXY_CONFIG_FILE):
        try:
            with open(PROXY_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved_key = json.load(f).get("key", "")
        except Exception:
            pass

    use_kp = input("\n👉 Có muốn dùng KiotProxy xoay IP không? (/regfull - 500đ) (y/n, mặc định: n): ").strip().lower()
    kiotproxy_key = ""
    if use_kp in ["y", "yes", "1"]:
        prompt_kp = f"👉 Nhập Key KiotProxy (Enter để dùng key đã lưu: {saved_key[:8]}...): " if saved_key else "👉 Nhập Key KiotProxy: "
        entered_key = input(prompt_kp).strip()
        kiotproxy_key = entered_key if entered_key else saved_key
        if kiotproxy_key:
            print(f"✅ Đã kích hoạt KiotProxy xoay IP (/regfull - 500đ/acc)")
        else:
            print("⚠️ Không có key. Tiếp tục chạy với IP mặc định của bot (/regsdt - 700đ/acc)")

    print("\nChọn chế độ chạy:")
    print("  [1] Chạy thử 1 tài khoản")
    print("  [2] Chạy tự động liên tục N tài khoản")
    mode = input("👉 Nhập lựa chọn (1 hoặc 2, mặc định là 1): ").strip()

    if mode == "2":
        count_str = input("👉 Bạn muốn reg bao nhiêu tài khoản?: ").strip()
        try:
            total_count = int(count_str)
        except ValueError:
            total_count = 1
        
        delay_str = input("👉 Thời gian nghỉ giữa các lần (giây, mặc định 10): ").strip()
        try:
            delay_sec = int(delay_str)
        except ValueError:
            delay_sec = 10

        success = 0
        for i in range(1, total_count + 1):
            print(f"\n>>> [TIẾN ĐỘ: {i}/{total_count}] <<<")
            res = await run_single_reg(selected_srv["id"], kiotproxy_key)
            if res:
                success += 1
            if i < total_count:
                print(f"💤 Nghỉ {delay_sec} giây trước khi chạy lượt tiếp theo...")
                await asyncio.sleep(delay_sec)

        print("\n" + "=" * 60)
        print(f"🏁 HOÀN TẤT CHIẾN DỊCH! Thành công: {success}/{total_count} tài khoản.")
        print(f"📂 Xem danh sách tài khoản tại file: {FILE_TXT}")
        print("=" * 60)
    else:
        await run_single_reg(selected_srv["id"], kiotproxy_key)

if __name__ == "__main__":
    client.loop.run_until_complete(main())
