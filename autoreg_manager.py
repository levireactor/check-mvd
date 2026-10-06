# -*- coding: utf-8 -*-
"""
MODULE QUẢN LÝ TIẾN TRÌNH AUTO REG SHOPEE CHẠY NỀN
Phục vụ API cho Web UI & Tích hợp KiotProxy xoay IP
"""

import asyncio
import re
import os
import json
import time
import threading
from datetime import datetime
import urllib.request
import urllib.error
import aiohttp
from telethon import TelegramClient, events

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
FILE_TXT = os.path.join(DIRECTORY, "accounts_reg.txt")
FILE_JSON = os.path.join(DIRECTORY, "accounts_reg.json")
PROXY_CONFIG_FILE = os.path.join(DIRECTORY, "proxy_config.json")
SESSION_NAME = os.path.join(DIRECTORY, "session_master")

API_ID = 33946669
API_HASH = "d88d388e5810305e722af0cc61a3a80a"
CMSNPA_KEY = "cmsnpa_Mud47JUcA1fYF8mTSmpABUoNqZvh_fUZjG96oVatiDw"
CMSNPA_BASE = "https://otpapi.cmsnpa.com"

def get_kiotproxy_ip(key, rotate=True):
    """
    Gọi KiotProxy API để lấy IP xoay dạng ip:port hoặc ip:port:user:pass.
    Trả về tuple: (proxy_str, note_str, err_str)
    """
    if not key or not str(key).strip():
        return None, "", "Chưa nhập Key KiotProxy"
    
    k = str(key).strip()
    url_base = "https://api.kiotproxy.com/api/public/proxies"
    headers = {"Content-Type": "application/json", "User-Agent": "ShopeeTracker/4.2"}

    def _parse_proxy(d):
        if not d or not isinstance(d, dict):
            return None
        http_val = d.get("http")
        if http_val:
            return str(http_val).replace("http://", "").replace("https://", "").strip()
        host = d.get("host")
        port = d.get("httpPort")
        user = d.get("proxyUser")
        pwd = d.get("proxyPass")
        if host and port:
            if user and pwd:
                return f"{host}:{port}:{user}:{pwd}"
            return f"{host}:{port}"
        return None

    # 1. Thử xoay IP mới nếu rotate=True
    if rotate:
        try:
            req = urllib.request.Request(
                f"{url_base}/get-new",
                data=json.dumps({"keyValue": k}).encode("utf-8"),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                res = json.loads(r.read().decode("utf-8"))
                if res.get("success") and res.get("data"):
                    p_str = _parse_proxy(res["data"])
                    if p_str:
                        return p_str, "IP mới vừa xoay", None
        except urllib.error.HTTPError:
            pass
        except Exception:
            pass

    # 2. Lấy IP hiện tại nếu get-new chưa tới giờ xoay hoặc xoay thất bại
    try:
        req = urllib.request.Request(
            f"{url_base}/get-current",
            data=json.dumps({"keyValue": k}).encode("utf-8"),
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            res = json.loads(r.read().decode("utf-8"))
            if res.get("success") and res.get("data"):
                p_str = _parse_proxy(res["data"])
                if p_str:
                    return p_str, "IP hiện tại còn hạn", None
                return None, "", "Không có định dạng IP hợp lệ"
            return None, "", res.get("message", "Không lấy được IP")
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            return None, "", err_data.get("message", f"HTTP {e.code}")
        except Exception:
            return None, "", f"HTTP {e.code}"
    except Exception as e:
        return None, "", str(e)

BOT_A = "@simclonenpa_bot"
BOT_B = "@sfast_main_bot"

SERVICES = {
    "dyn_ab1eb87836": {"name": "Shopee trâu (3.200đ) [Khuyên dùng]", "price": 3200},
    "dyn_d8f753cd7c": {"name": "Shopee call (2.000đ)", "price": 2000},
    "dyn_a6903d75a0": {"name": "Shopee gà (3.500đ)", "price": 3500},
    "dyn_a3a3ad627f": {"name": "Shopee bò (3.500đ)", "price": 3500}
}

try:
    from telegram_auth import tg_auth_mgr
except Exception as _tga_err:
    tg_auth_mgr = None

def get_telegram_account_info(force_refresh=False):
    """Lấy thông tin tài khoản Telegram đang đăng nhập từ tg_auth_mgr"""
    if tg_auth_mgr:
        return tg_auth_mgr.get_info(force_refresh=force_refresh)
    return {
        "connected": False,
        "name": "Chưa kết nối",
        "phone": "",
        "username": ""
    }

class AutoRegManager:
    def __init__(self):
        self.is_running = False
        self.should_stop = False
        self.current_step = "IDLE"  # IDLE, ROTATING_PROXY, RENTING_PHONE, SENDING_REG, WAITING_OTP, SENDING_OTP, WAITING_RESULT
        self.kiotproxy_key = ""
        self.use_proxy = False
        self.last_proxy = None
        self.stats = {
            "total_requested": 0,
            "success": 0,
            "failed": 0,
            "total_spent": 0,
            "current_index": 0
        }
        self.logs = []
        self.max_logs = 200
        self.thread = None
        self.lock = threading.Lock()

    def log(self, text, level="info"):
        now_str = datetime.now().strftime("%H:%M:%S")
        entry = {
            "time": now_str,
            "text": text,
            "level": level # info, success, warning, error, otp
        }
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > self.max_logs:
                self.logs.pop(0)
        print(f"[{now_str}] [{level.upper()}] {text}")

    def get_status(self):
        with self.lock:
            return {
                "is_running": self.is_running,
                "current_step": self.current_step,
                "kiotproxy_key": self.kiotproxy_key,
                "use_proxy": self.use_proxy,
                "last_proxy": self.last_proxy,
                "stats": dict(self.stats),
                "logs": list(self.logs[-50:])
            }

    def get_accounts(self):
        if not os.path.exists(FILE_JSON):
            return []
        try:
            with open(FILE_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def clear_accounts(self):
        with open(FILE_JSON, "w", encoding="utf-8") as f:
            json.dump([], f)
        if os.path.exists(FILE_TXT):
            with open(FILE_TXT, "w", encoding="utf-8") as f:
                f.write("")
        return True

    def save_account_record(self, account_raw, spc_st, phone):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(FILE_TXT, "a", encoding="utf-8") as f:
            f.write(f"[{now}] {account_raw}\n")
            if spc_st:
                f.write(f"  SPC_ST: {spc_st}\n")
            f.write("-" * 60 + "\n")

        existing = self.get_accounts()
        existing.insert(0, {
            "id": str(int(time.time() * 1000)),
            "time": now,
            "phone": phone,
            "account_raw": account_raw,
            "spc_st": spc_st
        })
        with open(FILE_JSON, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    def start(self, server_id="dyn_ab1eb87836", count=1, delay=10, kiotproxy_key="", use_proxy=False):
        if self.is_running:
            return False, "Tiến trình đang chạy!"
        self.should_stop = False
        self.is_running = True
        self.current_step = "STARTING"
        self.kiotproxy_key = str(kiotproxy_key).strip()
        self.use_proxy = bool(use_proxy and self.kiotproxy_key)
        self.last_proxy = None
        self.stats = {
            "total_requested": count,
            "success": 0,
            "failed": 0,
            "total_spent": 0,
            "current_index": 0
        }
        
        proxy_desc = f"Kèm KiotProxy xoay IP (/regfull - 500đ/acc)" if self.use_proxy else "Dùng IP Bot (/regsdt - 700đ/acc)"
        self.log(f"Bắt đầu chiến dịch tạo {count} tài khoản (Gói: {SERVICES.get(server_id, {}).get('name', server_id)} | {proxy_desc})", "info")
        
        self.thread = threading.Thread(
            target=self._worker_thread,
            args=(server_id, count, delay, self.kiotproxy_key, self.use_proxy),
            daemon=True
        )
        self.thread.start()
        return True, "Đã khởi động tiến trình"

    def stop(self):
        if not self.is_running:
            return False, "Tiến trình không chạy"
        self.should_stop = True
        self.log("Đã nhận lệnh dừng! Đang đợi chu kỳ hiện tại kết thúc...", "warning")
        return True, "Đang dừng tiến trình"

    def _worker_thread(self, server_id, count, delay, kiotproxy_key, use_proxy):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_run(server_id, count, delay, kiotproxy_key, use_proxy))
        except Exception as e:
            self.log(f"Lỗi ngoại lệ trong Worker: {e}", "error")
        finally:
            self.is_running = False
            self.current_step = "IDLE"
            self.log("Tiến trình đã kết thúc.", "info")
            loop.close()

    async def cancel_pending_session_on_bot_b(self, client):
        """Tìm nút '❌ Hủy Tạo Acc' trên Bot B và bấm hủy (hoặc gửi lệnh /huyreg)"""
        try:
            msgs = await client.get_messages(BOT_B, limit=6)
            for m in msgs:
                if m.buttons:
                    for row in m.buttons:
                        for btn in row:
                            if "hủy" in btn.text.lower() or "cancel" in btn.text.lower():
                                self.log(f"🛑 Tìm thấy nút '{btn.text}' trên Bot B. Đang bấm hủy...", "warning")
                                await btn.click()
                                await asyncio.sleep(2.5)
                                self.log("✅ Đã hủy yêu cầu reg trên Bot B thành công!", "success")
                                return True
            # Nếu không thấy nút bấm, gửi lệnh /huyreg trực tiếp
            self.log("🛑 Gửi lệnh /huyreg để làm sạch hàng đợi Bot B...", "info")
            await client.send_message(BOT_B, "/huyreg")
            await asyncio.sleep(2)
            return True
        except Exception as e:
            self.log(f"⚠️ Lỗi khi hủy phiên Bot B: {e}", "warning")
        return False

    async def click_resend_otp_on_bot_b(self, client):
        """Tìm nút '📲 Gửi Lại Mã' trên Bot B và click sau 70s"""
        try:
            msgs = await client.get_messages(BOT_B, limit=6)
            for m in msgs:
                if m.buttons:
                    for row in m.buttons:
                        for btn in row:
                            if "gửi lại" in btn.text.lower() or "resend" in btn.text.lower():
                                self.log(f"📲 Tìm thấy nút '{btn.text}' trên Bot B. Đang bấm gửi lại OTP...", "info")
                                await btn.click()
                                await asyncio.sleep(2)
                                self.log("✅ Đã bấm nút 'Gửi Lại Mã' trên Bot B thành công!", "success")
                                return True
        except Exception as e:
            self.log(f"⚠️ Lỗi khi bấm gửi lại mã trên Bot B: {e}", "warning")
        return False

    async def _async_run(self, server_id, count, delay, kiotproxy_key, use_proxy):
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            self.log("Chưa đăng nhập Telegram! Vui lòng chạy DANG_NHAP_TELEGRAM.bat trước.", "error")
            return

        async with aiohttp.ClientSession() as http:
            current_success = 0
            cycle_count = 0
            consecutive_fails = 0

            while current_success < count and not self.should_stop:
                cycle_count += 1
                self.stats["current_index"] = current_success + 1
                self.log(f"--- [MỤC TIÊU: {current_success + 1}/{count}] Bắt đầu phiên reg (Lượt thử #{cycle_count}) ---", "info")

                success, reason, spent_cycle = await self._run_single_reg_cycle(client, http, server_id, kiotproxy_key, use_proxy)
                if success:
                    current_success += 1
                    self.stats["success"] = current_success
                    self.stats["total_spent"] += spent_cycle
                    consecutive_fails = 0
                    
                    if current_success < count and not self.should_stop:
                        self.current_step = f"RESTING ({delay}s)"
                        self.log(f"Nghỉ {delay} giây trước khi chạy lượt tiếp theo...", "info")
                        for _ in range(delay):
                            if self.should_stop:
                                break
                            await asyncio.sleep(1)
                else:
                    self.stats["failed"] += 1
                    consecutive_fails += 1
                    if reason == "EXPIRED":
                        self.log("🔄 SIM QUÁ HẠN ➡️ Đã hủy phiên Bot B. Tự động thuê số mới chạy tiếp phiên...", "warning")
                    else:
                        self.log("⚠️ Phiên reg thất bại. Tự động thử lại...", "warning")

                    if consecutive_fails >= 5:
                        self.log("❌ Đã thất bại liên tiếp 5 lần! Dừng tiến trình để tránh tiêu tốn chi phí.", "error")
                        break

                    # Nghỉ 3 giây trước khi retry số mới
                    await asyncio.sleep(3)

        await client.disconnect()

    async def _run_single_reg_cycle(self, client, http, server_id, kiotproxy_key="", use_proxy=False):
        headers = {"Authorization": f"Bearer {CMSNPA_KEY}", "Content-Type": "application/json"}
        cmsnpa_price = SERVICES.get(server_id, {}).get("price", 3200)

        # Dọn dẹp: Hủy phiên treo cũ trên Bot B nếu có trước khi bắt đầu
        await self.cancel_pending_session_on_bot_b(client)

        # 1. Thuê SĐT từ CMSNPA
        self.current_step = "RENTING_PHONE"
        self.log("Đang gọi API CMSNPA để thuê số điện thoại...", "info")
        rental_id, phone = None, None
        try:
            async with http.post(f"{CMSNPA_BASE}/api/v1/get_number", headers=headers, json={"server": server_id}, timeout=15) as r:
                data = await r.json()
                if data.get("ResponseCode") == 0:
                    res = data.get("Result", {})
                    rental_id = res.get("Id")
                    phone = res.get("Number")
                else:
                    self.log(f"Lỗi thuê số: {data.get('Msg', 'Không rõ')}", "error")
                    return False, "RENT_FAIL", 0
        except Exception as e:
            self.log(f"Lỗi kết nối API thuê số: {e}", "error")
            return False, "NETWORK_ERROR", 0

        if not phone:
            self.log("Không nhận được số điện thoại từ API.", "error")
            return False, "NO_PHONE", 0

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

        self.log(f"Thuê số thành công từ CMSNPA: {phone_clean} (ReqID: {rental_id})", "success")

        # 2. Xử lý Proxy (Tự động xoay IP phiên nếu bật KiotProxy)
        proxy_assigned = None
        bot_fee = 700  # Mặc định dùng /regsdt (700đ)

        if use_proxy and kiotproxy_key:
            self.current_step = "ROTATING_PROXY"
            self.log("🌐 Đang kết nối KiotProxy xoay IP phiên mới...", "info")
            p_str, p_note, p_err = get_kiotproxy_ip(kiotproxy_key, rotate=True)
            if p_str:
                proxy_assigned = p_str
                self.last_proxy = p_str
                bot_fee = 500  # Gói /regfull (500đ)
                self.log(f"✅ KiotProxy đã cấp IP: {p_str} ({p_note}) — Phí bot: 500đ", "success")
            else:
                self.log(f"⚠️ KiotProxy không khả dụng ({p_err}). Tự động dùng IP của Bot B (/regsdt - 700đ)...", "warning")

        # 3. Gửi lệnh Reg sang @sfast_main_bot
        self.current_step = "SENDING_REG"
        if proxy_assigned:
            reg_cmd = f"/regfull {phone_clean}|{proxy_assigned}"
        else:
            reg_cmd = f"/regsdt {phone_clean}"

        self.log(f"Gửi lệnh sang @sfast_main_bot: {reg_cmd}", "info")
        sent_msg = await client.send_message(BOT_B, reg_cmd)
        sent_msg_id = sent_msg.id

        # 3.1 Kiểm tra phản hồi khoa học từ Bot B (Chỉ đọc tin sinh ra SAU tin nhắn vừa gửi)
        self.log("Đang đợi Bot B xác nhận tiếp nhận đơn...", "info")
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
                    self.log(f"❌ Bot B từ chối: SĐT {phone_clean} ĐÃ CÓ TÀI KHOẢN SHOPEE CŨ!", "error")
                    is_rejected = True
                    break
                elif "không hợp lệ" in txt:
                    self.log(f"❌ Bot B từ chối: SĐT {phone_clean} KHÔNG HỢP LỆ!", "error")
                    is_rejected = True
                    break
                elif "proxy" in txt and ("lỗi" in txt or "thất bại" in txt or "die" in txt):
                    self.log(f"❌ Bot B báo lỗi Proxy: {txt[:80]}", "error")
                    is_rejected = True
                    break

                # Bot B đã chấp nhận thành công vào hàng đợi / đang tạo
                if "đã đưa vào hàng đợi" in txt or "đang tạo account" in txt or "mã phiên" in txt or "gửi mã otp" in txt:
                    self.log(f"✅ Bot B đã tiếp nhận đơn reg SĐT {phone_clean} thành công!", "success")
                    is_accepted = True
                    break

            if is_rejected or is_accepted:
                break

        if is_rejected:
            self.log(f"🔄 Bỏ qua số {phone_clean}. Bên A sẽ tự hoàn tiền sau 300s. Đang chuyển sang thuê số mới...", "warning")
            await asyncio.sleep(3)
            return False, "PHONE_REJECTED", 0

        if not is_accepted:
            self.log("ℹ️ Bot B đang xử lý ngầm (không phát sinh lỗi). Tiếp tục chuyển sang bước chờ OTP.", "info")

        # 4. Chờ OTP (API Polling + Lắng nghe Bot A)
        self.current_step = "WAITING_OTP"
        self.log(f"Đang chờ OTP cho số {phone_clean} (Theo chu kỳ 300s của bên A)...", "info")
        otp_found = None
        is_expired = False
        start_wait = time.time()
        timeout_sim = 310

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

        while time.time() - start_wait < timeout_sim:
            if self.should_stop:
                client.remove_event_handler(bot_a_handler)
                await self.cancel_pending_session_on_bot_b(client)
                return False, "USER_STOPPED", 0

            # Tự động bấm '📲 Gửi Lại Mã' trên Bot B sau 100 giây nếu chưa có OTP
            elapsed_wait = time.time() - start_wait
            if elapsed_wait >= 100 and not resend_clicked:
                resend_clicked = True
                self.log(f"⏰ Đã qua 100 giây chưa có OTP. Đang bấm nút '📲 Gửi Lại Mã' trên Bot B...", "info")
                await self.click_resend_otp_on_bot_b(client)

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
                                    self.log(f"⚡ Bắt được OTP từ Bot A (@simclonenpa_bot): {otp_found}", "otp")
                                    break
                        elif "Hoàn tiền thuê số" in txt_a or "Không nhận được OTP" in txt_a:
                            if clean_num in txt_a:
                                is_expired = True
                                break
            except Exception:
                pass

            if otp_found:
                break

            # 2. Nếu Bot A chính thức phát thông báo hoàn tiền cho số này
            if is_expired:
                self.log(f"⚠️ Bot A (@simclonenpa_bot) ĐÃ XÁC NHẬN: Sim {phone_clean} hết hạn & đã được hoàn tiền!", "warning")
                break

            # 3. Nếu nhận được OTP từ Telegram Bot A event
            if captured_otp["code"]:
                otp_found = captured_otp["code"]
                self.log(f"⚡ Bắt được OTP từ Bot A (@simclonenpa_bot): {otp_found}", "otp")
                break

            # 4. Hỏi qua API CMSNPA (polling song song)
            try:
                async with http.post(f"{CMSNPA_BASE}/api/v1/check_code", headers=headers, json={"id": str(rental_id)}, timeout=8) as r:
                    res_data = await r.json()
                    if res_data.get("ResponseCode") == 0:
                        res_obj = res_data.get("Result", {})
                        code = res_obj.get("Code") or res_obj.get("Fields", {}).get("Mã OTP")
                        if code:
                            otp_found = str(code).strip()
                            self.log(f"⚡ Bắt được OTP từ API CMSNPA: {otp_found}", "otp")
                            break
            except Exception:
                pass

            await asyncio.sleep(3)

        client.remove_event_handler(bot_a_handler)

        # 5. Nếu sim hết hạn / hoàn trả hoặc quá 310s không có OTP:
        if not otp_found:
            self.log(f"🛑 Sim {phone_clean} đã hết hạn/hoàn tiền xong. Bắt đầu bấm '❌ Hủy Tạo Acc' bên Bot B...", "warning")
            await self.cancel_pending_session_on_bot_b(client)
            self.log(f"⏳ Chờ 5 giây dọn dẹp hàng đợi Bot B trước khi bắt đầu phiên mới...", "info")
            await asyncio.sleep(5)
            return False, "EXPIRED", 0

        # 6. Gửi OTP sang Bot B khi có mã hợp lệ
        self.current_step = "SENDING_OTP"
        otp_cmd = f"/otp {otp_found}"
        self.log(f"Gửi mã OTP vào @sfast_main_bot: {otp_cmd}", "info")
        sent_otp_msg = await client.send_message(BOT_B, otp_cmd)
        sent_otp_id = sent_otp_msg.id

        # 7. Chờ kết quả tạo tài khoản từ Bot B (Chỉ xét tin nhắn sinh ra SAU KHI GỬI /otp)
        self.current_step = "WAITING_RESULT"
        self.log("Chờ Bot B hoàn tất tạo tài khoản...", "info")
        start_res = time.time()
        while time.time() - start_res < 90:
            if self.should_stop:
                return False, "USER_STOPPED", 0
            await asyncio.sleep(3)
            msgs = await client.get_messages(BOT_B, limit=10)
            new_msgs = [m for m in msgs if m.id > sent_otp_id and not m.out]
            for m in new_msgs:
                txt = m.text or ""
                if "TẠO ACCOUNT THÀNH CÔNG" in txt:
                    clean_txt = txt.replace("`", "").strip()
                    total_spent_cycle = cmsnpa_price + bot_fee
                    self.log(f"🎉 TẠO ACCOUNT THÀNH CÔNG CHO SĐT {phone_clean}! Chi phí phiên: {total_spent_cycle:,}đ (SIM: {cmsnpa_price:,}đ + Bot: {bot_fee:,}đ)", "success")
                    
                    acc_match = re.search(r'([a-zA-Z0-9_\-\.]+)\|([^\|\n]+)\|(\d+)\|(SPC_F=[^\s\n\r]+)', clean_txt)
                    spc_st_match = re.search(r'(SPC_ST=[^\s\n\r]+)', clean_txt)

                    acc_raw = acc_match.group(0) if acc_match else f"Acc_{phone_clean}|Shopee"
                    spc_st = spc_st_match.group(1) if spc_st_match else ""

                    # Lưu vào danh sách accounts_reg
                    self.save_account_record(acc_raw, spc_st, phone_clean)
                    
                    # Tự động nạp luôn vào Cookie Vault của tool
                    try:
                        f_cookie = acc_match.group(4) if acc_match else acc_raw
                        self.save_to_cookie_vault(phone_clean, f_cookie, spc_st)
                        self.log(f"💾 Đã tự động lưu vào Kho Cookie & Danh sách!", "success")
                    except Exception as _ex:
                        self.log(f"⚠️ Lỗi nạp Kho Cookie: {_ex}", "warning")

                    return True, "SUCCESS", total_spent_cycle
                elif "mã otp nhập không đúng" in txt.lower() or "hết lượt thử" in txt.lower():
                    self.log(f"Bot B báo tạo tài khoản thất bại: {txt[:80]}", "error")
                    return False, "FAILED", 0

        self.log(f"Hết thời gian chờ kết quả từ Bot B cho số {phone_clean}.", "warning")
        return False, "TIMEOUT", 0

    def save_to_cookie_vault(self, phone, spc_f, spc_st):
        """Tự động đưa Cookie vào Kho Cookie của Shopee Tracker"""
        vault_file = os.path.join(DIRECTORY, "cookie_vault.json")
        vault = []
        if os.path.exists(vault_file):
            try:
                with open(vault_file, "r", encoding="utf-8") as f:
                    vault = json.load(f)
            except Exception:
                vault = []
        
        cookie_val = spc_f
        if spc_st:
            cookie_val = f"{spc_f}; {spc_st}"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        vault.insert(0, {
            "id": str(int(time.time() * 1000)),
            "name": f"Shopee {phone}",
            "cookie": cookie_val,
            "tags": "AutoReg, Shopee",
            "notes": f"Tự động tạo lúc {now_str}",
            "status": "live",
            "username": f"0{phone}" if not phone.startswith("0") else phone,
            "created_at": now_str,
            "updated_at": now_str
        })
        with open(vault_file, "w", encoding="utf-8") as f:
            json.dump(vault, f, ensure_ascii=False, indent=2)

# Global instance
auto_reg_mgr = AutoRegManager()
