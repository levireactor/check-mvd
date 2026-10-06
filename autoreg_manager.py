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

    async def cancel_pending_session_on_bot_b(self, client, target_phone=""):
        """Tìm nút '❌ Hủy Tạo Acc' khớp đúng SĐT trên Bot B và bấm hủy (hoặc gửi /huyreg khi sim đã hết hạn)"""
        clean_num = target_phone.lstrip("0") if target_phone else ""
        try:
            msgs = await client.get_messages(BOT_B, limit=8)
            for m in msgs:
                if not m.out:
                    txt = m.text or ""
                    # Bắt buộc đối chiếu đúng số điện thoại nếu có target_phone
                    if target_phone and (target_phone not in txt and clean_num not in txt):
                        continue

                    if m.buttons:
                        for row in m.buttons:
                            for btn in row:
                                if "hủy" in btn.text.lower() or "cancel" in btn.text.lower():
                                    phone_info = f" cho SĐT {target_phone}" if target_phone else ""
                                    self.log(f"🛑 Đang bấm nút '{btn.text}' trên Bot B{phone_info}...", "warning")
                                    await btn.click()
                                    await asyncio.sleep(2)
                                    self.log("✅ Đã bấm hủy phiên trên Bot B thành công!", "success")
                                    return True
            # Nếu không tìm thấy nút bấm khớp số, gửi lệnh /huyreg trực tiếp
            phone_info = f" (Sim {target_phone} đã hết hạn hoàn tiền trên Bot A)" if target_phone else ""
            self.log(f"🛑 Gửi lệnh /huyreg để làm sạch hàng đợi Bot B{phone_info}...", "info")
            await client.send_message(BOT_B, "/huyreg")
            await asyncio.sleep(2)
            return True
        except Exception as e:
            self.log(f"⚠️ Lỗi khi hủy phiên Bot B: {e}", "warning")
        return False

    async def click_resend_otp_on_bot_b(self, client):
        """Tìm nút '📲 Gửi Lại Mã' trên Bot B và click sau 70s"""
        try:
            msgs = await client.get_messages(BOT_B, limit=4)
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

    def _handle_success_account(self, clean_txt, phone_clean, cmsnpa_price, bot_fee):
        """Hàm xử lý và lưu tài khoản khi Bot B báo TẠO ACCOUNT THÀNH CÔNG"""
        clean_txt = clean_txt.replace("`", "").strip()
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

    async def _async_run(self, server_id, count, delay, kiotproxy_key, use_proxy):
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            self.log("Chưa đăng nhập Telegram! Vui lòng liên kết tài khoản Telegram trên giao diện trước.", "error")
            return

        async with aiohttp.ClientSession() as http:
            current_success = 0
            cycle_count = 0
            consecutive_fails = 0
            max_attempts = max(count * 4, 10)  # Giới hạn tối đa số lần thử tránh chạy vô tận

            while current_success < count and not self.should_stop:
                if cycle_count >= max_attempts:
                    self.log(f"🛑 Đã đạt giới hạn tối đa {max_attempts} lượt thử. Dừng tiến trình.", "warning")
                    break

                cycle_count += 1
                self.stats["current_index"] = current_success + 1
                self.log(f"--- [TIẾN ĐỘ: Đã xong {current_success}/{count} Acc | Lượt thử #{cycle_count}] ---", "info")

                success, reason, spent_cycle = await self._run_single_reg_cycle(client, http, server_id, kiotproxy_key, use_proxy)
                if success:
                    current_success += 1
                    self.stats["success"] = current_success
                    self.stats["total_spent"] += spent_cycle
                    consecutive_fails = 0
                    
                    if current_success >= count:
                        self.log(f"🎉🎉 ĐÃ HOÀN THÀNH MỤC TIÊU! Tạo thành công {current_success}/{count} tài khoản Shopee.", "success")
                        break
                    
                    if not self.should_stop:
                        self.current_step = f"RESTING ({delay}s)"
                        self.log(f"Nghỉ {delay} giây trước khi chạy tài khoản tiếp theo...", "info")
                        for _ in range(delay):
                            if self.should_stop:
                                break
                            await asyncio.sleep(1)
                else:
                    self.stats["failed"] += 1
                    consecutive_fails += 1
                    if reason == "EXPIRED":
                        self.log("🔄 SIM KHÔNG CÓ OTP ➡️ Đã dọn dẹp phiên. Tự động thuê số mới chạy tiếp...", "warning")
                    elif reason == "INSUFFICIENT_BALANCE":
                        self.log("❌ Số dư trên Bot B không đủ. Dừng tiến trình ngay lập tức!", "error")
                        break
                    elif reason == "PHONE_REJECTED":
                        self.log("ℹ️ SĐT cũ bị từ chối. Đang thử lại với SĐT mới...", "info")
                    else:
                        self.log("⚠️ Phiên thử thất bại. Tự động thử lại lượt tiếp theo...", "warning")

                    if consecutive_fails >= 5:
                        self.log("❌ Đã thất bại liên tiếp 5 lần! Dừng tiến trình để tránh tiêu tốn chi phí.", "error")
                        break

                    # Nghỉ 3 giây trước khi retry số mới
                    await asyncio.sleep(3)

        await client.disconnect()

    async def _run_single_reg_cycle(self, client, http, server_id, kiotproxy_key="", use_proxy=False):
        headers = {"Authorization": f"Bearer {CMSNPA_KEY}", "Content-Type": "application/json"}
        cmsnpa_price = SERVICES.get(server_id, {}).get("price", 3200)

        # 0. Kiểm tra nếu Bot B đang có phiên cũ đang chạy: Chờ kết thúc
        try:
            recent_b = await client.get_messages(BOT_B, limit=3)
            for m in recent_b:
                if not m.out:
                    txt = (m.text or "").lower()
                    if "đang tạo account" in txt or "shopee đang gọi điện" in txt:
                        self.log("⏳ Bot B đang có phiên reg đang chạy. Đang chờ 15s cho phiên cũ hoàn tất...", "info")
                        for _ in range(5):
                            await asyncio.sleep(3)
                            msgs_check = await client.get_messages(BOT_B, limit=3)
                            for mc in msgs_check:
                                if not mc.out and "tạo account thành công" in (mc.text or "").lower():
                                    self.log("🎉 Phiên cũ trên Bot B đã hoàn tất thành công!", "success")
                                    return self._handle_success_account(mc.text, "Acc_Saved", cmsnpa_price, 700)
        except Exception:
            pass

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

        # 3.1 Kiểm tra phản hồi từ Bot B
        self.log("Đang đợi Bot B xác nhận tiếp nhận đơn...", "info")
        is_accepted = False
        is_rejected = False
        check_start = time.time()

        while time.time() - check_start < 12:
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
                    self.log(f"❌ Bot B báo lỗi Proxy: {m.text[:80]}", "error")
                    is_rejected = True
                    break
                elif "số dư không đủ" in txt or "không đủ tiền" in txt or "hết tiền" in txt:
                    self.log(f"❌ Bot B báo số dư không đủ để thực hiện!", "error")
                    is_rejected = True
                    return False, "INSUFFICIENT_BALANCE", 0
                elif "đang có phiên tạo acc đang chạy" in txt:
                    self.log("⚠️ Bot B đang bận phiên khác. Chờ 8s...", "warning")
                    await asyncio.sleep(8)
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
            self.log(f"🔄 Bỏ qua số {phone_clean}. CMSNPA sẽ tự hoàn tiền sau 300s. Đang chuyển sang thuê số mới...", "warning")
            await asyncio.sleep(2)
            return False, "PHONE_REJECTED", 0

        if not is_accepted:
            self.log("ℹ️ Bot B đang xử lý. Tiếp tục chuyển sang bước theo dõi OTP & kết quả...", "info")

        # Lấy ID tin nhắn mới nhất trên Bot A trước khi bắt đầu chờ
        try:
            msgs_a_init = await client.get_messages(BOT_A, limit=1)
            last_bot_a_id = msgs_a_init[0].id if msgs_a_init else 0
        except Exception:
            last_bot_a_id = 0

        # 4. Chờ OTP & Đồng thời theo dõi Bot B
        self.current_step = "WAITING_OTP"
        self.log(f"Đang chờ OTP cho số {phone_clean} (Theo dõi chặt chẽ Bot A & Bot B)...", "info")
        otp_found = None
        is_expired = False
        start_wait = time.time()
        timeout_sim = 320  # Đợi trọn vẹn chu kỳ 300s của Bot A/CMSNPA (tối đa 320s)

        captured_otp = {"code": None}
        clean_num = phone_clean.lstrip("0")

        @client.on(events.NewMessage(chats=BOT_A))
        async def bot_a_handler(event):
            nonlocal is_expired
            text = event.raw_text
            if (clean_num in text) or (phone_clean in text):
                if "Đã nhận được OTP" in text:
                    match = re.search(r'Mã OTP:\s*\**(\d{4,8})\**', text)
                    if match:
                        captured_otp["code"] = match.group(1)
                elif "Hoàn tiền thuê số" in text or "Không nhận được OTP" in text:
                    is_expired = True

        resend_first_seen_time = None
        resend_clicked = False
        last_progress_log = time.time()

        while time.time() - start_wait < timeout_sim:
            if self.should_stop:
                client.remove_event_handler(bot_a_handler)
                await self.cancel_pending_session_on_bot_b(client, target_phone=phone_clean)
                return False, "USER_STOPPED", 0

            # 4.0 KIỂM TRA BOT B: ĐỐI CHIẾU KỸ SỐ ĐIỆN THOẠI ĐANG CHẠY TRONG PHIÊN
            try:
                msgs_b = await client.get_messages(BOT_B, limit=6)
                for mb in msgs_b:
                    if mb.id > sent_msg_id and not mb.out:
                        txt_b = mb.text or ""
                        # PHẢI QUÉT KĨ SỐ ĐIỆN THOẠI ĐANG ĐƯỢC CHẠY TRONG PHIÊN
                        if (phone_clean not in txt_b) and (clean_num not in txt_b):
                            continue

                        # Nếu Bot B đã tạo thành công cho đúng số này
                        if "TẠO ACCOUNT THÀNH CÔNG" in txt_b:
                            client.remove_event_handler(bot_a_handler)
                            return self._handle_success_account(txt_b, phone_clean, cmsnpa_price, bot_fee)

                        # Quét nút '📲 Gửi Lại Mã': Ghi nhận thời điểm xuất hiện lần đầu trên Bot B
                        if mb.buttons and (resend_first_seen_time is None) and (not resend_clicked):
                            for row in mb.buttons:
                                for btn in row:
                                    if "gửi lại" in btn.text.lower() or "resend" in btn.text.lower():
                                        resend_first_seen_time = time.time()
                                        self.log(f"⏱️ Đã phát hiện nút '{btn.text}' trên Bot B cho SĐT {phone_clean}. Bắt đầu tính đúng 100s kể từ thời điểm này...", "info")
                                        break
            except Exception:
                pass

            # XỬ LÝ BẤM NÚT 'GỬI LẠI MÃ' KHI ĐÃ ĐỦ 100S KỂ TỪ KHI NÚT XUẤT HIỆN
            if (resend_first_seen_time is not None) and (not resend_clicked):
                elapsed_btn = time.time() - resend_first_seen_time
                if elapsed_btn >= 100:
                    resend_clicked = True
                    self.log(f"📲 Đã đủ 100s ({int(elapsed_btn)}s) kể từ khi nút xuất hiện. Đang bấm nút 'Gửi Lại Mã' trên Bot B cho SĐT {phone_clean}...", "info")
                    try:
                        msgs_b_btn = await client.get_messages(BOT_B, limit=6)
                        btn_clicked_ok = False
                        for m_btn in msgs_b_btn:
                            if not m_btn.out:
                                txt_m = m_btn.text or ""
                                if (phone_clean in txt_m) or (clean_num in txt_m):
                                    if m_btn.buttons:
                                        for row in m_btn.buttons:
                                            for b in row:
                                                if "gửi lại" in b.text.lower() or "resend" in b.text.lower():
                                                    await b.click()
                                                    btn_clicked_ok = True
                                                    self.log(f"✅ Đã bấm nút '{b.text}' trên Bot B cho SĐT {phone_clean} thành công!", "success")
                                                    break
                                            if btn_clicked_ok:
                                                break
                            if btn_clicked_ok:
                                break
                        if not btn_clicked_ok:
                            self.log(f"ℹ️ Không thấy nút gửi lại mã còn hoạt động trên Bot B cho SĐT {phone_clean}.", "info")
                    except Exception as _b_err:
                        self.log(f"⚠️ Lỗi khi bấm nút gửi lại mã: {_b_err}", "warning")

            # 4.1 ĐỌC TRỰC TIẾP HỘP THƯ BOT A (Đối chiếu chính xác số điện thoại đang chạy trong phiên)
            try:
                msgs_a = await client.get_messages(BOT_A, limit=6)
                for m in msgs_a:
                    if m.id > last_bot_a_id and not m.out:
                        txt_a = m.text or ""
                        if (clean_num in txt_a) or (phone_clean in txt_a):
                            if "Đã nhận được OTP" in txt_a:
                                match = re.search(r'Mã OTP:\s*\**(\d{4,8})\**', txt_a)
                                if match:
                                    otp_found = match.group(1)
                                    self.log(f"⚡ Bắt được OTP từ Bot A (@simclonenpa_bot) cho số {phone_clean}: {otp_found}", "otp")
                                    break
                            elif "Hoàn tiền thuê số" in txt_a or "Không nhận được OTP" in txt_a:
                                is_expired = True
                                self.log(f"⚠️ Bot A (@simclonenpa_bot) đã chính thức thông báo: Sim {phone_clean} hết hạn & hoàn tiền!", "warning")
                                break
            except Exception:
                pass

            if otp_found:
                break

            # CHỈ DỪNG CHỜ KHI SIM TRÊN BOT A THỰC SỰ XÁC NHẬN HẾT HẠN HOÀN TIỀN
            if is_expired:
                break

            if captured_otp["code"]:
                otp_found = captured_otp["code"]
                self.log(f"⚡ Bắt được OTP từ Bot A (@simclonenpa_bot) cho số {phone_clean}: {otp_found}", "otp")
                break

            # 4.2 Hỏi qua API CMSNPA (chỉ bắt OTP nếu có, KHÔNG tự ý báo expired)
            try:
                async with http.post(f"{CMSNPA_BASE}/api/v1/check_code", headers=headers, json={"id": str(rental_id)}, timeout=8) as r:
                    res_data = await r.json()
                    if res_data.get("ResponseCode") == 0:
                        res_obj = res_data.get("Result", {})
                        code = res_obj.get("Code") or res_obj.get("Fields", {}).get("Mã OTP")
                        if code:
                            otp_found = str(code).strip()
                            self.log(f"⚡ Bắt được OTP từ API CMSNPA cho số {phone_clean}: {otp_found}", "otp")
                            break
            except Exception:
                pass

            # Log tiến độ chờ định kỳ mỗi 30s
            now_wait = time.time()
            if now_wait - last_progress_log >= 30:
                elapsed_total = int(now_wait - start_wait)
                extra_status = ""
                if resend_first_seen_time and not resend_clicked:
                    sec_left = max(0, 100 - int(now_wait - resend_first_seen_time))
                    extra_status = f" | Còn {sec_left}s sẽ bấm Gửi Lại Mã"
                elif resend_clicked:
                    extra_status = " | Đã bấm Gửi Lại Mã"
                self.log(f"⏳ Đang đợi OTP cho số {phone_clean} ({elapsed_total}s/300s chu kỳ Sim Bot A{extra_status})...", "info")
                last_progress_log = now_wait

            await asyncio.sleep(2.5)

        client.remove_event_handler(bot_a_handler)

        # 5. CHỈ KHI SIM TRÊN BOT A ĐÃ CHÍNH THỨC HẾT HẠN / HOÀN TIỀN XONG MỚI QUÉT HỦY TRÊN BOT B:
        if not otp_found:
            self.log(f"🛑 Sim {phone_clean} trên Bot A ĐÃ CHÍNH THỨC HẾT HẠN / HOÀN TIỀN XONG. Bắt đầu quét sang Bot B để hủy phiên...", "warning")
            await self.cancel_pending_session_on_bot_b(client, target_phone=phone_clean)
            await asyncio.sleep(3)
            return False, "EXPIRED", 0

        # 6. Gửi OTP sang Bot B khi có mã hợp lệ
        self.current_step = "SENDING_OTP"
        otp_cmd = f"/otp {otp_found}"
        self.log(f"Gửi mã OTP vào @sfast_main_bot: {otp_cmd}", "info")
        sent_otp_msg = await client.send_message(BOT_B, otp_cmd)
        sent_otp_id = sent_otp_msg.id

        # 7. Chờ kết quả tạo tài khoản từ Bot B
        self.current_step = "WAITING_RESULT"
        self.log("Chờ Bot B hoàn tất tạo tài khoản...", "info")
        start_res = time.time()
        while time.time() - start_res < 60:
            if self.should_stop:
                return False, "USER_STOPPED", 0
            await asyncio.sleep(2.5)
            msgs = await client.get_messages(BOT_B, limit=10)
            new_msgs = [m for m in msgs if m.id > sent_msg_id and not m.out]
            for m in new_msgs:
                txt = m.text or ""
                if "TẠO ACCOUNT THÀNH CÔNG" in txt:
                    return self._handle_success_account(txt, phone_clean, cmsnpa_price, bot_fee)
                elif "mã otp nhập không đúng" in txt.lower() or "hết lượt thử" in txt.lower():
                    self.log(f"❌ Bot B báo OTP sai hoặc hết lượt thử: {txt[:80]}", "error")
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
