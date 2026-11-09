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
import sys
import json
import time
import random
import threading
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

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

DEFAULT_AFF_CONFIG = {
    "enabled": True,
    "use_selenium": True,
    "app_id": "17324610663",
    "secret": "",
    "sub_id": "meoidungkhoa",
    "mmp_pid": "an_17320160631",
    "utm_source": "an_17320160631",
    "af_siteid": "an_17320160631",
    "portal_url": "https://affiliate.shopee.vn/offer/custom_link?mmp_pid=an_17320160631&affiliate_id=17324610663&pid=affiliates&utm_source=an_17320160631&utm_medium=affiliates&utm_content=meoidungkhoa&af_siteid=an_17320160631"
}

def load_affiliate_config():
    cfg = DEFAULT_AFF_CONFIG.copy()
    if os.path.exists(AFF_CONFIG_FILE):
        try:
            with open(AFF_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
        except Exception:
            pass
    # Đảm bảo các tham số cốt lõi luôn có giá trị mặc định của người dùng
    for k, v in DEFAULT_AFF_CONFIG.items():
        if not cfg.get(k):
            cfg[k] = v
    return cfg

def save_affiliate_config(data):
    try:
        with open(AFF_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

LAST_CONVERTED_AFFILIATE_LINKS = set()

def expand_shopee_short_url(url, timeout=10):
    """
    Mở rộng triệt để link rút gọn s.shopee.vn / vn.shp.ee / shp.ee / shope.ee thành link gốc Shopee.
    Tự động xử lý redirect nhiều cấp (HTTP 301/302) và bóc tách universal-link (param redir/url).
    """
    if not url:
        return ""
    url = url.strip()
    is_short = any(d in url.lower() for d in ["s.shopee.vn", "vn.shp.ee", "shp.ee", "shope.ee", "universal-link"])
    if not is_short:
        return url

    final_url = url
    # 1. Thử qua requests (mạnh mẽ, tự follow redirects)
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=timeout)
        if resp.url and "error" not in resp.url.lower():
            final_url = resp.url
    except Exception:
        # 2. Fallback qua urllib
        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
            with opener.open(req, timeout=timeout) as resp:
                u = resp.geturl()
                if u and "error" not in u.lower():
                    final_url = u
        except Exception:
            pass

    # 3. Bóc tách link sản phẩm gốc nếu final_url là dạng universal-link hoặc có param chuyển tiếp
    try:
        import urllib.parse
        parsed = urllib.parse.urlsplit(final_url)
        qs = urllib.parse.parse_qs(parsed.query)
        for param in ["redir", "url", "target"]:
            if param in qs and qs[param]:
                unquoted = urllib.parse.unquote(qs[param][0])
                if "shopee.vn" in unquoted:
                    final_url = unquoted
                    break
    except Exception:
        pass

    return final_url

def parse_affiliate_portal_url(url):
    """Bóc tách các tham số từ link Custom Link / Portal Shopee Affiliate"""
    if not url:
        return {}
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url.strip())
        qs = urllib.parse.parse_qs(parsed.query)
        result = {}
        for k, v in qs.items():
            if v:
                result[k] = v[0]
        # Mapping các trường chuẩn
        aff_id = result.get("affiliate_id") or result.get("app_id") or ""
        sub_id = result.get("sub_id") or result.get("utm_content") or ""
        mmp_pid = result.get("mmp_pid") or result.get("utm_source") or ""
        af_siteid = result.get("af_siteid") or result.get("utm_source") or ""
        return {
            "app_id": aff_id,
            "affiliate_id": aff_id,
            "sub_id": sub_id,
            "mmp_pid": mmp_pid,
            "af_siteid": af_siteid,
            "utm_source": result.get("utm_source", mmp_pid),
            "utm_content": sub_id,
            "portal_url": url.strip()
        }
    except Exception:
        return {}

def build_shopee_direct_tracking_url(url, cfg=None):
    """
    Gắn các tham số affiliate tracking trực tiếp vào link sản phẩm Shopee của người dùng.
    Tự động mở rộng link rút gọn trước và xóa bỏ toàn bộ tracking ID của người khác.
    """
    if cfg is None:
        cfg = load_affiliate_config()
    import urllib.parse
    try:
        # 1. Luôn mở rộng link nếu là link rút gọn
        canonical = expand_shopee_short_url(url)
        parsed = urllib.parse.urlsplit(canonical.strip())
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        aff_id = str(cfg.get("app_id") or cfg.get("affiliate_id") or "17324610663").strip()
        mmp_pid = str(cfg.get("mmp_pid") or "an_17320160631").strip()
        sub_id = str(cfg.get("sub_id") or cfg.get("utm_content") or "meoidungkhoa").strip()
        af_siteid = str(cfg.get("af_siteid") or cfg.get("utm_source") or "an_17320160631").strip()
        utm_src = str(cfg.get("utm_source") or mmp_pid or "an_17320160631").strip()

        # 2. Xóa sạch mọi mã Affiliate / UTM cũ của người khác
        for k in ["affiliate_id", "mmp_pid", "pid", "utm_source", "utm_medium", "utm_content", "af_siteid", "utm_campaign", "utm_term"]:
            qs.pop(k, None)

        # 3. Gắn thông tin Affiliate chuẩn của chính người dùng
        if mmp_pid:
            qs["mmp_pid"] = [mmp_pid]
        if aff_id:
            qs["affiliate_id"] = [aff_id]
        qs["pid"] = ["affiliates"]
        if utm_src:
            qs["utm_source"] = [utm_src]
        qs["utm_medium"] = ["affiliates"]
        if af_siteid:
            qs["af_siteid"] = [af_siteid]
        if sub_id:
            qs["utm_content"] = [sub_id]

        new_query = urllib.parse.urlencode(qs, doseq=True)
        netloc = parsed.netloc if parsed.netloc else "shopee.vn"
        if "s.shopee.vn" in netloc or "shp.ee" in netloc:
            netloc = "shopee.vn"
        scheme = parsed.scheme if parsed.scheme else "https"
        return urllib.parse.urlunsplit((scheme, netloc, parsed.path, new_query, parsed.fragment))
    except Exception:
        return url

def convert_via_web_custom_link(raw_url, cookie=None, sub_id=None):
    """
    Gọi API Web nội bộ của https://affiliate.shopee.vn/offer/custom_link bằng Cookie phiên đăng nhập.
    Thao tác y hệt người dùng dán link và bấm nút 'Lấy link' trên web mà không cần đăng ký Open API.
    Endpoint: https://affiliate.shopee.vn/api/v3/gql?q=batchCustomLink
    """
    import urllib.request
    import urllib.error

    cfg = load_affiliate_config()
    cookie = str(cookie if cookie is not None else cfg.get("cookie", "")).strip()
    sub_id = str(sub_id if sub_id is not None else cfg.get("sub_id", "")).strip()

    if not cookie:
        return False, "Chưa cung cấp Cookie tài khoản affiliate.shopee.vn"

    canonical_url = expand_shopee_short_url(raw_url)

    advanced_params = {}
    if sub_id:
        advanced_params["subId1"] = sub_id

    payload = {
        "operationName": "batchGetCustomLink",
        "query": "\n    query batchGetCustomLink($linkParams: [CustomLinkParam!], $sourceCaller: SourceCaller){\n      batchCustomLink(linkParams: $linkParams, sourceCaller: $sourceCaller){\n        shortLink\n        longLink\n        failCode\n      }\n    }\n    ",
        "variables": {
            "linkParams": [
                {
                    "originalLink": canonical_url,
                    "advancedLinkParams": advanced_params
                }
            ],
            "sourceCaller": "CUSTOM_LINK_CALLER"
        }
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "affiliate-program-type": "1",
        "content-type": "application/json; charset=UTF-8",
        "origin": "https://affiliate.shopee.vn",
        "referer": "https://affiliate.shopee.vn/offer/custom_link",
        "sec-ch-ua": '"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "cookie": cookie
    }

    csrf_token = cfg.get("csrf_token")
    if csrf_token:
        headers["csrf-token"] = csrf_token
    if cfg.get("af_ac_enc_dat"):
        headers["af-ac-enc-dat"] = cfg["af_ac_enc_dat"]
    if cfg.get("af_ac_enc_sz_token"):
        headers["af-ac-enc-sz-token"] = cfg["af_ac_enc_sz_token"]
    if cfg.get("x_sap_ri"):
        headers["x-sap-ri"] = cfg["x_sap_ri"]
    if cfg.get("x_sap_sec"):
        headers["x-sap-sec"] = cfg["x_sap_sec"]

    req = urllib.request.Request(
        "https://affiliate.shopee.vn/api/v3/gql?q=batchCustomLink",
        data=payload_bytes,
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            data = res_data.get("data", {})
            batch = data.get("batchCustomLink", [])
            if batch and len(batch) > 0:
                item = batch[0]
                short_link = item.get("shortLink")
                fail_code = item.get("failCode")
                if short_link and fail_code == 0:
                    return True, short_link
                elif short_link:
                    return True, short_link
                else:
                    return False, f"Shopee phản hồi failCode {fail_code}"
            # Trường hợp có error code Shopee anti-bot
            err_code = res_data.get("error") or res_data.get("3")
            if err_code:
                return False, f"Shopee yêu cầu xác thực web (Mã lỗi {err_code})"
            return False, "Shopee không trả về link rút gọn"
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return False, "Cookie Shopee Affiliate đã hết hạn hoặc cần mở tab web (Lỗi 403)"
        return False, f"Lỗi HTTP {e.code}"
    except Exception as e:
        return False, f"Lỗi kết nối Web API: {str(e)}"

def convert_shopee_affiliate_link(raw_url, app_id=None, secret=None, sub_id=None, cookie=None, allow_fallback=True):
    """
    Chuyển đổi linh hoạt link sản phẩm Shopee sang link Affiliate của người dùng:
    1. Ưu tiên 1: Chuyển đổi qua Chrome Thật (Selenium Remote Debugging cổng 9222) -> lấy link s.shopee.vn
    2. Ưu tiên 2: Dùng Cookie Web nội bộ gọi batchCustomLink (nếu cookie hợp lệ)
    3. Ưu tiên 3: Shopee Affiliate GraphQL Open API (nếu có Secret Key)
    4. Fallback toàn diện: Tự động giải mã link rút gọn và gắn Direct Affiliate Tracking UTM (mmp_pid, affiliate_id, ...)
    """
    import hashlib
    import urllib.request
    import urllib.error

    cfg = load_affiliate_config()
    target_aff_id = str(app_id if app_id is not None else cfg.get("app_id", "17324610663")).strip()
    target_mmp = str(cfg.get("mmp_pid", "an_17320160631")).strip()
    secret = str(secret if secret is not None else cfg.get("secret", "")).strip()
    sub_id = str(sub_id if sub_id is not None else cfg.get("sub_id", "meoidungkhoa")).strip()
    cookie = str(cookie if cookie is not None else cfg.get("cookie", "")).strip()

    raw_url = raw_url.strip()
    if not raw_url:
        return False, "Link sản phẩm trống"

    # 0. Nếu link này đã được chính tool chuyển đổi thành công trong phiên này, dùng lại ngay
    if raw_url in LAST_CONVERTED_AFFILIATE_LINKS:
        return True, raw_url

    # Nếu link là link trực tiếp đã có đúng Affiliate ID và MMP PID của người dùng
    if f"affiliate_id={target_aff_id}" in raw_url and (f"mmp_pid={target_mmp}" in raw_url or f"utm_source={target_mmp}" in raw_url):
        LAST_CONVERTED_AFFILIATE_LINKS.add(raw_url)
        return True, raw_url

    # 1. Mở rộng link nếu là link rút gọn để có canonical URL đầy đủ
    canonical_url = expand_shopee_short_url(raw_url)

    # 2. ƯU TIÊN 1: Chuyển đổi qua Chrome Thật (Selenium Remote Debugging cổng 9222)
    use_selenium = cfg.get("use_selenium", True)
    try:
        from shopee_affiliate_browser import is_chrome_running, convert_link_via_selenium
        if use_selenium and is_chrome_running():
            sel_ok, sel_res = convert_link_via_selenium(canonical_url if canonical_url else raw_url)
            if sel_ok and any(k in str(sel_res) for k in ["s.shopee.vn", "shp.ee", "shope.ee"]):
                LAST_CONVERTED_AFFILIATE_LINKS.add(sel_res)
                return True, sel_res
    except Exception as sel_err:
        print(f"[!] Selenium convert link warning: {sel_err}")

    # 3. ƯU TIÊN 2: Thử tạo link qua Web API Cookie (nếu có cookie cấu hình)
    if cookie:
        try:
            web_ok, web_res = convert_via_web_custom_link(canonical_url, cookie=cookie, sub_id=sub_id)
            if web_ok and web_res:
                LAST_CONVERTED_AFFILIATE_LINKS.add(web_res)
                return True, web_res
        except Exception:
            pass

    # 4. ƯU TIÊN 3: Nếu có Secret Key, gọi GraphQL Open API
    if target_aff_id and secret:
        try:
            if sub_id:
                sub_ids_str = json.dumps([sub_id])
                input_args = f'originUrl: "{canonical_url}", subIds: {sub_ids_str}'
            else:
                input_args = f'originUrl: "{canonical_url}"'

            gql_query = f"mutation {{ generateShortLink(input: {{ {input_args} }}) {{ shortLink }} }}"
            payload = {"query": gql_query}
            payload_str = json.dumps(payload, separators=(',', ':'))

            timestamp = int(time.time())
            factor = f"{target_aff_id}{timestamp}{payload_str}{secret}"
            signature = hashlib.sha256(factor.encode("utf-8")).hexdigest()

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"SHA256 Credential={target_aff_id}, Timestamp={timestamp}, Signature={signature}",
                "User-Agent": "ShopeeAffiliateClient/1.0"
            }

            req = urllib.request.Request(
                "https://open-api.affiliate.shopee.vn/graphql",
                data=payload_str.encode("utf-8"),
                headers=headers,
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if not ("errors" in res_data and res_data["errors"]):
                    data = res_data.get("data", {})
                    gen_res = data.get("generateShortLink", {})
                    short_link = gen_res.get("shortLink")
                    if short_link:
                        LAST_CONVERTED_AFFILIATE_LINKS.add(short_link)
                        return True, short_link
        except Exception:
            pass

    # 5. FALLBACK TOÀN DIỆN (LUÔN THÀNH CÔNG 100%): Gắn Direct Tracking UTM của người dùng vào link
    if allow_fallback:
        tracking_url = build_shopee_direct_tracking_url(canonical_url if canonical_url else raw_url, cfg)
        if tracking_url:
            LAST_CONVERTED_AFFILIATE_LINKS.add(tracking_url)
            return True, tracking_url

    if not target_aff_id and not cfg.get("mmp_pid"):
        return False, "Chưa cấu hình tài khoản Shopee Affiliate (App ID hoặc Link Affiliate)"

    return True, canonical_url

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
            "product_link_2": "",  # Link sản phẩm số 2 (tùy chọn)
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
            "timeout_step": 150,
            "timeout_cart": 240,
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
        try:
            print(f"[{timestamp}] [{log_type.upper()}] {msg}")
        except Exception:
            try:
                print(f"[{timestamp}] [{log_type.upper()}] {str(msg).encode('ascii', 'replace').decode('ascii')}")
            except Exception:
                pass

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
            product_link_2 = str(config.get("product_link_2", "")).strip()
            if not product_link and not product_link_2:
                return False, "Bạn đã bật lệnh Thêm Giỏ Hàng, vui lòng nhập ít nhất Link Sản Phẩm 1!"

            # Tự động xử lý chuyển đổi sang link Affiliate trước khi đưa vào bot
            aff_cfg = load_affiliate_config()
            target_aff_id = str(aff_cfg.get("app_id") or "17324610663").strip() if aff_cfg.get("enabled", True) else ""

            if product_link and aff_cfg.get("enabled", True):
                is_already_my_aff = (f"affiliate_id={target_aff_id}" in product_link) or (product_link in LAST_CONVERTED_AFFILIATE_LINKS)
                if not is_already_my_aff:
                    self.log(f"🔗 Đang chuyển đổi link sản phẩm 1 sang link Affiliate của bạn...", "info")
                    aff_ok, aff_res = convert_shopee_affiliate_link(product_link)
                    if aff_ok and aff_res:
                        product_link = aff_res
                        config["product_link"] = aff_res
                        self.log(f"✅ Đã chuyển đổi thành công link 1 dùng cho /addtocart: {aff_res}", "success")
                    else:
                        self.log(f"⚠️ Chuyển đổi link 1 chưa được ({aff_res}), dùng link gốc.", "warning")
                else:
                    config["product_link"] = product_link
                    self.log(f"🔗 Sử dụng trực tiếp link Affiliate cho link 1: {product_link}", "info")

            if product_link_2 and aff_cfg.get("enabled", True):
                is_already_my_aff_2 = (f"affiliate_id={target_aff_id}" in product_link_2) or (product_link_2 in LAST_CONVERTED_AFFILIATE_LINKS)
                if not is_already_my_aff_2:
                    self.log(f"🔗 Đang chuyển đổi link sản phẩm 2 sang link Affiliate của bạn...", "info")
                    aff_ok2, aff_res2 = convert_shopee_affiliate_link(product_link_2)
                    if aff_ok2 and aff_res2:
                        product_link_2 = aff_res2
                        config["product_link_2"] = aff_res2
                        self.log(f"✅ Đã chuyển đổi thành công link 2 dùng cho /addtocart: {aff_res2}", "success")
                    else:
                        self.log(f"⚠️ Chuyển đổi link 2 chưa được ({aff_res2}), dùng link gốc.", "warning")
                else:
                    config["product_link_2"] = product_link_2
                    self.log(f"🔗 Sử dụng trực tiếp link Affiliate cho link 2: {product_link_2}", "info")

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
        # CƠ CHẾ: Bắt chuẩn 100% thông báo thành công từ bot (@dangkyshopee_bot):
        #          - "THÀNH CÔNG!"
        #          - "XÁC MINH THÀNH CÔNG!"
        #          - "THÔNG TIN MAIL"
        #          - Nút "Đọc Mail"
        #          - "**INBOX**"
        #          Bắt được xong chuyển ngay sang lệnh tiếp theo, KHÔNG delay 80s.
        # =========================================================================
        if use_mailfree:
            self.current_step = "LỆNH: /mailfree"
            item["status"] = "mailfree"
            item["step_detail"] = "Đang gửi lệnh /mailfree..."
            self.log(f"📤 Gửi Lệnh: /mailfree cho nick...", "info")

            mail_cmd = f"/mailfree {raw_nick}"
            t_mail_start = time.time()
            success_mail, mail_res = await self._execute_mailfree(client, bot_entity, mail_cmd)
            elapsed_mail = round(time.time() - t_mail_start, 1)

            if not success_mail:
                item["error"] = f"Lỗi Bước /mailfree ({elapsed_mail}s): {mail_res}"
                return False

            item["mail_info"] = mail_res
            self.log(f"✅ BẮT ĐƯỢC thông báo /mailfree THÀNH CÔNG sau {elapsed_mail}s! ({mail_res})", "success")

            # Bắt được thông báo thành công → chuyển ngay sang lệnh tiếp theo (đệm an toàn 2s, không delay 80s)
            if (use_addtocart or use_address) and not self.should_stop:
                self.log("⚡ Chuyển ngay sang lệnh tiếp theo (bỏ qua delay 80s, đệm an toàn 2s)...", "info")
                await asyncio.sleep(2)

            if self.should_stop:
                return False

        # =========================================================================
        # (TÙY CHỌN) LỆNH 2: /addtocart (LINK 1 + LINK 2)
        # CƠ CHẾ: Bắt chuẩn thông báo "KẾT QUẢ THÊM GIỎ" + "Thành công: X"
        #          Sau khi Link 1 thành công -> nảy sang chạy tiếp Link 2.
        #          Chạy xong chuyển ngay sang lệnh tiếp theo, KHÔNG delay 80s.
        # =========================================================================
        if use_addtocart:
            self.current_step = "LỆNH: /addtocart"
            item["status"] = "addtocart"
            item["step_detail"] = "Đang gửi lệnh /addtocart Link 1..."
            prod_link_1 = self.config.get("product_link", "").strip()
            prod_link_2 = self.config.get("product_link_2", "").strip()

            cart_results = []
            link_1_success = False
            success_cart_2 = False

            # --- THỰC THI LINK 1 ---
            if prod_link_1:
                # Kiểm tra tự động chuyển đổi sang link Affiliate nếu cần
                aff_cfg = load_affiliate_config()
                if aff_cfg.get("enabled", True):
                    target_aff_id = str(aff_cfg.get("app_id") or "17324610663").strip()
                    is_aff_1 = (f"affiliate_id={target_aff_id}" in prod_link_1) or (prod_link_1 in LAST_CONVERTED_AFFILIATE_LINKS)
                    if not is_aff_1:
                        self.log("🔗 Đang chuyển đổi Link 1 sang link Affiliate của bạn...", "info")
                        aff_ok, aff_res = convert_shopee_affiliate_link(prod_link_1)
                        if aff_ok and aff_res:
                            prod_link_1 = aff_res
                            self.config["product_link"] = aff_res
                            self.log(f"✅ Đã chuyển đổi Link 1 thành công: {prod_link_1}", "success")
                        else:
                            self.log(f"⚠️ Chuyển đổi Link 1 chưa được: {aff_res}. Tiếp tục dùng link gốc.", "warning")
                    else:
                        self.log(f"🔗 Sử dụng trực tiếp link Affiliate cho Link 1: {prod_link_1}", "info")

                self.log(f"📤 Gửi /addtocart Link 1: {prod_link_1}|<nick>...", "info")
                cart_cmd_1 = f"/addtocart {prod_link_1}|{raw_nick}"
                t_cart1_start = time.time()
                success_cart_1, cart_res_1 = await self._execute_addtocart(client, bot_entity, cart_cmd_1)
                elapsed_cart1 = round(time.time() - t_cart1_start, 1)

                if success_cart_1:
                    link_1_success = True
                    cart_results.append(f"Link 1: {cart_res_1}")
                    self.log(f"✅ BẮT ĐƯỢC thông báo THÀNH CÔNG Link 1 sau {elapsed_cart1}s! ({cart_res_1})", "success")
                else:
                    cart_results.append(f"Link 1 Lỗi: {cart_res_1}")
                    self.log(f"❌ Link 1 không thành công ({cart_res_1})", "error")
                    item["error"] = f"Lỗi /addtocart Link 1: {cart_res_1}"
                    item["cart_info"] = " | ".join(cart_results)
                    return False  # DỪNG LẠI, KHÔNG CHẠY TIẾP NẾU LINK 1 LỖI HOẶC CHƯA XONG

            # --- THỰC THI LINK 2 (SAU KHI BẮT ĐƯỢC KẾT QUẢ LINK 1 ĐÃ NHẬP THÀNH CÔNG) ---
            if prod_link_2 and not self.should_stop:
                if prod_link_1 and not link_1_success:
                    self.log("⚠️ Link 1 chưa thành công, bỏ qua lệnh /addtocart cho Link 2.", "warning")
                    return False
                else:
                    self.log("⚡ Bắt được thông báo Link 1 thành công! Chạy tiếp /addtocart Link 2 ngay (đệm 2s, không delay 80s)...", "info")
                    await asyncio.sleep(2)

                    self.current_step = "LỆNH: /addtocart (Link 2)"
                    item["step_detail"] = "Đang gửi lệnh /addtocart Link 2..."

                    aff_cfg = load_affiliate_config()
                    if aff_cfg.get("enabled", True):
                        target_aff_id = str(aff_cfg.get("app_id") or "17324610663").strip()
                        is_aff_2 = (f"affiliate_id={target_aff_id}" in prod_link_2) or (prod_link_2 in LAST_CONVERTED_AFFILIATE_LINKS)
                        if not is_aff_2:
                            self.log("🔗 Đang chuyển đổi Link 2 sang link Affiliate của bạn...", "info")
                            aff_ok2, aff_res2 = convert_shopee_affiliate_link(prod_link_2)
                            if aff_ok2 and aff_res2:
                                prod_link_2 = aff_res2
                                self.config["product_link_2"] = aff_res2
                                self.log(f"✅ Đã chuyển đổi Link 2 thành công: {prod_link_2}", "success")
                            else:
                                self.log(f"⚠️ Chuyển đổi Link 2 chưa được: {aff_res2}. Tiếp tục dùng link gốc.", "warning")
                        else:
                            self.log(f"🔗 Sử dụng trực tiếp link Affiliate cho Link 2: {prod_link_2}", "info")

                    self.log(f"📤 Gửi /addtocart Link 2: {prod_link_2}|<nick>...", "info")
                    cart_cmd_2 = f"/addtocart {prod_link_2}|{raw_nick}"
                    t_cart2_start = time.time()
                    success_cart_2, cart_res_2 = await self._execute_addtocart(client, bot_entity, cart_cmd_2)
                    elapsed_cart2 = round(time.time() - t_cart2_start, 1)

                    if success_cart_2:
                        cart_results.append(f"Link 2: {cart_res_2}")
                        self.log(f"✅ BẮT ĐƯỢC thông báo THÀNH CÔNG Link 2 sau {elapsed_cart2}s! ({cart_res_2})", "success")
                    else:
                        cart_results.append(f"Link 2 Lỗi: {cart_res_2}")
                        self.log(f"❌ Link 2 không thành công ({cart_res_2})", "error")
                        item["error"] = f"Lỗi /addtocart Link 2: {cart_res_2}"
                        item["cart_info"] = " | ".join(cart_results)
                        return False  # DỪNG LẠI, KHÔNG CHẠY TIẾP NẾU LINK 2 LỖI HOẶC CHƯA XONG

            item["cart_info"] = " | ".join(cart_results) if cart_results else "Không có link giỏ"

            # Đã xong toàn bộ các link giỏ hàng hoàn tất → chuyển sang lệnh địa chỉ (đệm 2s an toàn)
            if use_address and not self.should_stop:
                self.log("⚡ Đã hoàn tất thêm giỏ hàng thành công! Chuyển ngay sang lệnh địa chỉ (đệm an toàn 2s)...", "info")
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
            t_addr_start = time.time()
            success_addr, addr_res = await self._execute_address_wizard(client, bot_entity, addr_cmd)
            elapsed_addr = round(time.time() - t_addr_start, 1)

            if not success_addr:
                item["error"] = f"Lỗi ({addr_cmd_type}) sau {elapsed_addr}s: {addr_res}"
                return False

            item["address_info"] = addr_res
            self.log(f"✅ BẮT ĐƯỢC thông báo {addr_cmd_type} THÀNH CÔNG sau {elapsed_addr}s! {addr_res}", "success")

        return True

    # -------------------------------------------------------------------------
    # BỘ XỬ LÝ LỆNH 1: /mailfree (BẮT CHUẨN THÔNG BÁO THÀNH CÔNG TỪ BOT)
    # -------------------------------------------------------------------------
    async def _execute_mailfree(self, client, bot_entity, cmd_text):
        """
        Bắt chuẩn 100% thông báo thành công /mailfree từ @dangkyshopee_bot:
        1. Bắt các dạng thông báo thành công thực tế của Bot:
           - "THÀNH CÔNG!" (kèm email, mật khẩu)
           - "XÁC MINH THÀNH CÔNG!" (kèm user, vị trí, thiết bị)
           - "THÔNG TIN MAIL" (kèm Shopee, email, mật khẩu)
           - Tin nhắn có nút inline "Đọc Mail"
           - "**INBOX**" (khi mail đã được cấp và hộp thư đã mở)
        2. Tự động giải phóng khi kẹt phiên:
           - "Bạn đang có phiên chạy dở" ➔ Tự động gửi /stop, đợi 2s và gửi lại lệnh
        3. Báo lỗi ngay lập tức (không treo chờ timeout):
           - "Cookie đăng nhập đã hết hạn"
           - "Key proxy đã hết hạn"
           - "KiotProxy không cấp được proxy"
           - Bất kỳ thông báo "❌ Lỗi:" hoặc "❌"
        """
        timeout = max(int(self.config.get("timeout_step", 150)), 150)
        last_sent = await client.send_message(bot_entity, cmd_text)
        start_time = time.time()
        has_sent_stop = False

        while time.time() - start_time < timeout:
            if self.should_stop:
                return False, "Tiến trình bị dừng"

            messages = await client.get_messages(bot_entity, limit=5)
            for m in messages:
                if m.out or m.id <= last_sent.id:
                    continue

                txt = m.text or ""
                txt_lower = txt.lower()

                # Quét nút inline của tin nhắn
                has_doc_mail_btn = False
                if m.buttons:
                    for row in m.buttons:
                        for btn in row:
                            b_text = (btn.text or "").strip().lower()
                            if "đọc mail" in b_text or "doc mail" in b_text:
                                has_doc_mail_btn = True
                                break
                        if has_doc_mail_btn:
                            break

                # 1. DẤU HIỆU BÁO THÀNH CÔNG CỦA /mailfree
                is_success = (
                    "thành công!" in txt_lower or
                    "xác minh thành công" in txt_lower or
                    "thông tin mail" in txt_lower or
                    has_doc_mail_btn or
                    "**inbox**" in txt_lower or
                    ("xác nhận email" in txt_lower and "welcome" in txt_lower)
                )

                if is_success:
                    # Trích xuất email nếu có trong tin nhắn
                    em_match = re.search(r'([a-zA-Z0-9_\-\.]+@[a-zA-Z0-9_\-\.]+\.[a-zA-Z]{2,})', txt)
                    if em_match:
                        email_str = em_match.group(1)
                        # Trích xuất mật khẩu mail nếu có
                        pass_match = re.search(r'🔐\s*`?([^\n`]+)`?', txt)
                        if pass_match:
                            return True, f"{email_str}|{pass_match.group(1).strip()}"
                        return True, email_str

                    # Nếu là tin xác minh thành công (hiển thị User)
                    user_match = re.search(r'User:\s*\*?([^\n\*]+)\*?', txt, re.IGNORECASE)
                    if user_match:
                        return True, f"Xác minh: {user_match.group(1).strip()}"

                    if "**inbox**" in txt_lower:
                        return True, "Hộp thư đã xác nhận"

                    return True, "Cấp mail thành công"

                # 2. XỬ LÝ PHIÊN CHẠY DỞ (TỰ ĐỘNG GỬI /stop ĐỂ GIẢI PHÓNG)
                if "bạn đang có phiên chạy dở" in txt_lower or "đang có phiên chạy dở" in txt_lower:
                    if not has_sent_stop:
                        self.log("⚠️ Bot báo có phiên chạy dở cũ. Đang tự động gửi /stop để giải phóng...", "warning")
                        await client.send_message(bot_entity, "/stop")
                        has_sent_stop = True
                        await asyncio.sleep(2)
                        self.log("🔄 Đang gửi lại lệnh /mailfree sau khi giải phóng...", "info")
                        last_sent = await client.send_message(bot_entity, cmd_text)
                        break

                # 3. DẤU HIỆU LỖI (BÁO LỖI NGAY LẬP TỨC, KHÔNG ĐỢI TIMEOUT)
                if "❌" in txt or "lỗi:" in txt_lower or "không đăng nhập được" in txt_lower or "hết hạn" in txt_lower:
                    err_line = txt.split("\n")[0].strip()
                    err_clean = re.sub(r'[*_`]', '', err_line)
                    return False, err_clean

            await asyncio.sleep(1)

        return False, f"Hết thời gian chờ phản hồi /mailfree ({timeout}s)"

    # -------------------------------------------------------------------------
    # BỘ XỬ LÝ LỆNH: /addtocart (NÂNG CẤP: CHỌN PHÂN LOẠI & BẤM NÚT XÁC NHẬN THÊM SẢN PHẨM)
    # -------------------------------------------------------------------------
    def _is_cancel_button(self, btn_text):
        """Kiểm tra nếu nút mang ý nghĩa Hủy/Cancel/Quay lại/Đóng"""
        if not btn_text:
            return False
        import unicodedata
        t = unicodedata.normalize('NFC', btn_text.strip().lower())
        cancel_keywords = [
            "hủy", "huỷ", "huy", "cancel", "quay lại", "quay lai",
            "thoát", "thoat", "close", "đóng", "dong", "back", "dừng", "dung", "stop", "🚫"
        ]
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

    def _is_mail_button(self, btn_text):
        """Kiểm tra nếu nút mang ý nghĩa Đọc Mail / Hộp thư / Mailfree"""
        if not btn_text:
            return False
        low = btn_text.strip().lower()
        mail_keywords = [
            "đọc mail", "doc mail", "đọc thư", "doc thu", "hộp thư", "hop thu",
            "xem mail", "xem thư", "lấy mail", "lay mail", "email", "mail", "inbox",
            "xác minh mail", "xac minh mail", "cấp mail", "cap mail"
        ]
        return any(mk in low for mk in mail_keywords)

    def _is_confirm_button(self, btn_text):
        """
        Kiểm tra nếu nút là nút Xác nhận thêm sản phẩm vào giỏ
        (VD: '✅ Thêm 1 sản phẩm', 'Thêm vào giỏ', 'Xác nhận', 'Hoàn tất')
        """
        if not btn_text:
            return False
        if self._is_cancel_button(btn_text) or self._is_qty_button(btn_text) or self._is_mail_button(btn_text):
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
        - Bỏ qua tuyệt đối các nút Đọc Mail / Hộp thư / Mailfree.
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
                # Bỏ qua nút Đọc Mail / Hộp thư
                if self._is_mail_button(b_txt):
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

        # 3. Không trùng khớp hoặc không nhập => Chọn nút phân loại đầu tiên hợp lệ
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
        2. Chờ bot xử lý:
           - Bot gửi '⏳ Đang thêm...': TUYỆT ĐỐI KHÔNG BẤM NÚT (vì nút duy nhất là nút Hủy). Kiên nhẫn chờ bot thêm xong.
           - Nếu bot có thông báo chọn phân loại rõ ràng thì mới xử lý.
           - Chờ đến khi bot trả về kết quả '🛒 KẾT QUẢ THÊM GIỎ' hoặc báo lỗi.
        3. Tuyệt đối không bấm nút Hủy giỏ hàng và không dừng giữa chừng.
        """
        timeout = max(int(self.config.get("timeout_cart", 240)), 240)
        target_variant = self.config.get("product_variant", "").strip()

        last_sent = await client.send_message(bot_entity, cmd_text)
        start_time = time.time()
        last_progress_log = 0
        has_sent_stop = False
        variant_clicked = False
        confirm_clicked = False
        last_confirm_click_time = 0

        while time.time() - start_time < timeout:
            if self.should_stop:
                return False, "Tiến trình bị dừng"

            messages = await client.get_messages(bot_entity, limit=5)
            for m in messages:
                # Bỏ qua tin nhắn do ta gửi và các tin nhắn cũ trước lệnh /addtocart
                if m.out or m.id <= last_sent.id:
                    continue

                txt = m.text or ""
                txt_lower = txt.lower()

                # Bỏ qua các tin nhắn mail cũ nếu còn sót
                if any(w in txt_lower for w in ["đọc mail", "hộp thư", "đã cấp mail", "xác minh thành công"]) and "kết quả thêm giỏ" not in txt_lower:
                    continue

                # 1. Cơ chế bắt báo thành công thêm giỏ hàng (KẾT QUẢ CUỐI CÙNG)
                is_cart_result = (
                    "kết quả thêm giỏ" in txt_lower or 
                    ("thành công:" in txt_lower and "lỗi:" in txt_lower) or
                    ("thêm giỏ" in txt_lower and "thành công" in txt_lower) or
                    ("đã thêm" in txt_lower and "giỏ" in txt_lower)
                )

                if is_cart_result:
                    success_match = re.search(r'Thành công:\s*\*?(\d+)\*?', txt, re.IGNORECASE)
                    fail_match = re.search(r'Lỗi:\s*\*?(\d+)\*?', txt, re.IGNORECASE)
                    s_count = int(success_match.group(1)) if success_match else 0
                    f_count = int(fail_match.group(1)) if fail_match else 0

                    if s_count > 0:
                        lines = [ln.strip() for ln in txt.split("\n") if "x1" in ln or "x2" in ln or "x3" in ln]
                        item_name = lines[0] if lines else f"Thành công {s_count} món"
                        return True, item_name
                    elif "thành công" in txt_lower and f_count == 0 and "lỗi" not in txt_lower:
                        return True, "Thành công thêm giỏ hàng"
                    elif f_count > 0 and s_count == 0:
                        return False, f"Thêm giỏ báo lỗi (Thành công: {s_count}, Lỗi: {f_count})"

                # 2. Kiểm tra nếu bot báo lỗi kết thúc (Terminal Errors)
                if "❌" in txt or "lỗi:" in txt_lower or "không đăng nhập được" in txt_lower or "cookie đăng nhập đã hết hạn" in txt_lower:
                    return False, txt.split("\n")[0].strip()

                if "đã hủy thêm giỏ hàng" in txt_lower:
                    return False, "Bot báo đã hủy thêm giỏ hàng"

                # 3. TIN NHẮN ĐANG TIẾN HÀNH THÊM GIỎ (⏳ Đang thêm... / resolve_proxy...)
                # TUYỆT ĐỐI KHÔNG BẤM BẤT KỲ NÚT NÀO TRÊN TIN NHẮN NÀY (Vì nút duy nhất là nút HỦY!)
                is_in_progress = (
                    "đang thêm" in txt_lower or
                    "đang xử lý" in txt_lower or
                    "đang lấy" in txt_lower or
                    "đang kết nối" in txt_lower or
                    "resolve_proxy" in txt_lower or
                    txt.strip().startswith("⏳")
                )

                if is_in_progress:
                    now = time.time()
                    if now - last_progress_log > 8:
                        elapsed = round(now - start_time)
                        self.log(f"⏳ Bot đang thực hiện thêm giỏ hàng (đã chờ {elapsed}s, KHÔNG bấm hủy)...", "info")
                        last_progress_log = now
                    # Đang chạy ngầm, kiên nhẫn đợi bot hoàn tất và sửa nội dung tin nhắn
                    continue

                # 4. Xử lý phiên chạy dở cũ (chỉ giải phóng nếu là phiên cũ của lệnh khác, KHÔNG giải phóng nếu bot đang addtocart)
                if "bạn đang có phiên chạy dở" in txt_lower or "đang có phiên chạy dở" in txt_lower:
                    if "/addtocart" in txt_lower or "thêm vào giỏ" in txt_lower:
                        # Bot vẫn đang trong phiên addtocart, chờ bot hoàn tất
                        await asyncio.sleep(3)
                        continue
                    if not has_sent_stop:
                        self.log("⚠️ Bot báo có phiên chạy dở cũ khác. Đang gửi /stop để giải phóng...", "warning")
                        await client.send_message(bot_entity, "/stop")
                        has_sent_stop = True
                        await asyncio.sleep(2)
                        self.log("🔄 Đang gửi lại lệnh /addtocart sau khi giải phóng...", "info")
                        last_sent = await client.send_message(bot_entity, cmd_text)
                        break
                    else:
                        return False, "Kẹt phiên chạy dở"

                # 5. Nếu bot thực sự gửi bảng chọn phân loại sản phẩm (chỉ khi có câu nhắc chọn phân loại rõ ràng)
                has_variant_prompt = any(vp in txt_lower for vp in ["chọn phân loại", "chọn mẫu", "chọn sản phẩm", "vui lòng chọn"])
                if m.buttons and has_variant_prompt and not is_cart_result:
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
        """
        Chạy một chu trình đầy đủ của wizard địa chỉ:
        Theo dõi chặt chẽ từng thông báo nảy ra từ bot trước khi bấm nút hoặc gửi dữ liệu.
        """
        timeout = int(self.config.get("timeout_address", 180))
        last_sent = await client.send_message(bot_entity, cmd_text)
        start_time = time.time()
        has_sent_stop = False

        # Các cờ trạng thái tuần tự theo dõi từng thông báo nảy ra
        step1_area_sent = False
        step1_choice_clicked = False
        step2_btn_clicked = False
        step2_name_sent = False
        step3_btn_clicked = False
        step3_phone_sent = False
        step4_btn_clicked = False
        step4_street_sent = False

        target_area = self.config.get("address_area", "").strip() or "Phường Tràng Tiền, Hoàn Kiếm, Hà Nội"
        target_name = self.config.get("address_name", "").strip() or "Nguyễn Văn Trung"
        target_street = self.config.get("address_street", "").strip() or "12 Tràng Tiền"
        phone_mode = self.config.get("phone_mode", "auto")
        custom_phone = self.config.get("custom_phone", "").strip()

        while time.time() - start_time < timeout:
            if self.should_stop:
                return False, "Tiến trình bị dừng"

            # Quét các tin nhắn bot phản hồi sau lệnh
            messages = await client.get_messages(bot_entity, limit=5)
            for m in messages:
                if m.out or m.id <= last_sent.id:
                    continue

                txt = m.text or ""
                txt_lower = txt.lower()

                # 1. Bot thông báo THÊM ĐỊA CHỈ THÀNH CÔNG!
                if "THÊM ĐỊA CHỈ THÀNH CÔNG!" in txt:
                    addr_summary = [ln.strip() for ln in txt.split("\n") if ln.strip() and not ln.startswith("✅")]
                    summary_text = " | ".join(addr_summary[:3]) if addr_summary else "Đã thêm địa chỉ thành công"
                    self.log(f"🎉 [Bot Xác Nhận]: {summary_text}", "success")
                    return True, summary_text

                # 2. Xử lý phiên chạy dở cũ (chỉ gửi /stop nếu không phải là phiên addtocart)
                if "bạn đang có phiên chạy dở" in txt_lower or "đang có phiên chạy dở" in txt_lower:
                    if "/addtocart" in txt_lower or "thêm vào giỏ" in txt_lower:
                        self.log("⏳ Phát hiện bot đang hoàn tất phiên thêm giỏ hàng, chờ bot xong trước khi thêm địa chỉ...", "info")
                        await asyncio.sleep(4)
                        continue

                    if not has_sent_stop:
                        self.log("⚠️ Bot báo có phiên chạy dở cũ. Đang tự động gửi /stop để giải phóng...", "warning")
                        await client.send_message(bot_entity, "/stop")
                        has_sent_stop = True
                        await asyncio.sleep(2)
                        self.log("🔄 Đang gửi lại lệnh địa chỉ sau khi giải phóng...", "info")
                        last_sent = await client.send_message(bot_entity, cmd_text)
                        break
                    else:
                        return False, "Kẹt phiên chạy dở"

                # 3. Bot báo lỗi đăng nhập / hết hạn cookie
                if "Không đăng nhập được" in txt or "Cookie đăng nhập đã hết hạn" in txt or "SPC_F chưa được chấp nhận" in txt:
                    return False, txt.split("\n")[0]

                # 4. Bot báo lỗi tra cứu khu vực
                if "Lỗi tìm kiếm: Chưa tra cứu được khu vực" in txt:
                    return False, "AREA_SEARCH_ERROR"

                # 4. BƯỚC 1: Thông báo nhập khu vực nảy ra
                if not step1_area_sent and ("BƯỚC 1: NHẬP KHU VỰC" in txt or "nhập khu vực" in txt.lower()):
                    first_line = txt.splitlines()[0] if txt else "Nhập khu vực"
                    self.log(f"🔔 [Bot Thông Báo]: {first_line} ➔ Gửi: '{target_area}'", "info")
                    await client.send_message(bot_entity, target_area)
                    step1_area_sent = True
                    await asyncio.sleep(2)
                    break

                # 5. BƯỚC 1 KẾT QUẢ: Danh sách khu vực tìm kiếm nảy ra
                if step1_area_sent and not step1_choice_clicked and m.buttons:
                    has_results = (
                        "chọn khu vực phù hợp" in txt.lower() or 
                        "kết quả tìm kiếm" in txt.lower() or 
                        any((btn.text or "").strip().startswith("1.") for row in m.buttons for btn in row)
                    )
                    if has_results:
                        chosen_btn = None
                        for row in m.buttons:
                            for btn in row:
                                b_text = (btn.text or "").strip()
                                if b_text.startswith("1.") or "Tràng Tiền" in b_text or target_area.split(",")[0].strip() in b_text:
                                    chosen_btn = btn
                                    break
                            if chosen_btn:
                                break
                        if not chosen_btn:
                            chosen_btn = m.buttons[0][0]

                        self.log(f"🔔 [Bot Thông Báo]: Danh sách khu vực nảy ra ➔ Bấm chọn: '{chosen_btn.text}'", "info")
                        await chosen_btn.click()
                        step1_choice_clicked = True
                        await asyncio.sleep(2)
                        break

                # 6. BƯỚC 2: Thông báo Tên Người Nhận nảy ra
                if step1_choice_clicked and not step2_btn_clicked and m.buttons:
                    if "tên người nhận" in txt.lower():
                        for row in m.buttons:
                            for btn in row:
                                b_text = (btn.text or "").strip().lower()
                                if "tự nhập tên" in b_text or "tự nhập" in b_text:
                                    self.log(f"🔔 [Bot Thông Báo]: Bước Tên nảy ra ➔ Bấm nút: '{btn.text}'", "info")
                                    await btn.click()
                                    step2_btn_clicked = True
                                    await asyncio.sleep(2)
                                    break
                            if step2_btn_clicked:
                                break
                        if step2_btn_clicked:
                            break

                # 7. BƯỚC 2 NHẬP: Ô yêu cầu chat Tên nảy ra
                if step2_btn_clicked and not step2_name_sent:
                    is_name_input_prompt = any(w in txt.lower() for w in ["chat tên", "nhập tên", "gửi tên", "chat ten", "nhap ten"]) or ("tên người nhận" in txt.lower() and not m.buttons)
                    if is_name_input_prompt:
                        self.log(f"🔔 [Bot Thông Báo]: Ô nhập tên nảy ra ➔ Gửi: '{target_name}'", "info")
                        await client.send_message(bot_entity, target_name)
                        step2_name_sent = True
                        await asyncio.sleep(2)
                        break

                # 8. BƯỚC 3: Thông báo Số Điện Thoại nảy ra
                if step2_name_sent and not step3_phone_sent:
                    is_phone_prompt = ("số điện thoại" in txt.lower() or "sđt" in txt.lower()) and "địa chỉ chi tiết" not in txt.lower()
                    if is_phone_prompt:
                        has_acc_phone = "Không tìm thấy" not in txt and "SĐT Acc:" in txt
                        should_random = False
                        if phone_mode == "random":
                            should_random = True
                        elif phone_mode == "custom":
                            should_random = False
                        else:  # auto
                            should_random = not has_acc_phone

                        if not should_random and has_acc_phone and phone_mode != "custom":
                            # Bấm Lấy SĐT Acc nếu tài khoản có sẵn SĐT
                            if m.buttons:
                                for row in m.buttons:
                                    for btn in row:
                                        if "lấy sđt" in (btn.text or "").lower():
                                            self.log(f"🔔 [Bot Thông Báo]: SĐT Acc có sẵn ➔ Bấm nút: '{btn.text}'", "info")
                                            await btn.click()
                                            step3_phone_sent = True
                                            await asyncio.sleep(2)
                                            break
                                    if step3_phone_sent:
                                        break
                                if step3_phone_sent:
                                    break
                        else:
                            # Cần tự nhập SĐT
                            if not step3_btn_clicked and m.buttons:
                                for row in m.buttons:
                                    for btn in row:
                                        b_text = (btn.text or "").lower()
                                        if "tự nhập sđt" in b_text or "tự nhập" in b_text:
                                            self.log(f"🔔 [Bot Thông Báo]: Bước SĐT nảy ra ➔ Bấm nút: '{btn.text}'", "info")
                                            await btn.click()
                                            step3_btn_clicked = True
                                            await asyncio.sleep(2)
                                            break
                                    if step3_btn_clicked:
                                        break
                                if step3_btn_clicked:
                                    break

                            # Đợi thông báo yêu cầu chat SĐT nảy ra
                            if step3_btn_clicked and not step3_phone_sent:
                                is_phone_input_prompt = any(w in txt.lower() for w in ["chat số", "nhập số", "chat sđt", "nhập sđt", "gửi sđt", "nhap sdt"]) or ("số điện thoại" in txt.lower() and not m.buttons)
                                if is_phone_input_prompt:
                                    phone_to_send = custom_phone if (custom_phone and phone_mode == "custom") else generate_random_vn_phone()
                                    self.log(f"🔔 [Bot Thông Báo]: Ô nhập SĐT nảy ra ➔ Gửi: '{phone_to_send}'", "info")
                                    await client.send_message(bot_entity, phone_to_send)
                                    step3_phone_sent = True
                                    await asyncio.sleep(2)
                                    break

                # 9. BƯỚC 4: Thông báo Địa Chỉ Chi Tiết nảy ra
                if step3_phone_sent and not step4_street_sent:
                    is_street_prompt = "địa chỉ chi tiết" in txt.lower() and "thành công" not in txt.lower()
                    if is_street_prompt:
                        if not step4_btn_clicked and m.buttons:
                            for row in m.buttons:
                                for btn in row:
                                    b_text = (btn.text or "").lower()
                                    if "tự nhập" in b_text and "random" not in b_text:
                                        self.log(f"🔔 [Bot Thông Báo]: Bước Địa chỉ chi tiết nảy ra ➔ Bấm nút: '{btn.text}'", "info")
                                        await btn.click()
                                        step4_btn_clicked = True
                                        await asyncio.sleep(2)
                                        break
                                if step4_btn_clicked:
                                    break
                            if step4_btn_clicked:
                                break

                        # Đợi thông báo yêu cầu chat Địa chỉ chi tiết nảy ra
                        if step4_btn_clicked and not step4_street_sent:
                            is_street_input_prompt = any(w in txt.lower() for w in ["chat địa chỉ", "nhập địa chỉ", "số nhà", "tên đường", "chat dia chi"]) or ("địa chỉ chi tiết" in txt.lower() and not m.buttons)
                            if is_street_input_prompt:
                                self.log(f"🔔 [Bot Thông Báo]: Ô nhập địa chỉ chi tiết nảy ra ➔ Gửi: '{target_street}'", "info")
                                await client.send_message(bot_entity, target_street)
                                step4_street_sent = True
                                await asyncio.sleep(3)
                                break

            await asyncio.sleep(1.5)

        return False, f"Hết thời gian chờ hoàn tất Wizard địa chỉ ({timeout}s)"

# Khởi tạo singleton manager
dks_mgr = DangKyShopeeManager()
