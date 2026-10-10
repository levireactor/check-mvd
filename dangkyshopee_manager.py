# -*- coding: utf-8 -*-
"""
MODULE QUẢN LÝ TIẾN TRÌNH TỰ ĐỘNG ĐIỀU PHỐI BOT @dangkyshopee_bot
Thực hiện tuần tự 3 lệnh cho từng tài khoản:
1. /mailfree <nick_data>
2. /addtocart <product_link>|<nick_data>
3. /diachi hoặc /addressnew <nick_data>
   - B1: Nhập khu vực (Phường/Xã/Quận/Tỉnh). Nếu lỗi tìm kiếm: bấm Hủy, delay 8s và làm lại.
   - B2: Tự nhập tên -> Gửi tên
   - B3: Số điện thoại (Ưu tiên SĐT Acc hoặc Tự nhập SĐT ngẫu nhiên)
   - B4: Tự nhập địa chỉ chi tiết -> Gửi địa chỉ
"""

import asyncio
import re
import os
import json
import time
import random
import threading
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(DIRECTORY, "dangkyshopee_history.json")

try:
    from telegram_auth import get_telethon_session, get_string_session_str, API_ID, API_HASH
except Exception:
    API_ID = 33946669
    API_HASH = "d88d388e5810305e722af0cc61a3a80a"
    get_telethon_session = None
    get_string_session_str = None

BOT_TARGET = "@dangkyshopee_bot"

def parse_vietnamese_address(raw_str):
    """
    Bóc tách thông minh chuỗi địa chỉ đầu vào thành:
    - name: Tên người nhận
    - phone: Số điện thoại (nếu có)
    - area: Phường/Xã, Quận/Huyện, Tỉnh/TP
    - street: Địa chỉ chi tiết (Số nhà, đường, ngõ ngách)
    """
    if not raw_str or not isinstance(raw_str, str):
        return {"name": "", "phone": "", "area": "", "street": ""}

    text = raw_str.strip()
    result = {"name": "", "phone": "", "area": "", "street": ""}

    # 1. Tìm số điện thoại (03, 05, 07, 08, 09, 84...)
    phone_match = re.search(r'(\b(?:0|84|\+84)[35789]\d{8}\b)', text)
    if phone_match:
        result["phone"] = phone_match.group(1)
        text = text.replace(result["phone"], " ").strip()

    # 2. Nếu định dạng phân cách bởi dấu gạch đứng | hoặc dấu gạch chéo /
    if "|" in text:
        parts = [p.strip() for p in text.split("|") if p.strip()]
        if len(parts) >= 3:
            result["name"] = parts[0]
            result["area"] = parts[1]
            result["street"] = parts[2]
            return result
        elif len(parts) == 2:
            result["name"] = parts[0]
            result["street"] = parts[1]
            result["area"] = parts[1]
            return result

    # 3. Phân tách theo dấu phẩy với nhận diện từ khóa hành chính
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) >= 2:
        result["name"] = parts[0]
        # Tìm vị trí xuất hiện đơn vị hành chính đầu tiên (phường, xã, thị trấn, quận, huyện, tp, tỉnh)
        area_start_idx = -1
        for i in range(1, len(parts)):
            if re.search(r'\b(phường|xã|thị trấn|quận|huyện|thành phố|tp\.|tỉnh)\b', parts[i], re.IGNORECASE):
                area_start_idx = i
                break

        if area_start_idx > 0:
            result["street"] = ", ".join(parts[1:area_start_idx]) if area_start_idx > 1 else parts[1]
            result["area"] = ", ".join(parts[area_start_idx:])
            return result
        else:
            if len(parts) >= 3:
                result["street"] = parts[1]
                result["area"] = ", ".join(parts[2:])
            else:
                result["street"] = parts[1]
                result["area"] = parts[1]
            return result

    # Nếu chỉ là 1 dòng không dấu phẩy
    result["name"] = text[:20].strip()
    result["area"] = text
    result["street"] = text
    return result

AFF_CONFIG_FILE = os.path.join(DIRECTORY, "affiliate_config.json")

def load_affiliate_config():
    if os.path.exists(AFF_CONFIG_FILE):
        try:
            with open(AFF_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"enabled": False, "app_id": "", "secret": "", "sub_id": ""}

def save_affiliate_config(data):
    try:
        with open(AFF_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def expand_shopee_short_url(url):
    """Mở rộng link rút gọn s.shopee.vn / vn.shp.ee thành link gốc canonical"""
    url = url.strip()
    if any(d in url.lower() for d in ["s.shopee.vn", "vn.shp.ee", "shp.ee", "shope.ee"]):
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
            with opener.open(req, timeout=8) as resp:
                return resp.geturl()
        except Exception:
            pass
    return url

def convert_shopee_affiliate_link(raw_url, app_id=None, secret=None, sub_id=None):
    """
    Gọi Shopee Affiliate GraphQL Open API để sinh shortLink có mã hoa hồng tiếp thị
    Endpoint: https://open-api.affiliate.shopee.vn/graphql
    """
    import hashlib
    import urllib.request
    import urllib.error

    cfg = load_affiliate_config()
    app_id = str(app_id if app_id is not None else cfg.get("app_id", "")).strip()
    secret = str(secret if secret is not None else cfg.get("secret", "")).strip()
    sub_id = str(sub_id if sub_id is not None else cfg.get("sub_id", "")).strip()

    if not app_id or not secret:
        return False, "Chưa cấu hình App ID hoặc Secret Key của Shopee Affiliate"

    # 1. Mở rộng link nếu là dạng rút gọn
    canonical_url = expand_shopee_short_url(raw_url)

    # 2. Xây dựng mutation GraphQL
    if sub_id:
        sub_ids_str = json.dumps([sub_id])
        input_args = f'originUrl: "{canonical_url}", subIds: {sub_ids_str}'
    else:
        input_args = f'originUrl: "{canonical_url}"'

    gql_query = f"mutation {{ generateShortLink(input: {{ {input_args} }}) {{ shortLink }} }}"
    payload = {"query": gql_query}
    payload_str = json.dumps(payload, separators=(',', ':'))

    timestamp = int(time.time())
    factor = f"{app_id}{timestamp}{payload_str}{secret}"
    signature = hashlib.sha256(factor.encode("utf-8")).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}",
        "User-Agent": "ShopeeAffiliateClient/1.0"
    }

    req = urllib.request.Request(
        "https://open-api.affiliate.shopee.vn/graphql",
        data=payload_str.encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if "errors" in res_data and res_data["errors"]:
                err_msg = res_data["errors"][0].get("message", "Lỗi GraphQL Shopee")
                return False, f"Shopee API báo lỗi: {err_msg}"

            data = res_data.get("data", {})
            gen_res = data.get("generateShortLink", {})
            short_link = gen_res.get("shortLink")
            if short_link:
                return True, short_link
            else:
                return False, "Không nhận được shortLink từ Shopee"
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_json = json.loads(err_body)
            msg = err_json.get("message") or err_json.get("errors", [{}])[0].get("message", f"HTTP {e.code}")
            return False, f"Lỗi HTTP {e.code}: {msg}"
        except Exception:
            return False, f"Lỗi kết nối Shopee API (HTTP {e.code})"
    except Exception as e:
        return False, f"Lỗi kết nối: {str(e)}"

class DangKyShopeeManager:
    def __init__(self):
        self.is_running = False
        self.should_stop = False
        self.is_paused = False
        self.thread = None

        self.current_step = "IDLE"
        self.current_nick = ""
        self.current_index = 0
        self.total_nicks = 0

        self.config = {
            "product_link": "",
            "product_variant": "",  # Phân loại/mẫu sản phẩm mong muốn (nếu có)
            "max_cart_retries": 3,
            "use_mailfree": False,  # Mặc định bỏ lệnh mailfree
            "use_addtocart": True,  # Tùy chọn lệnh addtocart (mặc định bật)
            "use_address": True,   # Tùy chọn lệnh diachi (mặc định bật)
            "address_command": "/diachi",  # /diachi hoặc /addressnew
            "address_area": "",
            "address_name": "",
            "address_street": "",
            "phone_mode": "auto",  # auto: lấy sđt acc nếu có, ko có thì random; random: luôn random; custom: dùng số chỉ định
            "custom_phone": "",
            "delay_between_nicks": 6,
            "timeout_step": 50,
            "max_area_retries": 3
        }

        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "current": 0
        }

        self.accounts_queue = []  # List dict thông tin từng nick
        self.logs = []
        self._log_lock = threading.Lock()
        self._load_history()

    def _load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.accounts_queue = data[-200:]
            except Exception:
                pass

    def _save_history(self):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.accounts_queue[-300:], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def log(self, msg, log_type="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = {
            "time": timestamp,
            "msg": str(msg),
            "type": log_type
        }
        with self._log_lock:
            self.logs.append(entry)
            if len(self.logs) > 600:
                self.logs = self.logs[-600:]
        print(f"[{timestamp}] [{log_type.upper()}] {msg}")

    def clear_logs(self):
        with self._log_lock:
            self.logs.clear()

    def clear_queue(self):
        if self.is_running:
            return False, "Tiến trình đang chạy, không thể xóa danh sách!"
        self.accounts_queue.clear()
        self._save_history()
        return True, "Đã xóa toàn bộ danh sách"

    def get_status(self):
        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "current_step": self.current_step,
            "current_nick": self.current_nick,
            "current_index": self.current_index,
            "total_nicks": self.total_nicks,
            "stats": self.stats,
            "config": self.config,
            "queue": self.accounts_queue,
            "logs": self.logs[-150:]
        }

    def start(self, config, nicks_raw):
        if self.is_running:
            return False, "Tiến trình đang chạy!"

        if not nicks_raw or not isinstance(nicks_raw, list) or len(nicks_raw) == 0:
            return False, "Danh sách nick trống!"

        use_mailfree = bool(config.get("use_mailfree", False))
        use_addtocart = bool(config.get("use_addtocart", True))
        use_address = bool(config.get("use_address", True))

        if not (use_mailfree or use_addtocart or use_address):
            return False, "Vui lòng chọn ít nhất 1 lệnh để thực thi (Mailfree, Thêm Giỏ Hàng hoặc Địa Chỉ)!"

        if use_addtocart:
            product_link = str(config.get("product_link", "")).strip()
            if not product_link:
                return False, "Bạn đã bật lệnh Thêm Giỏ Hàng, vui lòng nhập Link sản phẩm!"

        self.config.update(config)
        self.should_stop = False
        self.is_paused = False
        self.is_running = True
        self.current_step = "STARTING"

        # Chuẩn bị hàng đợi
        self.accounts_queue.clear()
        for idx, item in enumerate(nicks_raw):
            raw_line = str(item).strip()
            if not raw_line:
                continue
            # Rút gọn nhãn hiển thị cho nick
            display_name = raw_line
            if len(display_name) > 35:
                if "SPC_ST=" in display_name:
                    display_name = "Cookie_ST..." + display_name[-15:]
                else:
                    display_name = display_name[:32] + "..."

            self.accounts_queue.append({
                "id": idx + 1,
                "raw": raw_line,
                "display": display_name,
                "status": "pending",  # pending, mailfree, addtocart, diachi, success, failed
                "step_detail": "Đang chờ trong hàng đợi",
                "mail_info": "",
                "cart_info": "",
                "address_info": "",
                "error": "",
                "updated_at": datetime.now().strftime("%H:%M:%S")
            })

        self.total_nicks = len(self.accounts_queue)
        self.stats = {
            "total": self.total_nicks,
            "success": 0,
            "failed": 0,
            "current": 0
        }

        self.log(f"🚀 BẮT ĐẦU CHIẾN DỊCH: {self.total_nicks} nick | Lệnh ĐC: {self.config.get('address_command')} | Delay: {self.config.get('delay_between_nicks')}s", "info")

        self.thread = threading.Thread(target=self._worker_thread, daemon=True)
        self.thread.start()
        return True, "Đã khởi động tiến trình thành công"

    def stop(self):
        if not self.is_running:
            return False, "Tiến trình không chạy!"
        self.should_stop = True
        self.log("🛑 Nhận lệnh DỪNG! Đang chờ chu kỳ hiện tại hoàn tất an toàn...", "warning")
        return True, "Đang dừng tiến trình"

    def _worker_thread(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_run())
        except Exception as e:
            self.log(f"💥 Lỗi hệ thống trong luồng điều phối: {e}", "error")
        finally:
            self.is_running = False
            self.current_step = "IDLE"
            self.log("🏁 Toàn bộ chiến dịch đã kết thúc.", "info")
            self._save_history()
            loop.close()

    async def _async_run(self):
        # 1. Khởi tạo Telegram Client
        s_str = get_string_session_str() if get_string_session_str else None
        if s_str:
            client = TelegramClient(StringSession(s_str), API_ID, API_HASH)
        else:
            sess = get_telethon_session() if get_telethon_session else "session_master"
            client = TelegramClient(sess, API_ID, API_HASH)

        await client.connect()
        if not await client.is_user_authorized():
            self.log("❌ Chưa đăng nhập tài khoản Telegram! Vui lòng liên kết Telegram trước.", "error")
            return

        try:
            bot_entity = await client.get_entity(BOT_TARGET)
        except Exception as e:
            self.log(f"❌ Không tìm thấy Bot {BOT_TARGET}: {e}", "error")
            await client.disconnect()
            return

        self.log(f"✅ Đã kết nối Telegram thành công với {BOT_TARGET}!", "success")

        # 2. Xử lý từng nick trong hàng đợi
        for idx, item in enumerate(self.accounts_queue):
            if self.should_stop:
                self.log("🛑 Đã dừng tiến trình theo yêu cầu.", "warning")
                break

            self.current_index = idx + 1
            self.current_nick = item["display"]
            self.stats["current"] = self.current_index
            item["status"] = "running"
            item["updated_at"] = datetime.now().strftime("%H:%M:%S")

            self.log(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "info")
            self.log(f"▶ [{self.current_index}/{self.total_nicks}] Đang xử lý: {self.current_nick}", "info")

            acc_success = await self._process_single_account(client, bot_entity, item)

            if acc_success:
                item["status"] = "success"
                item["step_detail"] = "Hoàn thành cả 3 lệnh thành công"
                self.stats["success"] += 1
                self.log(f"🎉 NICK [{self.current_index}/{self.total_nicks}] HOÀN THÀNH TẤT CẢ 3 BƯỚC!", "success")
            else:
                item["status"] = "failed"
                self.stats["failed"] += 1
                self.log(f"❌ NICK [{self.current_index}/{self.total_nicks}] THẤT BẠI: {item.get('error')}", "error")

            item["updated_at"] = datetime.now().strftime("%H:%M:%S")
            self._save_history()

            # Nghỉ giữa các nick nếu chưa phải nick cuối
            if self.current_index < self.total_nicks and not self.should_stop:
                delay = int(self.config.get("delay_between_nicks", 6))
                self.current_step = f"RESTING ({delay}s)"
                self.log(f"⏳ Nghỉ {delay}s trước khi chạy nick tiếp theo...", "info")
                for _ in range(delay):
                    if self.should_stop:
                        break
                    await asyncio.sleep(1)

        await client.disconnect()

    async def _process_single_account(self, client, bot_entity, item):
        raw_nick = item["raw"]
        use_mailfree = bool(self.config.get("use_mailfree", False))
        use_addtocart = bool(self.config.get("use_addtocart", True))
        use_address = bool(self.config.get("use_address", True))

        # =========================================================================
        # (TÙY CHỌN) LỆNH 1: /mailfree
        # =========================================================================
        if use_mailfree:
            self.current_step = "LỆNH: /mailfree"
            item["status"] = "mailfree"
            item["step_detail"] = "Đang gửi lệnh /mailfree..."
            self.log(f"📤 Gửi Lệnh: /mailfree cho nick...", "info")

            mail_cmd = f"/mailfree {raw_nick}"
            success_mail, mail_res = await self._execute_mailfree(client, bot_entity, mail_cmd)
            if not success_mail:
                item["error"] = f"Lỗi Bước /mailfree: {mail_res}"
                return False

            item["mail_info"] = mail_res
            self.log(f"✅ Lệnh /mailfree THÀNH CÔNG! {mail_res}", "success")
            await asyncio.sleep(2)

            if self.should_stop:
                return False

        # =========================================================================
        # (TÙY CHỌN) LỆNH 2: /addtocart
        # =========================================================================
        if use_addtocart:
            self.current_step = "LỆNH: /addtocart"
            item["status"] = "addtocart"
            item["step_detail"] = "Đang gửi lệnh /addtocart..."
            prod_link = self.config.get("product_link", "").strip()

            # Kiểm tra tự động chuyển đổi sang link Affiliate của người dùng
            aff_cfg = load_affiliate_config()
            if aff_cfg.get("enabled") and aff_cfg.get("app_id") and aff_cfg.get("secret"):
                self.log("🔗 Đang chuyển đổi link sản phẩm sang link Affiliate của bạn...", "info")
                aff_ok, aff_res = convert_shopee_affiliate_link(prod_link)
                if aff_ok:
                    prod_link = aff_res
                    self.log(f"✅ Đã chuyển đổi thành công link Affiliate: {prod_link}", "success")
                else:
                    self.log(f"⚠️ Chuyển đổi link Affiliate chưa được: {aff_res}. Tiếp tục dùng link gốc.", "warning")

            self.log(f"📤 Gửi /addtocart {prod_link}|<nick>...", "info")

            cart_cmd = f"/addtocart {prod_link}|{raw_nick}"
            success_cart, cart_res = await self._execute_addtocart(client, bot_entity, cart_cmd)
            if success_cart:
                item["cart_info"] = cart_res
                self.log(f"✅ Lệnh /addtocart THÀNH CÔNG! {cart_res}", "success")
            else:
                item["cart_info"] = f"Lỗi: {cart_res}"
                if not use_address:
                    item["error"] = f"Lỗi /addtocart: {cart_res}"
                    return False
                self.log(f"⚠️ Lệnh /addtocart không thành công ({cart_res}), tiếp tục chạy luôn lệnh địa chỉ...", "warning")

            await asyncio.sleep(2)

            if self.should_stop:
                return False

        # =========================================================================
        # (TÙY CHỌN) LỆNH 3: /diachi hoặc /addressnew (Interactive Wizard)
        # =========================================================================
        if use_address:
            self.current_step = "LỆNH: ĐỊA CHỈ"
            item["status"] = "diachi"
            item["step_detail"] = "Đang gửi lệnh thêm địa chỉ..."
            addr_cmd_type = self.config.get("address_command", "/diachi")
            self.log(f"📤 Gửi lệnh {addr_cmd_type} cho nick...", "info")

            addr_cmd = f"{addr_cmd_type} {raw_nick}"
            success_addr, addr_res = await self._execute_address_wizard(client, bot_entity, addr_cmd)
            if not success_addr:
                item["error"] = f"Lỗi ({addr_cmd_type}): {addr_res}"
                return False

            item["address_info"] = addr_res
            self.log(f"✅ Lệnh {addr_cmd_type} THÀNH CÔNG! {addr_res}", "success")

        return True

    # -------------------------------------------------------------------------
    # BỘ XỬ LÝ LỆNH 1: /mailfree
    # -------------------------------------------------------------------------
    async def _execute_mailfree(self, client, bot_entity, cmd_text):
        timeout = int(self.config.get("timeout_step", 50))
        last_sent = await client.send_message(bot_entity, cmd_text)
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.should_stop:
                return False, "Tiến trình bị dừng"

            messages = await client.get_messages(bot_entity, limit=4)
            for m in messages:
                if not m.out and m.id > last_sent.id:
                    txt = m.text or ""
                    # Kiểm tra dấu hiệu thành công
                    if "THÀNH CÔNG!" in txt or "XÁC MINH THÀNH CÔNG!" in txt:
                        # Rút trích email nếu có
                        em_match = re.search(r'([a-zA-Z0-9_\-\.]+@[a-zA-Z0-9_\-\.]+\.[a-zA-Z]{2,})', txt)
                        email = em_match.group(1) if em_match else "Đã cấp mail"
                        return True, email

                    # Kiểm tra dấu hiệu lỗi
                    if "❌" in txt or "Lỗi:" in txt:
                        err_line = txt.split("\n")[0]
                        return False, err_line

            await asyncio.sleep(2)

        return False, f"Hết thời gian chờ phản hồi ({timeout}s)"

    # -------------------------------------------------------------------------
    # BỘ XỬ LÝ LỆNH: /addtocart (NÂNG CẤP: CHỌN PHÂN LOẠI & BẤM NÚT XÁC NHẬN THÊM SẢN PHẨM)
    # -------------------------------------------------------------------------
    def _is_cancel_button(self, btn_text):
        """Kiểm tra nếu nút mang ý nghĩa Hủy/Cancel/Quay lại/Đóng"""
        if not btn_text:
            return False
        t = btn_text.strip().lower()
        cancel_keywords = ["hủy", "huy", "cancel", "quay lại", "thoát", "close", "đóng", "back", "dừng", "stop"]
        return any(ck in t for ck in cancel_keywords)

    def _is_qty_button(self, btn_text):
        """Kiểm tra nếu nút là nút tăng giảm số lượng (- / +)"""
        if not btn_text:
            return False
        t = btn_text.strip()
        if t in ["-", "+", "➖", "➕", "--", "++", "<", ">", "<<", ">>"]:
            return True
        if re.fullmatch(r'[-+➖➕]+', t):
            return True
        return False

    def _is_confirm_button(self, btn_text):
        """
        Kiểm tra nếu nút là nút Xác nhận thêm sản phẩm vào giỏ
        (VD: '✅ Thêm 1 sản phẩm', 'Thêm vào giỏ', 'Xác nhận', 'Hoàn tất')
        """
        if not btn_text:
            return False
        if self._is_cancel_button(btn_text) or self._is_qty_button(btn_text):
            return False

        low = btn_text.strip().lower()

        # 1. Chứa 'thêm' kết hợp với từ khóa sản phẩm / giỏ / món
        if "thêm" in low and any(w in low for w in ["sản phẩm", "sp", "vào giỏ", "giỏ hàng", "món", "hang", "hàng"]):
            return True

        # 2. Bắt đầu bằng icon check/tick và có chữ 'thêm' (VD: '✅ Thêm 1 sản phẩm', '✓ Thêm...')
        if any(ic in btn_text for ic in ["✅", "✔", "✓", "☑"]) and "thêm" in low:
            return True

        # 3. Mẫu 'thêm <số lượng>' (VD: 'Thêm 1', 'Thêm 2')
        if re.search(r'thêm\s+\d+', low):
            return True

        # 4. Từ khóa xác nhận rõ ràng
        if any(ck in low for ck in ["xác nhận thêm", "xác nhận", "hoàn tất"]):
            return True

        return False

    def _find_confirm_button(self, buttons):
        """Tìm nút xác nhận thêm sản phẩm trong danh sách buttons"""
        for row in buttons:
            for btn in row:
                b_txt = (btn.text or "").strip()
                if self._is_confirm_button(b_txt):
                    return btn
        return None

    def _find_best_variant_button(self, buttons, target_variant=""):
        """
        Quét danh sách các nút phân loại của sản phẩm:
        - Bỏ qua tuyệt đối các nút mang ý nghĩa Hủy/Cancel/Quay lại/Đóng.
        - Bỏ qua các nút tăng giảm số lượng (- / +).
        - Bỏ qua các nút Xác nhận thêm sản phẩm.
        - Tìm nút trùng hoặc gần giống nhất với tên phân loại đã nhập.
        - Nếu không quét thấy hoặc không nhập phân loại: Tự động chọn nút phân loại đầu tiên hợp lệ!
        """
        valid_btns = []

        for row in buttons:
            for btn in row:
                b_txt = (btn.text or "").strip()
                if not b_txt:
                    continue
                # Bỏ qua nút Hủy / Cancel
                if self._is_cancel_button(b_txt):
                    continue
                # Bỏ qua nút tăng giảm số lượng
                if self._is_qty_button(b_txt):
                    continue
                # Bỏ qua nút xác nhận thêm sản phẩm (để bấm ở bước xác nhận riêng)
                if self._is_confirm_button(b_txt):
                    continue
                valid_btns.append(btn)

        if not valid_btns:
            return None, "NO_VALID_BUTTONS"

        target = (target_variant or "").strip().lower()
        if target:
            # 1. So khớp chính xác hoặc chứa toàn bộ chuỗi
            for btn in valid_btns:
                b_txt = btn.text.strip().lower()
                if target == b_txt or target in b_txt or b_txt in target:
                    return btn, "MATCH_EXACT"

            # 2. So khớp theo các từ khóa tương đồng (word overlap)
            target_words = set(re.findall(r'\w+', target))
            best_btn = None
            best_score = 0
            for btn in valid_btns:
                b_words = set(re.findall(r'\w+', btn.text.strip().lower()))
                common = target_words.intersection(b_words)
                score = len(common)
                if score > best_score:
                    best_score = score
                    best_btn = btn

            if best_btn and best_score > 0:
                return best_btn, "MATCH_SIMILAR"

        # 3. Không trùng khớp hoặc không nhập => Chọn nút phân loại đầu tiên
        return valid_btns[0], "FIRST_CHOICE"

    async def _execute_addtocart(self, client, bot_entity, cmd_text):
        """Thực thi thêm giỏ hàng 1 lần duy nhất (không lặp lại/không retry)"""
        if self.should_stop:
            return False, "Tiến trình bị dừng"
        return await self._run_single_addtocart(client, bot_entity, cmd_text)

    async def _run_single_addtocart(self, client, bot_entity, cmd_text):
        """
        Chạy một chu trình thêm giỏ hàng:
        1. Gửi lệnh /addtocart
        2. Chọn phân loại sản phẩm (nếu có yêu cầu hoặc chưa chọn)
        3. Bấm nút XÁC NHẬN thêm sản phẩm (VD: '✅ Thêm 1 sản phẩm')
        4. Chờ bot trả về 'KẾT QUẢ THÊM GIỎ'
        """
        timeout = int(self.config.get("timeout_step", 50))
        target_variant = self.config.get("product_variant", "").strip()

        last_sent = await client.send_message(bot_entity, cmd_text)
        start_time = time.time()
        variant_clicked = False
        confirm_clicked = False
        last_confirm_click_time = 0

        while time.time() - start_time < timeout:
            if self.should_stop:
                return False, "Tiến trình bị dừng"

            messages = await client.get_messages(bot_entity, limit=4)
            for m in messages:
                if m.out:
                    continue

                txt = m.text or ""

                # 1. Kiểm tra nếu đã có kết quả thêm giỏ
                if "KẾT QUẢ THÊM GIỎ" in txt:
                    success_match = re.search(r'Thành công:\s*\*?(\d+)\*?', txt, re.IGNORECASE)
                    fail_match = re.search(r'Lỗi:\s*\*?(\d+)\*?', txt, re.IGNORECASE)
                    s_count = int(success_match.group(1)) if success_match else 0
                    f_count = int(fail_match.group(1)) if fail_match else 0

                    if s_count > 0:
                        lines = [ln.strip() for ln in txt.split("\n") if "x1" in ln or "x2" in ln or "x3" in ln]
                        item_name = lines[0] if lines else f"Thành công {s_count} món"
                        return True, item_name
                    else:
                        return False, f"Thêm giỏ báo lỗi (Thành công: {s_count}, Lỗi: {f_count})"

                # 2. Kiểm tra nếu bot báo lỗi
                if "❌ Lỗi:" in txt or "Không đăng nhập được" in txt or "Cookie đăng nhập đã hết hạn" in txt:
                    return False, txt.split("\n")[0]

                if "Bạn đang có phiên chạy dở" in txt:
                    return False, "Kẹt phiên chạy dở"

                # 3. Quét và xử lý các nút inline của bot
                if m.buttons and "KẾT QUẢ THÊM GIỎ" not in txt:
                    confirm_btn = self._find_confirm_button(m.buttons)
                    variant_btn, match_type = self._find_best_variant_button(m.buttons, target_variant)

                    # TRƯỜNG HỢP A: Có cấu hình phân loại cụ thể và cần bấm chọn phân loại đó trước
                    need_select_variant = (
                        bool(target_variant) and 
                        not variant_clicked and 
                        variant_btn is not None and 
                        match_type in ["MATCH_EXACT", "MATCH_SIMILAR"]
                    )

                    if need_select_variant:
                        self.log(f"🛒 Quét thấy phân loại khớp '{target_variant}': Bấm chọn '{variant_btn.text}'...", "info")
                        try:
                            await variant_btn.click()
                            variant_clicked = True
                        except Exception as _b_err:
                            self.log(f"⚠️ Lỗi bấm nút phân loại: {_b_err}", "warning")
                        await asyncio.sleep(2)
                        break

                    # TRƯỜNG HỢP B: Đã có nút Xác nhận thêm sản phẩm (VD: '✅ Thêm 1 sản phẩm')
                    if confirm_btn:
                        now = time.time()
                        # Bấm nút xác nhận nếu chưa bấm, hoặc thử lại sau 6 giây nếu bot chưa phản hồi
                        if not confirm_clicked or (now - last_confirm_click_time > 6):
                            self.log(f"🔘 Bấm nút xác nhận thêm sản phẩm: '{confirm_btn.text}'...", "info")
                            try:
                                await confirm_btn.click()
                                confirm_clicked = True
                                last_confirm_click_time = now
                            except Exception as _c_err:
                                self.log(f"⚠️ Lỗi bấm nút xác nhận thêm sản phẩm: {_c_err}", "warning")
                            await asyncio.sleep(2)
                            break

                    # TRƯỜNG HỢP C: Chưa có nút xác nhận và chưa bấm phân loại, nhưng có các nút phân loại để chọn
                    if not confirm_btn and not variant_clicked and variant_btn:
                        self.log(f"📦 Bấm chọn phân loại sản phẩm: '{variant_btn.text}'...", "info")
                        try:
                            await variant_btn.click()
                            variant_clicked = True
                        except Exception as _v_err:
                            self.log(f"⚠️ Lỗi bấm nút phân loại: {_v_err}", "warning")
                        await asyncio.sleep(2)
                        break

            await asyncio.sleep(1.5)

        return False, f"Hết thời gian chờ phản hồi thêm giỏ ({timeout}s)"

    # -------------------------------------------------------------------------
    # BỘ XỬ LÝ LỆNH 3: /diachi hoặc /addressnew (WIZARD TOÀN DIỆN)
    # -------------------------------------------------------------------------
    async def _execute_address_wizard(self, client, bot_entity, cmd_text):
        max_retries = int(self.config.get("max_area_retries", 3))

        for attempt in range(1, max_retries + 1):
            if self.should_stop:
                return False, "Tiến trình bị dừng"

            if attempt > 1:
                self.log(f"🔄 Thử lại Lệnh 3 (Lần {attempt}/{max_retries})...", "warning")

            success, reason_or_result = await self._run_single_address_flow(client, bot_entity, cmd_text)

            if success:
                return True, reason_or_result

            # Kiểm tra nếu là lỗi tìm kiếm khu vực => cần Hủy, delay 8s và làm lại
            if reason_or_result == "AREA_SEARCH_ERROR":
                self.log(f"⚠️ Phát hiện 'Lỗi tìm kiếm khu vực' ➔ Đang bấm Hủy và delay 8 giây...", "warning")
                await self._click_cancel_button(client, bot_entity)
                await asyncio.sleep(8)
                continue
            else:
                return False, reason_or_result

        return False, f"Thất bại sau {max_retries} lần thử cấu hình địa chỉ"

    async def _click_cancel_button(self, client, bot_entity):
        """Bấm nút Hủy trên tin nhắn bot nếu có, hoặc gửi /huy"""
        try:
            msgs = await client.get_messages(bot_entity, limit=4)
            for m in msgs:
                if not m.out and m.buttons:
                    for row in m.buttons:
                        for btn in row:
                            if "hủy" in btn.text.lower() or "cancel" in btn.text.lower():
                                await btn.click()
                                await asyncio.sleep(1)
                                return True
            # Nếu không tìm thấy nút, gửi /stop hoặc /huy
            await client.send_message(bot_entity, "/stop")
            await asyncio.sleep(1)
            return True
        except Exception as e:
            self.log(f"Lỗi khi bấm hủy: {e}", "warning")
        return False

    async def _run_single_address_flow(self, client, bot_entity, cmd_text):
        """Chạy một chu trình đầy đủ của wizard địa chỉ"""
        timeout = int(self.config.get("timeout_step", 60))
        last_sent = await client.send_message(bot_entity, cmd_text)
        wizard_msg_id = None
        start_time = time.time()

        # =====================================================================
        # GIAI ĐOẠN 0: CHỜ BOT TRẢ VỀ HOẶC MỞ WIZARD
        # =====================================================================
        phase = "WAIT_INITIAL"
        step1_sent = False
        step2_clicked = False
        step2_name_sent = False
        step3_phone_handled = False
        step4_clicked = False
        step4_addr_sent = False

        target_area = self.config.get("address_area", "").strip() or "Phường Tràng Tiền, Hoàn Kiếm, Hà Nội"
        target_name = self.config.get("address_name", "").strip() or "Nguyễn Văn Trung"
        target_street = self.config.get("address_street", "").strip() or "12 Tràng Tiền"
        phone_mode = self.config.get("phone_mode", "auto")
        custom_phone = self.config.get("custom_phone", "").strip()

        while time.time() - start_time < timeout:
            if self.should_stop:
                return False, "Tiến trình bị dừng"

            # Lấy 4 tin nhắn gần nhất (cả tin nhắn mới lẫn tin nhắn bot sửa đổi)
            messages = await client.get_messages(bot_entity, limit=4)
            for m in messages:
                if m.out:
                    continue

                txt = m.text or ""

                # 1. Trường hợp bot báo THÊM ĐỊA CHỈ THÀNH CÔNG ngay lập tức!
                if "THÊM ĐỊA CHỈ THÀNH CÔNG!" in txt:
                    # Trích xuất thông tin người nhận
                    addr_summary = [ln.strip() for ln in txt.split("\n") if ln.strip() and not ln.startswith("✅")]
                    summary_text = " | ".join(addr_summary[:3]) if addr_summary else "Đã thêm địa chỉ thành công"
                    return True, summary_text

                # 2. Trường hợp lỗi đăng nhập / hết hạn cookie
                if "Không đăng nhập được" in txt or "Cookie đăng nhập đã hết hạn" in txt or "SPC_F chưa được chấp nhận" in txt:
                    return False, txt.split("\n")[0]

                # 3. Kiểm tra lỗi tìm kiếm khu vực ở Bước 1
                if "Lỗi tìm kiếm: Chưa tra cứu được khu vực" in txt:
                    return False, "AREA_SEARCH_ERROR"

                # 4. BƯỚC 1: BƯỚC NHẬP KHU VỰC
                if "BƯỚC 1: NHẬP KHU VỰC" in txt and not step1_sent:
                    wizard_msg_id = m.id
                    self.log(f"📍 Bot yêu cầu BƯỚC 1: Nhập khu vực ➔ Gửi: '{target_area}'", "info")
                    await client.send_message(bot_entity, target_area)
                    step1_sent = True
                    await asyncio.sleep(2)
                    break

                # 5. BƯỚC 1 KẾT QUẢ: Bot hiện danh sách các nút kết quả khu vực
                if ("Chọn khu vực phù hợp:" in txt or "Đã chọn:" not in txt and m.buttons and len(m.buttons) >= 2) and step1_sent and not step2_clicked:
                    # Tìm nút phù hợp nhất
                    clicked = False
                    for row in m.buttons:
                        for btn in row:
                            b_text = btn.text.strip()
                            if b_text.startswith("1.") or "Tràng Tiền" in b_text or target_area.split(",")[0].strip() in b_text:
                                self.log(f"👉 Bấm chọn nút khu vực: '{b_text}'", "info")
                                await btn.click()
                                clicked = True
                                await asyncio.sleep(2)
                                break
                        if clicked:
                            break
                    if not clicked and m.buttons:
                        # Mặc định bấm nút đầu tiên nếu không khớp
                        first_btn = m.buttons[0][0]
                        self.log(f"👉 Bấm chọn khu vực kết quả đầu tiên: '{first_btn.text}'", "info")
                        await first_btn.click()
                        await asyncio.sleep(2)
                    break

                # 6. BƯỚC 2: TÊN NGƯỜI NHẬN (Hỏi Random hay Tự nhập)
                if "BƯỚC 2: TÊN NGƯỜI NHẬN" in txt and not step2_clicked:
                    self.log("👤 Bot yêu cầu BƯỚC 2: Tên người nhận ➔ Bấm nút 'Tự nhập Tên'...", "info")
                    clicked_name = False
                    if m.buttons:
                        for row in m.buttons:
                            for btn in row:
                                if "tự nhập tên" in btn.text.lower():
                                    await btn.click()
                                    clicked_name = True
                                    step2_clicked = True
                                    await asyncio.sleep(2)
                                    break
                            if clicked_name:
                                break
                    break

                # 7. Bot yêu cầu chat Tên người nhận vào
                if ("Tên người nhận" in txt or "chat Tên" in txt or step2_clicked) and not step2_name_sent and "BƯỚC 2: SỐ ĐIỆN THOẠI" not in txt:
                    self.log(f"✍️ Gửi Tên người nhận: '{target_name}'", "info")
                    await client.send_message(bot_entity, target_name)
                    step2_name_sent = True
                    await asyncio.sleep(2)
                    break

                # 8. BƯỚC 3: SỐ ĐIỆN THOẠI (Kiểm tra acc có SĐT hay Không tìm thấy)
                if "BƯỚC 2: SỐ ĐIỆN THOẠI" in txt or "SĐT Acc:" in txt or ("SỐ ĐIỆN THOẠI" in txt and "BƯỚC 3: ĐỊA CHỈ" not in txt):
                    if not step3_phone_handled:
                        # Kiểm tra xem có tìm thấy SĐT Acc không
                        has_acc_phone = "Không tìm thấy" not in txt and "SĐT Acc:" in txt

                        if phone_mode == "random":
                            should_random = True
                        elif phone_mode == "custom":
                            should_random = False
                        else:  # auto
                            should_random = not has_acc_phone

                        if not should_random and has_acc_phone and phone_mode != "custom":
                            # Bấm lấy SĐT Acc
                            self.log("📞 Tài khoản còn SĐT ➔ Bấm nút 'Lấy SĐT Acc'...", "info")
                            if m.buttons:
                                for row in m.buttons:
                                    for btn in row:
                                        if "lấy sđt" in btn.text.lower():
                                            await btn.click()
                                            step3_phone_handled = True
                                            await asyncio.sleep(2)
                                            break
                        else:
                            # Tự nhập SĐT
                            self.log("📞 Bấm nút 'Tự nhập SĐT'...", "info")
                            if m.buttons:
                                for row in m.buttons:
                                    for btn in row:
                                        if "tự nhập sđt" in btn.text.lower() or "tự nhập" in btn.text.lower():
                                            await btn.click()
                                            await asyncio.sleep(2)
                                            # Tạo số điện thoại
                                            phone_to_send = custom_phone if (custom_phone and phone_mode == "custom") else generate_random_vn_phone()
                                            self.log(f"📱 Gửi Số điện thoại: '{phone_to_send}'", "info")
                                            await client.send_message(bot_entity, phone_to_send)
                                            step3_phone_handled = True
                                            await asyncio.sleep(2)
                                            break
                        break

                # 9. BƯỚC 4: ĐỊA CHỈ CHI TIẾT
                if ("BƯỚC 3: ĐỊA CHỈ CHI TIẾT" in txt or "ĐỊA CHỈ CHI TIẾT" in txt) and not step4_clicked:
                    self.log("🏠 Bot yêu cầu BƯỚC 4: Địa chỉ chi tiết ➔ Bấm nút 'Tự nhập'...", "info")
                    if m.buttons:
                        for row in m.buttons:
                            for btn in row:
                                if "tự nhập" in btn.text.lower() and "random" not in btn.text.lower():
                                    await btn.click()
                                    step4_clicked = True
                                    await asyncio.sleep(2)
                                    break
                    break

                # 10. Gửi text địa chỉ chi tiết
                if step4_clicked and not step4_addr_sent and "THÊM ĐỊA CHỈ THÀNH CÔNG" not in txt:
                    self.log(f"🏠 Gửi Địa chỉ chi tiết: '{target_street}'", "info")
                    await client.send_message(bot_entity, target_street)
                    step4_addr_sent = True
                    await asyncio.sleep(3)
                    break

            await asyncio.sleep(1.5)

        return False, f"Hết thời gian chờ hoàn tất Wizard địa chỉ ({timeout}s)"

# Khởi tạo singleton manager
dks_mgr = DangKyShopeeManager()
