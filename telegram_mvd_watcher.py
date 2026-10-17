# -*- coding: utf-8 -*-
"""
TELEGRAM MVD WATCHER - TỰ ĐỘNG THEO DÕI VÀ BÁO MÃ VẬN ĐƠN SHOPEE 24/7
=====================================================================
Chức năng chính:
1. Tự động quét định kỳ danh sách đơn hàng từ draft.json / Supabase.
2. Phát hiện ngay lập tức khi đơn hàng "NHẢY MÃ VẬN ĐƠN" (từ chưa có -> có MVĐ mới).
3. Gửi thông báo tức thì về Telegram (kèm âm thanh, thông tin chi tiết, link tra cứu vận đơn).
4. Cập nhật mã vận đơn mới thẳng vào draft.json & Supabase để web sheet luôn đồng bộ.
5. Bot phản hồi lệnh qua Telegram: /start, /check, /mvd, /pending, /status, /auto_on, /auto_off.
"""

import os
import sys
import json
import time
import ssl
import threading
import datetime
import urllib.request
import urllib.parse
import urllib.error

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DRAFT_FILE = os.path.join(DIRECTORY, "draft.json")
TELEGRAM_CONFIG_FILE = os.path.join(DIRECTORY, "telegram_config.json")
NOTIFIED_MVD_FILE = os.path.join(DIRECTORY, "notified_mvd.json")
VAULT_FILE = os.path.join(DIRECTORY, "cookie_vault.json")

# SSL Context
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# Lock đồng bộ ghi file
file_lock = threading.Lock()

def get_carrier_tracking_url(carrier, tracking_no):
    """Tạo đường link tra cứu hành trình bưu cục trực tiếp"""
    if not tracking_no:
        return ""
    c_lower = (carrier or '').lower()
    t_clean = tracking_no.strip()
    if 'spx' in c_lower or 'shopee express' in c_lower:
        return f"https://spx.vn/track?{t_clean}"
    elif 'ghn' in c_lower or 'giao hàng nhanh' in c_lower:
        return f"https://ghn.vn/blogs/trang-thai-don-hang?order_code={t_clean}"
    elif 'j&t' in c_lower or 'jt' in c_lower:
        return f"https://jtexpress.vn/vi/tracking?billcode={t_clean}"
    elif 'viettel' in c_lower:
        return f"https://viettelpost.vn/tra-cuu-hanh-trinh-don/?order_number={t_clean}"
    elif 'ninja' in c_lower:
        return f"https://www.ninjavox.com/vietnam/tracking?id={t_clean}"
    return f"https://spx.vn/track?{t_clean}"


def load_telegram_config():
    """Tải cấu hình Telegram từ file"""
    default_cfg = {
        "bot_token": "",
        "chat_id": "",
        "enabled": False,
        "auto_check_mvd": True,
        "check_interval_seconds": 180,
        "notify_new_mvd": True,
        "notify_completed": True,
        "notify_cancelled": True,
        "last_check_time": "",
        "total_mvd_notified": 0
    }
    if os.path.exists(TELEGRAM_CONFIG_FILE):
        try:
            with open(TELEGRAM_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                default_cfg.update(data)
        except Exception as e:
            print(f"[TelegramMVD] Lỗi đọc config: {e}")
    return default_cfg


def save_telegram_config(cfg):
    """Lưu cấu hình Telegram an toàn"""
    with file_lock:
        try:
            with open(TELEGRAM_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[TelegramMVD] Lỗi lưu config: {e}")
            return False


def load_notified_mvd():
    """Tải danh sách các đơn đã từng thông báo MVĐ để tránh báo trùng lặp"""
    if os.path.exists(NOTIFIED_MVD_FILE):
        try:
            with open(NOTIFIED_MVD_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_notified_mvd(notified_dict):
    """Lưu danh sách đã thông báo"""
    with file_lock:
        try:
            with open(NOTIFIED_MVD_FILE, 'w', encoding='utf-8') as f:
                json.dump(notified_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[TelegramMVD] Lỗi lưu notified_mvd.json: {e}")


def load_draft_data():
    """Tải danh sách đơn hàng hiện tại từ draft.json"""
    if os.path.exists(DRAFT_FILE):
        try:
            with open(DRAFT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[TelegramMVD] Lỗi đọc draft.json: {e}")
    return {"rows": [], "count": 0, "updated_at": "", "blocked_cancelled_orders": []}


def save_draft_data(draft_data):
    """Lưu cập nhật lại vào draft.json"""
    with file_lock:
        try:
            with open(DRAFT_FILE, 'w', encoding='utf-8') as f:
                json.dump(draft_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[TelegramMVD] Lỗi ghi draft.json: {e}")
            return False


def send_telegram_raw(token, chat_id, text, reply_markup=None):
    """Gửi tin nhắn Telegram qua Bot API chính thức"""
    if not token or not chat_id:
        return False, "Thiếu Bot Token hoặc Chat ID"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': False
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup

    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=12) as res:
            res_json = json.loads(res.read().decode('utf-8'))
            if res_json.get('ok'):
                return True, "Thành công"
            return False, res_json.get('description', 'Lỗi không xác định')
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='replace')
        return False, f"HTTP {e.code}: {err_msg}"
    except Exception as e:
        return False, str(e)


def format_new_mvd_message(order, old_mvd=""):
    """Tạo mẫu tin nhắn thông báo NHẢY MÃ VẬN ĐƠN MỚI cực kỳ đẹp mắt và nổi bật"""
    sn = order.get('order_sn') or order.get('order_id') or '--'
    mvd = order.get('tracking_no') or 'Chưa có MVĐ'
    carrier = order.get('carrier') or 'SPX Express'
    status = order.get('status_desc') or order.get('status_badge_text') or 'Đang xử lý / Chờ giao hàng'
    name = order.get('receiver_name') or '--'
    phone = order.get('receiver_phone') or '--'
    addr = order.get('receiver_address') or '--'
    prod = order.get('product_name') or '--'
    cod = order.get('cod_amount') or '0 đ'
    pay_st = order.get('payment_status') or 'Chưa thanh toán'
    now_str = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    shop = order.get('note_name') or ''
    if not shop and order.get('account'):
        shop = order['account'].get('username') or order['account'].get('phone') or ''

    msg = f"🚀 <b>THÔNG BÁO: ĐÃ NHẢY MÃ VẬN ĐƠN MỚI!</b>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🚚 <b>Mã vận đơn (MVĐ):</b> <code>{mvd}</code>\n"
    msg += f"🏢 <b>Đơn vị vận chuyển:</b> <b>{carrier}</b>\n"
    msg += f"🔖 <b>Mã đơn hàng:</b> <code>{sn}</code>\n"
    msg += f"⚡ <b>Trạng thái:</b> <b>{status}</b>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"👤 <b>Người nhận:</b> <b>{name}</b>\n"
    msg += f"📞 <b>SĐT nhận:</b> <code>{phone}</code>\n"
    msg += f"📍 <b>Địa chỉ:</b> {addr}\n"
    msg += f"🛍️ <b>Sản phẩm:</b> {prod}\n"
    msg += f"💰 <b>COD / Thu hộ:</b> <b>{cod}</b> <i>({pay_st})</i>\n"
    if shop:
        msg += f"🏪 <b>Shop / Tài khoản:</b> <code>{shop}</code>\n"
    msg += f"⏰ <b>Thời điểm nhảy MVĐ:</b> {now_str}\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
    track_url = get_carrier_tracking_url(carrier, mvd)
    if track_url:
        msg += f"🔗 <a href=\"{track_url}\">Nhấn vào đây để xem trực tiếp hành trình đơn hàng</a>\n\n"
    msg += f"🤖 <i>Shopee Auto MVĐ Tracker (24/7 Engine)</i>"

    # Tạo nút bấm tra cứu nhanh
    reply_markup = None
    if track_url:
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": f"🚚 Tra cứu hành trình ({carrier})", "url": track_url}
                ]
            ]
        }

    return msg, reply_markup


class TelegramMVDWatcher:
    """
    Bộ máy theo dõi và kiểm tra tự động mã vận đơn Shopee
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TelegramMVDWatcher, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.running = False
        self.watcher_thread = None
        self.bot_thread = None
        self.last_check_time = None
        self.last_check_status = "Chưa chạy"
        self.is_checking_now = False
        self.last_update_id = 0

    def start(self):
        """Khởi động tiến trình chạy ngầm 24/7"""
        if self.running:
            return
        self.running = True

        # 1. Thread định kỳ quét nhảy mã vận đơn
        self.watcher_thread = threading.Thread(target=self._watcher_loop, daemon=True, name="MVDWatcherLoop")
        self.watcher_thread.start()

        # 2. Thread lắng nghe lệnh chat Telegram Bot (/check, /mvd, /status, etc.)
        self.bot_thread = threading.Thread(target=self._bot_polling_loop, daemon=True, name="MVDBotPolling")
        self.bot_thread.start()

        print("[TelegramMVD] 🚀 Đã kích hoạt hệ thống Auto Báo Mã Vận Đơn Shopee 24/7!")

    def stop(self):
        """Dừng tiến trình"""
        self.running = False
        print("[TelegramMVD] ⏹️ Đã dừng hệ thống Auto Báo MVĐ.")

    def get_status(self):
        """Lấy thông tin trạng thái phục vụ hiển thị lên Web UI hoặc Bot"""
        cfg = load_telegram_config()
        notified = load_notified_mvd()
        draft = load_draft_data()
        rows = draft.get('rows', [])

        has_mvd_count = sum(1 for r in rows if r.get('tracking_no') and r.get('tracking_no') not in ['Chưa có MVĐ', 'N/A', ''])
        waiting_count = len(rows) - has_mvd_count

        return {
            "running": self.running,
            "enabled": cfg.get("enabled", False),
            "auto_check_mvd": cfg.get("auto_check_mvd", True),
            "bot_configured": bool(cfg.get("bot_token") and cfg.get("chat_id")),
            "check_interval_seconds": cfg.get("check_interval_seconds", 180),
            "last_check_time": self.last_check_time or cfg.get("last_check_time", "Chưa quét lần nào"),
            "last_check_status": self.last_check_status,
            "is_checking_now": self.is_checking_now,
            "total_orders": len(rows),
            "orders_has_mvd": has_mvd_count,
            "orders_waiting_mvd": waiting_count,
            "total_notified": len(notified)
        }

    def trigger_check_now(self):
        """Kích hoạt quét ngay lập tức từ giao diện Web hoặc lệnh Telegram"""
        if self.is_checking_now:
            return False, "Hệ thống đang trong tiến trình quét, vui lòng đợi vài giây!"
        th = threading.Thread(target=self.run_check_cycle, kwargs={"force_all": True}, daemon=True)
        th.start()
        return True, "Đã bắt đầu tiến trình quét mã vận đơn mới!"

    def run_check_cycle(self, force_all=False):
        """
        Tiến hành 1 chu kỳ quét toàn bộ đơn hàng để phát hiện nhảy MVĐ
        """
        if self.is_checking_now:
            return
        self.is_checking_now = True
        self.last_check_status = "Đang quét..."
        t0 = time.time()

        try:
            cfg = load_telegram_config()
            bot_token = cfg.get('bot_token', '').strip()
            chat_id = cfg.get('chat_id', '').strip()
            is_enabled = cfg.get('enabled', False)
            notify_mvd = cfg.get('notify_new_mvd', True)

            draft_data = load_draft_data()
            rows = draft_data.get('rows', [])
            if not rows:
                self.last_check_status = "Không có đơn hàng nào trong sheet"
                return

            notified_dict = load_notified_mvd()

            # Nhóm các đơn theo Cookie SPC_ST để giảm thiểu số lần gọi API
            cookie_groups = {} # cookie -> list of orders
            for row in rows:
                # Bỏ qua các đơn đã hoàn thành hoặc hủy nếu không ép quét
                st_lower = (row.get('status_desc') or '').lower()
                if not force_all and ('hoàn thành' in st_lower or 'giao thành công' in st_lower or 'đã hủy' in st_lower):
                    continue

                # Nếu đơn đã có MVĐ và đã được thông báo trước đó, không cần quét lại trừ khi force_all
                current_mvd = (row.get('tracking_no') or '').strip()
                row_key = str(row.get('order_sn') or row.get('order_id') or row.get('id'))
                if not force_all and current_mvd and current_mvd not in ['Chưa có MVĐ', 'N/A'] and row_key in notified_dict:
                    continue

                cookie = (row.get('cookie_raw') or row.get('spc_st') or '').strip()
                if not cookie or len(cookie) < 20:
                    continue

                if cookie not in cookie_groups:
                    cookie_groups[cookie] = {
                        "note_name": row.get('note_name') or '',
                        "rows": []
                    }
                cookie_groups[cookie]["rows"].append(row)

            if not cookie_groups:
                self.last_check_status = "Tất cả đơn đều đã có MVĐ hoặc không có cookie"
                return

            # Nhập hàm extract_cookie_orders từ server.py
            try:
                import server
                extract_fn = server.extract_cookie_orders
            except Exception as e:
                self.last_check_status = f"Lỗi import server: {e}"
                print(f"[TelegramMVD] Lỗi import extract_cookie_orders: {e}")
                return

            new_mvd_jumped = []
            updated_any = False

            # Quét từng cookie tài khoản
            for cookie, grp in cookie_groups.items():
                try:
                    res = extract_fn(cookie, note_name=grp["note_name"], order_limit=30)
                    fetched_orders = res.get('orders', []) or []
                    if not fetched_orders:
                        continue

                    # So khớp từng đơn trong nhóm
                    for row in grp["rows"]:
                        oid = str(row.get('order_id') or '')
                        osn = str(row.get('order_sn') or '')
                        row_key = osn or oid or str(row.get('id'))

                        # Tìm đơn khớp
                        match = None
                        for fo in fetched_orders:
                            if (fo.get('order_id') and str(fo['order_id']) == oid) or (fo.get('order_sn') and fo['order_sn'] == osn):
                                match = fo
                                break

                        if not match and fetched_orders:
                            # Nếu chỉ có 1 đơn trong tài khoản
                            if len(grp["rows"]) == 1 and len(fetched_orders) == 1:
                                match = fetched_orders[0]

                        if match:
                            old_mvd = (row.get('tracking_no') or '').strip()
                            new_mvd = (match.get('tracking_no') or '').strip()

                            # Kiểm tra xem có phải "NHẢY MÃ VẬN ĐƠN" không
                            # Điều kiện:
                            # 1. new_mvd có giá trị hợp lệ (> 3 ký tự, không phải 'Chưa có MVĐ')
                            # 2. VÀ trước đó old_mvd rỗng HOẶC chưa từng thông báo mã này trong notified_dict
                            is_valid_new_mvd = bool(new_mvd and len(new_mvd) > 3 and new_mvd not in ['Chưa có MVĐ', 'N/A', '--'])
                            had_no_mvd = not old_mvd or old_mvd in ['Chưa có MVĐ', 'N/A', '--']
                            never_notified = (row_key not in notified_dict) or (notified_dict[row_key].get('tracking_no') != new_mvd)

                            # Cập nhật thông tin đơn hàng trong sheet
                            row['tracking_no'] = new_mvd
                            row['has_tracking'] = is_valid_new_mvd
                            if match.get('carrier'):
                                row['carrier'] = match['carrier']
                            if match.get('status_desc'):
                                row['status_desc'] = match['status_desc']
                            if match.get('status_badge_text'):
                                row['status_badge_text'] = match['status_badge_text']
                            if match.get('status_badge_type'):
                                row['status_badge_type'] = match['status_badge_type']
                            if match.get('driver_phone'):
                                row['driver_phone'] = match['driver_phone']
                            if match.get('timeline'):
                                row['timeline'] = match['timeline']
                            row['last_check'] = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                            updated_any = True

                            # Nếu thỏa mãn điều kiện nhảy mã vận đơn mới
                            if is_valid_new_mvd and (had_no_mvd or never_notified):
                                new_mvd_jumped.append({
                                    "order": row,
                                    "old_mvd": old_mvd,
                                    "row_key": row_key
                                })
                                # Lưu ngay vào danh sách đã báo
                                notified_dict[row_key] = {
                                    "tracking_no": new_mvd,
                                    "carrier": row.get('carrier', 'SPX Express'),
                                    "order_sn": osn or oid,
                                    "notified_at": datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                                }

                    # Giãn cách 1-2 giây giữa các cookie để giữ an toàn cho IP
                    time.sleep(1.2)

                except Exception as e:
                    print(f"[TelegramMVD] Lỗi quét cookie: {e}")

            # Lưu lại draft.json nếu có thay đổi
            if updated_any:
                draft_data['updated_at'] = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                save_draft_data(draft_data)
                save_notified_mvd(notified_dict)

                # Đồng bộ lên Supabase nếu có
                try:
                    import server
                    if server._is_supabase_configured():
                        sb = server.get_supabase()
                        if sb:
                            for item in new_mvd_jumped:
                                o = item["order"]
                                sb_id = str(o.get('order_sn') or o.get('order_id') or o.get('id'))
                                sb.table('orders').update({
                                    'tracking_no': o.get('tracking_no', ''),
                                    'carrier': o.get('carrier', ''),
                                    'status_desc': o.get('status_desc', ''),
                                    'has_tracking': True,
                                    'last_check': o.get('last_check', '')
                                }).eq('order_sn', sb_id).execute()
                except Exception as e:
                    print(f"[TelegramMVD] Lỗi đồng bộ Supabase: {e}")

            # Gửi thông báo Telegram cho các đơn vừa nhảy MVĐ
            notified_count = 0
            if new_mvd_jumped and is_enabled and notify_mvd and bot_token and chat_id:
                for item in new_mvd_jumped:
                    ord_obj = item["order"]
                    msg, markup = format_new_mvd_message(ord_obj, item["old_mvd"])
                    ok, res_txt = send_telegram_raw(bot_token, chat_id, msg, reply_markup=markup)
                    if ok:
                        notified_count += 1
                        print(f"[TelegramMVD] ✅ ĐÃ BẮN TELEGRAM: Đơn {ord_obj.get('order_sn')} nhảy MVĐ -> {ord_obj.get('tracking_no')}")
                    else:
                        print(f"[TelegramMVD] ❌ Lỗi gửi Telegram: {res_txt}")
                    time.sleep(0.5)

            duration = round(time.time() - t0, 1)
            now_str = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
            self.last_check_time = now_str
            self.last_check_status = f"Quét xong ({duration}s). Nhảy {len(new_mvd_jumped)} MVĐ mới, đã bắn {notified_count} tin."
            print(f"[TelegramMVD] 🏁 Hoàn thành chu kỳ quét ({duration}s): {len(new_mvd_jumped)} MVĐ mới.")

            # Cập nhật cấu hình
            cfg['last_check_time'] = now_str
            cfg['total_mvd_notified'] = len(notified_dict)
            save_telegram_config(cfg)

        except Exception as e:
            self.last_check_status = f"Lỗi: {e}"
            print(f"[TelegramMVD] Lỗi ngoại lệ trong chu kỳ quét: {e}")
        finally:
            self.is_checking_now = False

    def _watcher_loop(self):
        """Vòng lặp ngầm 24/7 kiểm tra định kỳ theo thời gian cài đặt"""
        # Nghỉ 10s sau khi server khởi động trước khi quét lần đầu
        time.sleep(10)

        while self.running:
            try:
                cfg = load_telegram_config()
                is_enabled = cfg.get('enabled', False)
                auto_check = cfg.get('auto_check_mvd', True)
                interval = max(60, int(cfg.get('check_interval_seconds', 180)))

                if is_enabled and auto_check and cfg.get('bot_token'):
                    self.run_check_cycle(force_all=False)
                else:
                    self.last_check_status = "Đang tạm dừng (Tính năng Telegram hoặc Auto check đang tắt)"

                # Chờ đến chu kỳ tiếp theo (chia nhỏ giấc ngủ để có thể dừng ngay lập tức khi stop)
                for _ in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                print(f"[TelegramMVD] Lỗi trong watcher_loop: {e}")
                time.sleep(10)

    def _bot_polling_loop(self):
        """Vòng lặp lắng nghe lệnh từ người dùng trên Telegram (Long Polling)"""
        while self.running:
            try:
                cfg = load_telegram_config()
                token = cfg.get('bot_token', '').strip()
                if not token:
                    time.sleep(5)
                    continue

                url = f"https://api.telegram.org/bot{token}/getUpdates?offset={self.last_update_id + 1}&timeout=20"
                req = urllib.request.Request(url, headers={'User-Agent': 'ShopeeMVDWatcherBot/1.0'})
                try:
                    with urllib.request.urlopen(req, context=ssl_ctx, timeout=25) as resp:
                        res_data = json.loads(resp.read().decode('utf-8'))
                        if res_data.get('ok'):
                            updates = res_data.get('result', [])
                            for up in updates:
                                self.last_update_id = up.get('update_id', self.last_update_id)
                                self._handle_bot_update(token, up)
                except urllib.error.HTTPError as e:
                    if e.code == 409:
                        # Trùng lặp instance polling
                        time.sleep(15)
                    else:
                        time.sleep(5)
                except Exception:
                    time.sleep(3)

            except Exception as e:
                print(f"[TelegramMVD] Lỗi bot polling: {e}")
                time.sleep(5)

    def _handle_bot_update(self, token, update):
        """Xử lý từng lệnh tin nhắn gửi tới Bot"""
        msg = update.get('message') or update.get('channel_post')
        if not msg:
            return

        chat = msg.get('chat', {})
        chat_id = str(chat.get('id', ''))
        text = (msg.get('text') or '').strip()
        from_user = msg.get('from', {})
        user_name = from_user.get('first_name') or from_user.get('username') or 'bạn'

        if not text:
            return

        cmd = text.split()[0].lower() if text else ''

        cfg = load_telegram_config()
        configured_chat_id = str(cfg.get('chat_id') or '').strip()

        # Nếu chưa cấu hình Chat ID hoặc người dùng gửi /start, tự động liên kết Chat ID
        if cmd == '/start' or not configured_chat_id:
            if not configured_chat_id:
                cfg['chat_id'] = chat_id
                cfg['enabled'] = True
                save_telegram_config(cfg)
                print(f"[TelegramMVD] 🔗 Đã tự động kết nối Bot với Chat ID: {chat_id}")

        # Xử lý các lệnh:
        if cmd in ['/start', '/help', 'menu', 'bắt đầu']:
            reply = (
                f"👋 <b>Xin chào {user_name}!</b>\n"
                f"Tôi là <b>Bot Báo Mã Vận Đơn Shopee Tự Động (24/7)</b>.\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 <b>Chat ID của bạn:</b> <code>{chat_id}</code>\n"
                f"⚡ <b>Trạng thái Auto Check:</b> {'🟢 ĐANG BẬT' if cfg.get('auto_check_mvd') else '🔴 ĐANG TẮT'}\n"
                f"⏱️ <b>Chu kỳ quét:</b> {cfg.get('check_interval_seconds', 180)} giây ({int(cfg.get('check_interval_seconds', 180)/60)} phút)\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📋 <b>CÁC LỆNH NHANH:</b>\n"
                f"🔹 <b>/check</b> hoặc <b>/scan</b> : Ép kiểm tra và quét ngay lập tức\n"
                f"🔹 <b>/mvd</b> : Xem danh sách các mã vận đơn mới nhất\n"
                f"🔹 <b>/pending</b> : Xem danh sách đơn đang chờ người bán gửi hàng\n"
                f"🔹 <b>/status</b> : Báo cáo chi tiết trạng thái hệ thống\n"
                f"🔹 <b>/auto_on</b> : Bật tự động quét ngầm 24/7\n"
                f"🔹 <b>/auto_off</b> : Tạm dừng tự động quét ngầm\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Mỗi khi Shopee bàn giao bưu cục và nhảy mã vận đơn, Bot sẽ tự động bắn tin nhắn về đây ngay lập tức!</i>"
            )
            markup = {
                "keyboard": [
                    [{"text": "/check"}, {"text": "/mvd"}],
                    [{"text": "/pending"}, {"text": "/status"}]
                ],
                "resize_keyboard": True
            }
            send_telegram_raw(token, chat_id, reply, reply_markup=markup)

        elif cmd in ['/check', '/scan', '/quet', 'quét']:
            send_telegram_raw(token, chat_id, "⏳ <b>Đang kích hoạt quét toàn bộ đơn hàng...</b>\nVui lòng đợi trong giây lát!")
            ok, msg_txt = self.trigger_check_now()
            if not ok:
                send_telegram_raw(token, chat_id, f"⚠️ {msg_txt}")
            else:
                # Chờ vài giây để có kết quả phản hồi
                def send_result_after_check():
                    time.sleep(6)
                    send_telegram_raw(token, chat_id, f"🏁 <b>Kết quả quét:</b>\n{self.last_check_status}")
                threading.Thread(target=send_result_after_check, daemon=True).start()

        elif cmd in ['/mvd', '/mvdmoi', 'mã vận đơn']:
            draft = load_draft_data()
            rows = draft.get('rows', [])
            mvd_list = [r for r in rows if r.get('tracking_no') and r.get('tracking_no') not in ['Chưa có MVĐ', 'N/A', '', '--']]

            if not mvd_list:
                send_telegram_raw(token, chat_id, "📦 Hiện chưa có đơn hàng nào có Mã Vận Đơn trong hệ thống.")
                return

            reply = f"🚚 <b>DANH SÁCH MÃ VẬN ĐƠN MỚI NHẤT ({len(mvd_list)} đơn):</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            for idx, r in enumerate(mvd_list[:15], 1):
                sn = r.get('order_sn') or r.get('order_id') or '--'
                mvd = r.get('tracking_no')
                carrier = r.get('carrier') or 'SPX Express'
                name = r.get('receiver_name') or '--'
                st = r.get('status_desc') or 'Đang vận chuyển'
                reply += f"<b>{idx}.</b> <code>{mvd}</code> <i>({carrier})</i>\n"
                reply += f"   🔖 Đơn: <code>{sn}</code> | 👤 {name}\n"
                reply += f"   ⚡ {st}\n"
            reply += f"━━━━━━━━━━━━━━━━━━━━━\n🤖 <i>Gửi /check để quét cập nhật thêm.</i>"
            send_telegram_raw(token, chat_id, reply)

        elif cmd in ['/pending', '/chuamvd', 'chờ']:
            draft = load_draft_data()
            rows = draft.get('rows', [])
            pending_list = [r for r in rows if not r.get('tracking_no') or r.get('tracking_no') in ['Chưa có MVĐ', 'N/A', '', '--']]

            if not pending_list:
                send_telegram_raw(token, chat_id, "🎉 Tuyệt vời! Tất cả các đơn hàng trong sheet đều ĐÃ CÓ mã vận đơn.")
                return

            reply = f"⏳ <b>DANH SÁCH ĐƠN ĐANG CHỜ NHẢY MVĐ ({len(pending_list)} đơn):</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            for idx, r in enumerate(pending_list[:15], 1):
                sn = r.get('order_sn') or r.get('order_id') or '--'
                name = r.get('receiver_name') or '--'
                prod = (r.get('product_name') or '--')[:40]
                cod = r.get('cod_amount') or '0 đ'
                reply += f"<b>{idx}.</b> <code>{sn}</code> — 👤 <b>{name}</b>\n"
                reply += f"   🛍️ {prod}...\n"
                reply += f"   💰 COD: {cod}\n"
            reply += f"━━━━━━━━━━━━━━━━━━━━━\n💡 <i>Hệ thống đang theo dõi 24/7. Ngay khi người bán giao bưu cục, bot sẽ gửi tin nhắn báo mã cho bạn!</i>"
            send_telegram_raw(token, chat_id, reply)

        elif cmd in ['/status', 'trạng thái']:
            st = self.get_status()
            reply = (
                f"📊 <b>BÁO CÁO TRẠNG THÁI HỆ THỐNG SHOPEE TRACKER</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 <b>Bot Engine:</b> {'🟢 ĐANG CHẠY 24/7' if st['running'] else '🔴 ĐÃ DỪNG'}\n"
                f"⚡ <b>Auto Check:</b> {'Bật' if st['auto_check_mvd'] else 'Tắt'}\n"
                f"⏱️ <b>Chu kỳ quét:</b> {st['check_interval_seconds']} giây ({int(st['check_interval_seconds']/60)} phút)\n"
                f"📦 <b>Tổng số đơn:</b> <b>{st['total_orders']}</b> đơn\n"
                f"🚚 <b>Đơn đã có MVĐ:</b> <b>{st['orders_has_mvd']}</b> đơn\n"
                f"⏳ <b>Đơn chờ nhảy MVĐ:</b> <b>{st['orders_waiting_mvd']}</b> đơn\n"
                f"🎯 <b>Tổng số lần đã báo:</b> <b>{st['total_notified']}</b> lần\n"
                f"⏰ <b>Lần quét cuối:</b> {st['last_check_time']}\n"
                f"📝 <b>Chi tiết:</b> <i>{st['last_check_status']}</i>\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            send_telegram_raw(token, chat_id, reply)

        elif cmd in ['/auto_on', 'bật']:
            cfg['auto_check_mvd'] = True
            cfg['enabled'] = True
            save_telegram_config(cfg)
            send_telegram_raw(token, chat_id, "✅ <b>ĐÃ BẬT TỰ ĐỘNG QUÉT MÃ VẬN ĐƠN 24/7!</b>\nBot sẽ tự động quét định kỳ và gửi tin nhắn mỗi khi có MVĐ mới.")

        elif cmd in ['/auto_off', 'tắt']:
            cfg['auto_check_mvd'] = False
            save_telegram_config(cfg)
            send_telegram_raw(token, chat_id, "⏸️ <b>ĐÃ TẠM DỪNG TỰ ĐỘNG QUÉT!</b>\nBạn vẫn có thể gõ /check để quét thủ công bất cứ lúc nào.")


# Singleton Instance
mvd_watcher = TelegramMVDWatcher()


def start_watcher_background():
    """Hàm tiện ích gọi từ server.py khi khởi động server"""
    mvd_watcher.start()


if __name__ == '__main__':
    # Hỗ trợ chạy trực tiếp file độc lập
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    print("=" * 65)
    print("      SHOPEE MVD WATCHER - TỰ ĐỘNG BÁO MÃ VẬN ĐƠN TELEGRAM 24/7")
    print("=" * 65)
    cfg = load_telegram_config()
    if not cfg.get('bot_token'):
        print("[!] CẢNH BÁO: Chưa cấu hình Bot Token trong telegram_config.json!")
        print("[!] Hãy chat với @BotFather để tạo Bot và điền Token vào Web hoặc file.")
    else:
        print(f"[*] Bot Token: {cfg['bot_token'][:8]}...{cfg['bot_token'][-5:]}")
        print(f"[*] Chat ID: {cfg.get('chat_id') or 'Chưa cấu hình (hãy nhắn /start cho Bot)'}")

    mvd_watcher.start()
    print("[*] Bot đang chạy... Nhấn Ctrl+C để thoát.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        mvd_watcher.stop()
        print("\n[*] Đã thoát.")
