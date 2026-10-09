"""
Shopee Tracking Sheet Backend
Direct Shopee Mobile Gateway (x-api-source: rn)
Supports Sheet View: Order SN, Tracking MVĐ, Receiver, Address, COD, Status Badges, Draft Save/Load
Additional Columns: Product Link, Shipper Phone, Order Time, Last Check, Full Detail

V2: Supabase PostgreSQL integration — data stored in cloud, local draft.json as offline fallback
"""

import http.server
import socketserver
import json
import os
import ssl
import time
import datetime
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import threading

try:
    from supabase import create_client, Client as SupabaseClient
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    print("[!] supabase-py not installed. Run: pip install supabase")

try:
    from autoreg_manager import auto_reg_mgr, SERVICES as AUTOREG_SERVICES, CMSNPA_KEY, CMSNPA_BASE, get_kiotproxy_ip, get_telegram_account_info
    AUTOREG_AVAILABLE = True
except Exception as _ar_ex:
    auto_reg_mgr = None
    AUTOREG_AVAILABLE = False
    print(f"[!] Autoreg manager not loaded: {_ar_ex}")

try:
    from telegram_auth import tg_auth_mgr
except Exception as _tg_err:
    tg_auth_mgr = None
    print(f"[!] Telegram auth manager not loaded: {_tg_err}")

try:
    from dangkyshopee_manager import dks_mgr, parse_vietnamese_address
    DKS_AVAILABLE = True
except Exception as _dks_err:
    dks_mgr = None
    parse_vietnamese_address = None
    DKS_AVAILABLE = False
    print(f"[!] DangKyShopee manager not loaded: {_dks_err}")

PORT = int(os.environ.get("PORT", 8080))
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DRAFT_FILE = os.path.join(DIRECTORY, "draft.json")
ENV_FILE = os.path.join(DIRECTORY, ".env")
VAULT_FILE = os.path.join(DIRECTORY, "cookie_vault.json")
TEMPLATES_FILE = os.path.join(DIRECTORY, "templates_config.json")
TELEGRAM_CONFIG_FILE = os.path.join(DIRECTORY, "telegram_config.json")

# ━━━ ĐỌC CONFIG TỪ FILE .env ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUPABASE_URL = ""
SUPABASE_KEY = ""

def _load_env():
    """Đọc SUPABASE_URL và SUPABASE_KEY từ file .env"""
    global SUPABASE_URL, SUPABASE_KEY
    # Ưu tiên biến môi trường hệ thống
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
    # Nếu chưa có thì đọc từ file .env
    if not SUPABASE_URL and os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or '=' not in line:
                        continue
                    key, _, val = line.partition('=')
                    key = key.strip()
                    val = val.strip()
                    if key == 'SUPABASE_URL':
                        SUPABASE_URL = val
                    elif key == 'SUPABASE_KEY':
                        SUPABASE_KEY = val
        except Exception as e:
            print(f"[!] Không thể đọc .env: {e}")

_load_env()

def get_supabase():
    """Trả về Supabase client nếu đã cấu hình đúng, ngược lại trả None."""
    if not SUPABASE_AVAILABLE:
        return None
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    # Kiểm tra URL hợp lệ (chưa điền placeholder)
    if 'your-project-id' in SUPABASE_URL or 'your-anon' in SUPABASE_KEY:
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[!] Không thể kết nối Supabase: {e}")
        return None

def _is_supabase_configured():
    """Kiểm tra nhanh xem Supabase đã được cấu hình chưa."""
    return (
        SUPABASE_AVAILABLE
        and bool(SUPABASE_URL)
        and bool(SUPABASE_KEY)
        and 'your-project-id' not in SUPABASE_URL
        and 'your-anon' not in SUPABASE_KEY
    )

# Columns không cần lưu vào Supabase (chỉ dùng nội bộ frontend)
_EXCLUDED_COLS = {'created_at'}

# SSL context
ssl_ctx = ssl.create_default_context()

MOBILE_HEADERS = {
    'User-Agent': 'Shopee/3.20.00 (Android; 13; SM-G998B)',
    'x-api-source': 'rn',
    'accept': 'application/json',
    'x-shopee-language': 'vi'
}

def clean_cookie_str(raw):
    raw = (raw or '').strip()
    if raw.startswith('Cookie:'):
        raw = raw[7:].strip()
    if '|' in raw:
        raw = raw.split('|')[0].strip()
    if 'SPC_ST=' in raw:
        parts = raw.split(';')
        for p in parts:
            p = p.strip()
            if p.startswith('SPC_ST='):
                return p[7:].strip()
    return raw

# ━━━ PROXY INTEGRATION (KiotProxy + ProxyVN) ━━━━━━━━━━━━━━━━━━━
PROXY_CONFIG_FILE = os.path.join(DIRECTORY, "proxy_config.json")
KIOTPROXY_API_BASE = "https://api.kiotproxy.com/api/public/proxies"
PROXYVN_API_URL = "https://proxyxoay.shop/api/get.php"

proxy_state = {
    # Loại provider: "kiotproxy" hoặc "proxyvn"
    "provider": "proxyvn",
    # Shared
    "key": "",
    "enabled": False,
    "auto_rotate": True,
    "region": "",
    "current_proxy": None,
    "proxy_url": None,
    "last_check": None,
    "last_error": None,
    # ProxyVN specific
    "proxyvn_key": "",
    "proxyvn_nhamang": "Random",
    "proxyvn_tinhthanh": "0",
    "proxyvn_current_ip": "",
    "proxyvn_location": "",
    "proxyvn_expire_s": 0,
    "proxyvn_expire_at": "",
}

def _load_proxy_config():
    global proxy_state
    if os.path.exists(PROXY_CONFIG_FILE):
        try:
            with open(PROXY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                proxy_state.update(saved)
        except Exception as e:
            print(f"[!] Lỗi đọc proxy_config.json: {e}")
    # Fallback env vars
    if not proxy_state.get('key'):
        env_key = os.environ.get("KIOTPROXY_KEY", "")
        if env_key:
            proxy_state['key'] = env_key
    if not proxy_state.get('proxyvn_key'):
        env_key = os.environ.get("PROXYVN_KEY", "")
        if env_key:
            proxy_state['proxyvn_key'] = env_key

def _init_proxy_on_boot():
    time.sleep(0.5)
    if proxy_state.get('enabled') or proxy_state.get('key'):
        prov = proxy_state.get('provider', 'proxyvn')
        try:
            if prov == 'kiotproxy' and proxy_state.get('key'):
                kiotproxy_get_current()
                print(f"[KiotProxy] Proxy da nap thanh cong: {proxy_state.get('proxy_url')}")
            elif prov == 'proxyvn' and proxy_state.get('proxyvn_key'):
                proxyvn_get_ip()
                print(f"[ProxyVN] Proxy da nap thanh cong: {proxy_state.get('proxy_url')}")
        except Exception as e:
            try:
                print(f"[Proxy] Nap proxy khoi dong warning: {e}")
            except Exception:
                pass

_load_proxy_config()
threading.Thread(target=_init_proxy_on_boot, daemon=True).start()

def _save_proxy_config():
    try:
        to_save = {
            "provider": proxy_state.get("provider", "proxyvn"),
            "key": proxy_state.get("key", ""),
            "enabled": proxy_state.get("enabled", False),
            "auto_rotate": proxy_state.get("auto_rotate", True),
            "region": proxy_state.get("region", ""),
            "last_check": proxy_state.get("last_check"),
            "proxyvn_key": proxy_state.get("proxyvn_key", ""),
            "proxyvn_nhamang": proxy_state.get("proxyvn_nhamang", "Random"),
            "proxyvn_tinhthanh": proxy_state.get("proxyvn_tinhthanh", "0"),
        }
        with open(PROXY_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Lỗi ghi proxy_config.json: {e}")

# ━━━ PROXYVN HELPERS (proxyxoay.shop) ━━━━━━━━━━━━━━━━━━━━━━━━━━
def proxyvn_get_ip(key=None, nhamang=None, tinhthanh=None):
    """Gọi ProxyVN API để lấy IP xoay mới. Trả về proxy_url dạng http://ip:port"""
    global proxy_state
    k = (key or proxy_state.get('proxyvn_key') or '').strip()
    if not k:
        return {'success': False, 'message': 'Chưa nhập Key ProxyVN'}
    nm = nhamang or proxy_state.get('proxyvn_nhamang') or 'Random'
    tt = tinhthanh if tinhthanh is not None else proxy_state.get('proxyvn_tinhthanh', '0')
    url = f"{PROXYVN_API_URL}?key={k}&nhamang={nm}&tinhthanh={tt}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ShopeeTracker/4.2'})
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=25) as res:
            data = json.loads(res.read().decode('utf-8'))
        if data.get('status') == 100:
            proxy_http = data.get('proxyhttp', '')
            # Format: "IP:PORT::" hoặc "IP:PORT:user:pass"
            parts = proxy_http.split(':')
            ip = parts[0] if len(parts) >= 1 else ''
            port = parts[1] if len(parts) >= 2 else ''
            user = parts[2] if len(parts) >= 3 else ''
            pwd = parts[3] if len(parts) >= 4 else ''
            if user and pwd:
                p_url = f"http://{user}:{pwd}@{ip}:{port}"
            else:
                p_url = f"http://{ip}:{port}"
            proxy_state['proxyvn_current_ip'] = ip
            proxy_state['proxyvn_location'] = data.get('Vi Tri', '')
            proxy_state['proxyvn_expire_s'] = int(data.get('message', '').replace('proxy nay se die sau ', '').replace('s', '').strip() or 0) if 'die sau' in str(data.get('message','')) else 0
            proxy_state['proxyvn_expire_at'] = data.get('Token expiration date', '')
            proxy_state['proxy_url'] = p_url
            proxy_state['current_proxy'] = {
                'ip': ip, 'port': port,
                'nhamang': data.get('Nha Mang', nm),
                'location': data.get('Vi Tri', ''),
                'expire_at': data.get('Token expiration date', ''),
                'proxy_url': p_url
            }
            proxy_state['last_check'] = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
            proxy_state['last_error'] = None
            print(f"[ProxyVN] Đã lấy IP mới: {ip}:{port} ({data.get('Vi Tri','')}) - {data.get('Nha Mang','')}")
            return {'success': True, 'data': proxy_state['current_proxy'], 'proxy_url': p_url}
        else:
            raw_msg = str(data.get('message', 'Lỗi không xác định'))
            msg = f"ProxyVN: {raw_msg} (Status: {data.get('status')})"
            proxy_state['last_error'] = msg
            return {'success': False, 'message': msg}
    except Exception as e:
        msg = f"Lỗi kết nối ProxyVN: {str(e)}"
        proxy_state['last_error'] = msg
        return {'success': False, 'message': msg}

def _format_proxy_url(p_data):
    if not p_data or not isinstance(p_data, dict):
        return None
    user = p_data.get('proxyUser')
    pwd = p_data.get('proxyPass')
    host = p_data.get('host')
    port = p_data.get('httpPort')
    if host and port:
        if user and pwd:
            return f"http://{user}:{pwd}@{host}:{port}"
        return f"http://{host}:{port}"
    http_str = p_data.get('http')
    if http_str:
        parts = http_str.split(':')
        if len(parts) == 4:
            return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        elif len(parts) == 2:
            return f"http://{parts[0]}:{parts[1]}"
        return f"http://{http_str}"
    return None

def kiotproxy_api_request(endpoint, payload):
    url = f"{KIOTPROXY_API_BASE}/{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'ShopeeTracker/4.2'}
    )
    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=12) as res:
            return json.loads(res.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='replace')
        try:
            return json.loads(err_body)
        except Exception:
            return {'success': False, 'code': e.code, 'message': err_body}
    except Exception as e:
        return {'success': False, 'message': str(e)}

def kiotproxy_get_current(key=None, auto_create=True, force_refresh=False):
    global proxy_state
    k = (key or proxy_state.get('key') or '').strip()
    if not k:
        return {'success': False, 'message': 'Chưa nhập Key KiotProxy'}
    
    # 0. Nếu proxy hiện tại vẫn còn hạn và không ép refresh -> dùng ngay để tránh bị KiotProxy rate-limit
    if not force_refresh and proxy_state.get('current_proxy') and k == proxy_state.get('key'):
        cp = proxy_state['current_proxy']
        exp_ms = cp.get('expirationAt')
        now_ms = time.time() * 1000
        if exp_ms and isinstance(exp_ms, (int, float)) and exp_ms > (now_ms + 15000):
            # Proxy còn hạn > 15 giây
            return {'success': True, 'data': cp, 'cached': True}
    
    # 1. Thử lấy proxy hiện tại từ API KiotProxy
    res = kiotproxy_api_request('get-current', {'keyValue': k})
    if res.get('success') and res.get('data'):
        proxy_state['current_proxy'] = res['data']
        proxy_state['proxy_url'] = _format_proxy_url(res['data'])
        proxy_state['last_check'] = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
        proxy_state['last_error'] = None
        return res
    
    # Nếu bị rate-limit gọi get-current nhưng trong máy đã có proxy
    msg_str = str(res.get('message', ''))
    if 'giới hạn' in msg_str or 'quá nhiều' in msg_str:
        if proxy_state.get('current_proxy') and k == proxy_state.get('key'):
            return {'success': True, 'data': proxy_state['current_proxy'], 'note': 'Dùng IP hiện tại (đang hạn chế tần suất gọi API)'}
    
    # 2. Nếu chưa có proxy đang dùng hoặc hết hạn -> tự động cấp IP mới (get-new)
    if auto_create:
        res_new = kiotproxy_get_new(key=k, fallback_current=False)
        if res_new.get('success') and res_new.get('data'):
            return res_new
        # Nếu get-new báo đang trong thời gian chờ (cooldown) mà get-current trước đó lỗi
        # thử lại get-current một lần nữa
        if res_new.get('code') == 40001038 or 'giây' in str(res_new.get('message', '')):
            if proxy_state.get('current_proxy'):
                return {'success': True, 'data': proxy_state['current_proxy']}
            res_retry = kiotproxy_api_request('get-current', {'keyValue': k})
            if res_retry.get('success') and res_retry.get('data'):
                proxy_state['current_proxy'] = res_retry['data']
                proxy_state['proxy_url'] = _format_proxy_url(res_retry['data'])
                proxy_state['last_check'] = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                proxy_state['last_error'] = None
                return res_retry
        
        proxy_state['last_error'] = res.get('message') or res_new.get('message') or 'Không thể kết nối KiotProxy'
        return res if res.get('message') else res_new
    
    proxy_state['last_error'] = res.get('message', 'Không lấy được proxy hiện tại')
    return res

def kiotproxy_get_new(key=None, region=None, fallback_current=True):
    global proxy_state
    k = (key or proxy_state.get('key') or '').strip()
    if not k:
        return {'success': False, 'message': 'Chưa nhập Key KiotProxy'}
    payload = {'keyValue': k}
    reg = region if region is not None else proxy_state.get('region')
    if reg:
        payload['region'] = reg
    res = kiotproxy_api_request('get-new', payload)
    if res.get('success') and res.get('data'):
        proxy_state['current_proxy'] = res['data']
        proxy_state['proxy_url'] = _format_proxy_url(res['data'])
        proxy_state['last_check'] = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
        proxy_state['last_error'] = None
        return res
    
    # Nếu bị cooldown và cho phép fallback: lấy lại IP hiện tại đang hoạt động
    if fallback_current and (res.get('code') == 40001038 or 'giây' in str(res.get('message', ''))):
        curr_res = kiotproxy_api_request('get-current', {'keyValue': k})
        if curr_res.get('success') and curr_res.get('data'):
            proxy_state['current_proxy'] = curr_res['data']
            proxy_state['proxy_url'] = _format_proxy_url(curr_res['data'])
            proxy_state['last_check'] = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
            proxy_state['last_error'] = None
            curr_res['message'] = res.get('message') or 'IP hiện tại vẫn còn hạn'
            curr_res['cooldown'] = True
            return curr_res

    proxy_state['last_error'] = res.get('message', 'Không thể đổi proxy mới')
    return res

def kiotproxy_out(key=None):
    k = (key or proxy_state.get('key') or '').strip()
    if not k:
        return {'success': False, 'message': 'Chưa nhập Key Proxy'}
    return kiotproxy_api_request('out', {'keyValue': k})

def fetch_shopee_json(url, headers, timeout=10, retries=1):
    req = urllib.request.Request(url, headers=headers)
    
    if proxy_state.get('enabled'):
        provider = proxy_state.get('provider', 'proxyvn')
        # Đảm bảo có proxy_url
        if not proxy_state.get('proxy_url'):
            try:
                if provider == 'proxyvn':
                    proxyvn_get_ip()
                else:
                    kiotproxy_get_current()
            except Exception:
                pass

        p_url = proxy_state.get('proxy_url')
        if p_url:
            try:
                proxy_handler = urllib.request.ProxyHandler({'http': p_url, 'https': p_url})
                https_handler = urllib.request.HTTPSHandler(context=ssl_ctx)
                opener = urllib.request.build_opener(proxy_handler, https_handler)
                with opener.open(req, timeout=timeout) as res:
                    return json.loads(res.read().decode('utf-8'))
            except Exception as e:
                is_http_err = isinstance(e, urllib.error.HTTPError)
                is_block = is_http_err and e.code in (403, 429)
                is_proxy_dead = not is_http_err or (is_http_err and e.code in (502, 503, 504))

                if (is_block or is_proxy_dead) and proxy_state.get('auto_rotate') and retries > 0:
                    print(f"[Proxy-{provider}] Gặp lỗi ({e}), tự động lấy IP mới và thử lại...")
                    try:
                        if provider == 'proxyvn':
                            proxyvn_get_ip()
                        else:
                            kiotproxy_get_new()
                        return fetch_shopee_json(url, headers, timeout=timeout, retries=retries - 1)
                    except Exception as rot_err:
                        print(f"[Proxy-{provider}] Đổi IP thất bại: {rot_err}")
                print(f"[Proxy-{provider}] Lỗi kết nối ({p_url}): {e}")
                raise
        else:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=timeout) as res:
                return json.loads(res.read().decode('utf-8'))
    else:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=timeout) as res:
            return json.loads(res.read().decode('utf-8'))

# ━━━ COOKIE VAULT / KHO QUẢN LÝ SHOP ━━━━━━━━━━━━━━━━━━━━━━━━━
_SUPABASE_VAULT_ENABLED = True

def _load_vault():
    global _SUPABASE_VAULT_ENABLED
    local_vault = []
    if os.path.exists(VAULT_FILE):
        try:
            with open(VAULT_FILE, 'r', encoding='utf-8') as f:
                local_vault = json.load(f)
                if not isinstance(local_vault, list):
                    local_vault = []
        except Exception as e:
            print(f"[!] Lỗi đọc cookie_vault.json: {e}")
            local_vault = []

    # Nếu Supabase được cấu hình, thử nạp từ bảng cookie_vault trên cloud
    if _is_supabase_configured() and _SUPABASE_VAULT_ENABLED:
        try:
            sb = get_supabase()
            if sb:
                res = sb.table('cookie_vault').select('*').order('created_at', desc=True).execute()
                cloud_vault = res.data or []
                if cloud_vault:
                    # Đồng bộ xuống file cục bộ làm bản cache
                    try:
                        with open(VAULT_FILE, 'w', encoding='utf-8') as f:
                            json.dump(cloud_vault, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    return cloud_vault
                elif local_vault:
                    # Cloud đang rỗng nhưng local có sẵn tài khoản -> Tự động đẩy lên Supabase
                    try:
                        sb.table('cookie_vault').upsert(local_vault, on_conflict='id').execute()
                    except Exception:
                        pass
        except Exception as e:
            err_msg = str(e)
            if 'PGRST205' in err_msg or 'schema cache' in err_msg:
                _SUPABASE_VAULT_ENABLED = False
                print("[!] Supabase: Bảng 'cookie_vault' chưa được tạo trong database. Sử dụng kho cookie file cục bộ an toàn.")
            else:
                print(f"[!] Supabase load vault warning: {e}")

    return local_vault

def _save_vault(items):
    global _SUPABASE_VAULT_ENABLED
    if not isinstance(items, list):
        items = []

    # 1. Luôn lưu vào file cục bộ trước tiên
    saved_ok = False
    try:
        with open(VAULT_FILE, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        saved_ok = True
    except Exception as e:
        print(f"[!] Lỗi ghi cookie_vault.json: {e}")

    # 2. Đồng bộ lên Supabase nếu có cấu hình
    if _is_supabase_configured() and _SUPABASE_VAULT_ENABLED:
        try:
            sb = get_supabase()
            if sb:
                if not items:
                    sb.table('cookie_vault').delete().neq('id', '').execute()
                else:
                    clean_items = []
                    for it in items:
                        c = dict(it)
                        if not c.get('id'):
                            c['id'] = str(int(time.time() * 1000))
                        clean_items.append(c)

                    # Tự động loại bỏ cột không hợp lệ nếu schema Supabase khác biệt
                    for attempt in range(5):
                        try:
                            sb.table('cookie_vault').upsert(clean_items, on_conflict='id').execute()
                            break
                        except Exception as ex:
                            err_msg = str(ex)
                            import re
                            match = re.search(r"Could not find the '([^']+)' column", err_msg)
                            if match:
                                missing_col = match.group(1)
                                for r in clean_items:
                                    r.pop(missing_col, None)
                                continue
                            raise ex
        except Exception as e:
            err_msg = str(e)
            if 'PGRST205' in err_msg or 'schema cache' in err_msg:
                _SUPABASE_VAULT_ENABLED = False
                print("[!] Supabase: Bảng 'cookie_vault' chưa tạo trên Cloud. Dữ liệu đã lưu cục bộ.")
            else:
                print(f"[!] Supabase save vault warning: {e}")

    return saved_ok


def check_cookie_health(spc_st):
    """Kiểm tra tình trạng cookie Shopee còn sống hay hết hạn"""
    token = clean_cookie_str(spc_st)
    if not token or len(token) < 20:
        return {'status': 'invalid', 'error': 'Cookie không hợp lệ hoặc quá ngắn', 'account': None}
    acc_url = 'https://shopee.vn/api/v4/account/basic/get_account_info'
    acc_headers = {**MOBILE_HEADERS, 'Cookie': f'SPC_ST={token};'}
    try:
        data = fetch_shopee_json(acc_url, acc_headers, timeout=8)
        err = data.get('error')
        if err == 0 and data.get('data'):
            u = data['data']
            return {
                'status': 'alive',
                'username': u.get('username') or f"User_{u.get('userid')}",
                'userid': u.get('userid'),
                'phone': u.get('phone') or '',
                'error': None
            }
        elif err == 19 or 'auth' in str(data.get('error_msg', '')).lower():
            return {'status': 'expired', 'error': 'Cookie đã hết hạn đăng nhập (Error 19)', 'account': None}
        else:
            return {'status': 'error', 'error': data.get('error_msg') or f'Lỗi Code {err}', 'account': None}
    except Exception as e:
        return {'status': 'error', 'error': str(e)[:100], 'account': None}

# ━━━ TIN NHẮN TÙY BIẾN (TEMPLATES) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _load_templates():
    if os.path.exists(TEMPLATES_FILE):
        try:
            with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def _save_templates(items):
    try:
        with open(TEMPLATES_FILE, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

# ━━━ TELEGRAM BOT THÔNG BÁO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _load_telegram_config():
    if os.path.exists(TELEGRAM_CONFIG_FILE):
        try:
            with open(TELEGRAM_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "bot_token": "",
        "chat_id": "",
        "enabled": False,
        "notify_new_mvd": True,
        "notify_completed": True,
        "notify_cancelled": True
    }

def _save_telegram_config(cfg):
    try:
        with open(TELEGRAM_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def send_telegram_alert(text):
    """Gửi tin nhắn Telegram thông báo nếu được kích hoạt"""
    cfg = _load_telegram_config()
    if not cfg.get('enabled'):
        return False, "Telegram chưa bật"
    token = (cfg.get('bot_token') or '').strip()
    chat_id = (cfg.get('chat_id') or '').strip()
    if not token or not chat_id:
        return False, "Thiếu Token hoặc Chat ID"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=8) as res:
            res_data = json.loads(res.read().decode('utf-8'))
            if res_data.get('ok'):
                return True, "Gửi thành công"
            return False, res_data.get('description', 'Lỗi không xác định')
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='replace')
        return False, f"HTTP {e.code}: {err_msg}"
    except Exception as e:
        return False, str(e)

# ━━━ HÀNH TRÌNH VẬN CHUYỂN BƯU CỤC (TRACKING TIMELINE) ━━━━━━━━
def fetch_order_tracking_timeline(order_id, spc_st):
    """Lấy chi tiết toàn bộ các mốc hành trình bưu cục của đơn hàng"""
    token = clean_cookie_str(spc_st)
    headers = {**MOBILE_HEADERS, 'Cookie': f'SPC_ST={token};'}
    timeline = []
    carrier = ''
    tracking_no = ''
    order_sn = ''
    driver_info = {}

    # 1. Gọi API get_order_tracking_info của Shopee
    try:
        tr_url = f'https://shopee.vn/api/v4/order/get_order_tracking_info?order_id={order_id}'
        tr_data = fetch_shopee_json(tr_url, headers, timeout=8)
        data = tr_data.get('data') or {}
        carrier = data.get('carrier_name') or ''
        tracking_no = data.get('tracking_number') or ''
        list_events = data.get('tracking_list') or data.get('list') or []
        for ev in list_events:
            ev_time = ev.get('ctime') or ev.get('time') or 0
            time_str = datetime.datetime.fromtimestamp(ev_time).strftime("%H:%M %d/%m/%Y") if ev_time else ''
            timeline.append({
                'time': time_str,
                'timestamp': ev_time,
                'description': ev.get('description') or ev.get('text') or '',
                'status': ev.get('status') or '',
                'driver_name': ev.get('driver_name') or '',
                'driver_phone': ev.get('driver_phone') or ''
            })
    except Exception as e:
        print(f"[Timeline] Lỗi get_order_tracking_info: {e}")

    # 2. Fallback gọi get_order_detail nếu timeline chưa có mốc nào
    try:
        dt_url = f'https://shopee.vn/api/v4/order/get_order_detail?order_id={order_id}'
        d = fetch_shopee_json(dt_url, headers, timeout=8).get('data', {})
        order_sn = d.get('processing_info', {}).get('order_sn') or str(order_id)
        shipping = d.get('shipping', {}) or {}
        if not tracking_no:
            tracking_no = shipping.get('tracking_number') or ''
        if not carrier:
            carrier = (shipping.get('fulfilment_carrier', {}).get('text') or 
                       shipping.get('masked_carrier', {}).get('text') or 'SPX Express')
        tracking_info = shipping.get('tracking_info', {}) or {}
        driver_info = {
            'driver_name': tracking_info.get('driver_name') or '',
            'driver_phone': tracking_info.get('driver_phone') or ''
        }
        if not timeline:
            raw_list = tracking_info.get('tracking_list') or tracking_info.get('list') or shipping.get('tracking_list') or []
            for ev in raw_list:
                ev_time = ev.get('ctime') or ev.get('time') or 0
                time_str = datetime.datetime.fromtimestamp(ev_time).strftime("%H:%M %d/%m/%Y") if ev_time else ''
                timeline.append({
                    'time': time_str,
                    'timestamp': ev_time,
                    'description': ev.get('description') or ev.get('text') or '',
                    'status': ev.get('status') or '',
                    'driver_name': ev.get('driver_name') or '',
                    'driver_phone': ev.get('driver_phone') or ''
                })
        if not timeline and tracking_info.get('description'):
            ctime = tracking_info.get('ctime') or int(time.time())
            time_str = datetime.datetime.fromtimestamp(ctime).strftime("%H:%M %d/%m/%Y")
            timeline.append({
                'time': time_str,
                'timestamp': ctime,
                'description': tracking_info.get('description'),
                'status': 'current',
                'driver_name': tracking_info.get('driver_name') or '',
                'driver_phone': tracking_info.get('driver_phone') or ''
            })
    except Exception as e:
        print(f"[Timeline] Lỗi fallback get_order_detail: {e}")

    return {
        'order_id': str(order_id),
        'order_sn': order_sn,
        'tracking_no': tracking_no,
        'carrier': carrier,
        'driver_info': driver_info,
        'timeline': timeline
    }

def extract_cookie_orders(spc_st, note_name="", order_limit=30):
    """
    Trích xuất toàn bộ đơn hàng và thông tin chi tiết:
    Mã đơn, MVĐ, Trạng thái, Người nhận, SĐT, Địa chỉ, Sản phẩm, Link SP, SĐT ship, COD, Thời gian đặt, Last check
    """
    token = clean_cookie_str(spc_st)
    cookie_prefix = token[:10] + '...' if len(token) > 10 else token
    cookie_display = f"SPC_ST={cookie_prefix}"
    
    res = {
        'cookie_preview': cookie_display,
        'cookie_raw': token,
        'account': None,
        'orders': [],
        'error': None,
        'duration_s': 0
    }

    if len(token) < 20:
        res['error'] = 'Cookie không hợp lệ hoặc quá ngắn'
        return res

    t0 = time.time()
    now_str = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")

    # ── Bước 1: Xác thực tài khoản ──
    acc_url = 'https://shopee.vn/api/v4/account/basic/get_account_info'
    acc_headers = {**MOBILE_HEADERS, 'Cookie': f'SPC_ST={token};'}
    
    userid = None
    try:
        data = fetch_shopee_json(acc_url, acc_headers, timeout=8)
        err = data.get('error')
        if err == 0 and data.get('data'):
            u = data['data']
            userid = u.get('userid')
            res['account'] = {
                'userid': userid,
                'username': u.get('username') or f'User_{userid}',
                'phone': u.get('phone') or '',
                'email': u.get('email') or ''
            }
        elif err == 19 or 'auth' in str(data.get('error_msg', '')).lower():
            res['error'] = 'Cookie đã hết hạn hoặc không tồn tại (Error 19)'
            res['duration_s'] = round(time.time() - t0, 2)
            return res
        else:
            res['error'] = data.get('error_msg') or f'Lỗi xác thực (Code {err})'
            res['duration_s'] = round(time.time() - t0, 2)
            return res
    except urllib.error.HTTPError as e:
        res['error'] = f'HTTP {e.code}: {e.reason}'
        res['duration_s'] = round(time.time() - t0, 2)
        return res
    except Exception as e:
        res['error'] = f'Lỗi kết nối tài khoản: {str(e)[:80]}'
        res['duration_s'] = round(time.time() - t0, 2)
        return res

    # ── Bước 2: Lấy danh sách order_id ──
    cookie_str = f'SPC_ST={token}; SPC_U={userid};'
    order_headers = {**MOBILE_HEADERS, 'Cookie': cookie_str}
    
    order_ids = []
    try:
        list_url = f'https://shopee.vn/api/v4/order/get_all_order_and_checkout_list?limit={order_limit}&offset=0'
        list_data = fetch_shopee_json(list_url, order_headers, timeout=10)
        
        items = list_data.get('new_data', {}).get('order_or_checkout_data', []) or []
        for it in items:
            oid = it.get('order_list_detail', {}).get('info_card', {}).get('order_id')
            if oid and oid not in order_ids:
                order_ids.append(oid)
    except Exception as e:
        res['error'] = f'Lỗi lấy danh sách đơn: {str(e)[:80]}'
        res['duration_s'] = round(time.time() - t0, 2)
        return res

    if not order_ids:
        res['duration_s'] = round(time.time() - t0, 2)
        return res

    # ── Bước 3: Lấy chi tiết từng đơn hàng ──
    def fetch_single_order(args):
        oid, order_idx, total_orders = args
        url = f'https://shopee.vn/api/v4/order/get_order_detail?order_id={oid}'
        try:
            d = fetch_shopee_json(url, order_headers, timeout=8).get('data', {})
            
            # 1. Mã đơn hàng (order_sn)
            order_sn = d.get('processing_info', {}).get('order_sn') or str(oid)
            
            # 2. Vận chuyển & MVĐ
            shipping = d.get('shipping', {}) or {}
            tracking_no = (shipping.get('tracking_number') or 
                           shipping.get('tracking_no') or 
                           shipping.get('carrier_tracking_number') or '')
            
            # Dự phòng lấy MVĐ từ package_list nếu shipping chưa có
            if not tracking_no and isinstance(d.get('package_list'), list) and d['package_list']:
                pkg = d['package_list'][0]
                if isinstance(pkg, dict):
                    tracking_no = pkg.get('tracking_number') or pkg.get('tracking_no') or ''
            
            carrier = (shipping.get('fulfilment_carrier', {}).get('text') or 
                       shipping.get('masked_carrier', {}).get('text') or 
                       'SPX Express')
            
            tracking_info = shipping.get('tracking_info', {}) or {}
            desc = tracking_info.get('description', '') or ''
            status_label = d.get('status', {}).get('status_label', {}).get('text', '') or ''
            
            # SĐT Shipper / Tài xế
            driver_phone = tracking_info.get('driver_phone') or tracking_info.get('driver_name') or ''
            
            # 3. Phân loại màu Badge trạng thái theo chuẩn Sheet
            desc_lower = desc.lower()
            label_lower = status_label.lower()
            if 'hủy' in desc_lower or 'cancel' in label_lower:
                badge_type = 'red'
                badge_text = '❌ Đơn hàng đã hủy'
            elif 'giao thành công' in desc_lower or 'delivered' in label_lower or 'hoàn thành' in desc_lower:
                badge_type = 'green'
                badge_text = '✅ Giao hàng thành công'
            elif 'thao tác' in desc_lower or 'chờ thanh toán' in desc_lower:
                badge_type = 'purple'
                badge_text = 'Ban đang thao tác...'
            elif desc or tracking_no:
                badge_type = 'blue'
                badge_text = desc if len(desc) <= 30 else (desc[:28] + '...')
            else:
                badge_type = 'gray'
                badge_text = '➖'

            # 4. Người nhận, SĐT, Địa chỉ
            addr = d.get('address', {}) or {}
            receiver_name = addr.get('shipping_name') or ''
            receiver_phone = addr.get('shipping_phone') or ''
            receiver_address = addr.get('shipping_address') or ''

            # 5. Sản phẩm & Link Sản Phẩm & Ảnh (Bọc try-except tuyệt đối an toàn)
            products = []
            product_images = []
            product_url = ""
            try:
                info_card = d.get('info_card', {}) or {}
                for pc in (info_card.get('parcel_cards') or []):
                    if not isinstance(pc, dict): continue
                    pinfo = pc.get('product_info') or {}
                    for grp in (pinfo.get('item_groups') or []):
                        if not isinstance(grp, dict): continue
                        for it in (grp.get('items') or []):
                            if not isinstance(it, dict): continue
                            name = it.get('name')
                            if name:
                                products.append(name)
                            img_h = it.get('image') or (it.get('images', [None])[0] if isinstance(it.get('images'), list) and it.get('images') else None)
                            if img_h and isinstance(img_h, str):
                                if not img_h.startswith('http'):
                                    product_images.append(f"https://down-vn.img.susercontent.com/file/{img_h}")
                                else:
                                    product_images.append(img_h)
                            if not product_url and it.get('item_id') and it.get('shop_id'):
                                product_url = f"https://shopee.vn/product/{it.get('shop_id')}/{it.get('item_id')}"
            except Exception:
                pass
            
            product_display = products[0] if products else '--'
            product_image = product_images[0] if product_images else ''

            # Lộ trình bưu cục nhanh (Bọc try-except an toàn)
            timeline = []
            try:
                raw_timeline = tracking_info.get('tracking_list') or tracking_info.get('list') or shipping.get('tracking_list') or []
                if isinstance(raw_timeline, list):
                    for ev in raw_timeline:
                        if not isinstance(ev, dict): continue
                        ev_time = ev.get('ctime') or ev.get('time') or 0
                        time_str = ''
                        if ev_time:
                            try:
                                t_val = int(ev_time)
                                if t_val > 100000000000: t_val = t_val // 1000
                                time_str = datetime.datetime.fromtimestamp(t_val).strftime("%H:%M %d/%m/%Y")
                            except Exception:
                                time_str = ''
                        timeline.append({
                            'time': time_str,
                            'timestamp': ev_time,
                            'description': ev.get('description') or ev.get('text') or '',
                            'status': ev.get('status') or '',
                            'driver_name': ev.get('driver_name') or '',
                            'driver_phone': ev.get('driver_phone') or ''
                        })
            except Exception:
                timeline = []

            # 6. COD & Thanh toán
            payment_info = info_card.get('parcel_cards', [{}])[0].get('payment_info', {}) if isinstance(info_card.get('parcel_cards'), list) and info_card.get('parcel_cards') else {}
            extra_info = payment_info.get('extra_info', {})
            channel_name = d.get('payment_method', {}).get('payment_channel_name', {}).get('text', '')
            is_cod = 'nhận hàng' in channel_name.lower() or 'cod' in channel_name.lower()
            
            cod_val = 0
            if extra_info.get('cod_amount_to_pay') is not None:
                cod_val = int(extra_info['cod_amount_to_pay']) // 100000
            elif is_cod:
                cod_val = int(info_card.get('final_total', 0)) // 100000
            
            cod_str = f"{cod_val:,} đ".replace(',', '.')

            # 7. Thời gian & ngày đặt
            try:
                ctime = tracking_info.get('ctime') or d.get('ctime') or int(time.time())
                t_val = int(ctime)
                if t_val > 100000000000: t_val = t_val // 1000
                dt = datetime.datetime.fromtimestamp(t_val)
                order_date = dt.strftime('%Y-%m-%d')
                order_day = dt.strftime('%d')
                order_time = dt.strftime('%H:%M %d/%m/%Y')
            except Exception:
                dt = datetime.datetime.now()
                order_date = dt.strftime('%Y-%m-%d')
                order_day = dt.strftime('%d')
                order_time = dt.strftime('%H:%M %d/%m/%Y')
                ctime = int(time.time())

            # 8. Tag Đơn (ví dụ: 'Đơn 2' nếu tài khoản có nhiều đơn)
            order_tag = f"Đơn {order_idx}" if total_orders > 1 else ""

            return {
                'order_id': str(oid),
                'order_sn': order_sn,
                'tracking_no': tracking_no,
                'has_tracking': bool(tracking_no),
                'carrier': carrier,
                'status_desc': desc,
                'status_badge_type': badge_type,
                'status_badge_text': badge_text,
                'receiver_name': receiver_name,
                'receiver_phone': receiver_phone,
                'receiver_address': receiver_address,
                'product_name': product_display,
                'product_url': product_url,
                'product_image': product_image,
                'driver_phone': driver_phone,
                'all_products': products,
                'timeline': timeline,
                'cod_val': cod_val,
                'cod_amount': cod_str,
                'payment_status': 'Chưa thanh toán' if cod_val > 0 else '—',
                'order_date': order_date,
                'order_day': order_day,
                'order_time': order_time,
                'last_check': now_str,
                'timestamp': ctime,
                'order_tag': order_tag,
                'cookie_preview': cookie_display,
                'cookie_raw': token,
                'note_name': note_name
            }
        except Exception as e:
            return {
                'order_id': str(oid),
                'order_sn': str(oid),
                'tracking_no': '',
                'has_tracking': False,
                'carrier': 'N/A',
                'status_desc': f'Lỗi: {str(e)[:50]}',
                'status_badge_type': 'gray',
                'status_badge_text': '➖',
                'receiver_name': '',
                'receiver_phone': '',
                'receiver_address': '',
                'product_name': '--',
                'product_url': '',
                'product_image': '',
                'driver_phone': '',
                'all_products': [],
                'timeline': [],
                'cod_val': 0,
                'cod_amount': '0 đ',
                'payment_status': '—',
                'order_date': datetime.datetime.now().strftime('%Y-%m-%d'),
                'order_day': datetime.datetime.now().strftime('%d'),
                'order_time': datetime.datetime.now().strftime('%H:%M %d/%m/%Y'),
                'last_check': now_str,
                'timestamp': int(time.time()),
                'order_tag': f"Đơn {order_idx}" if total_orders > 1 else "",
                'cookie_preview': cookie_display,
                'cookie_raw': token,
                'note_name': note_name
            }

    tasks = [(oid, idx + 1, len(order_ids)) for idx, oid in enumerate(order_ids)]
    with ThreadPoolExecutor(max_workers=min(8, len(order_ids) or 1)) as pool:
        orders = list(pool.map(fetch_single_order, tasks))

    res['orders'] = orders
    res['duration_s'] = round(time.time() - t0, 2)
    return res


# ━━━ HTTP Server Handler ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TrackingRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/ping':
            sb_ok = _is_supabase_configured()
            self._json(200, {
                'status': 'ok',
                'engine': 'shopee-sheet-v4.2-supabase',
                'supabase': sb_ok,
                'supabase_url': SUPABASE_URL[:40] + '...' if SUPABASE_URL else ''
            })

        elif self.path == '/api/zalo/orders':
            try:
                zalo_file = os.path.join(DIRECTORY, "zalo_orders.json")
                if os.path.exists(zalo_file):
                    with open(zalo_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self._json(200, {'success': True, 'data': data})
                else:
                    self._json(200, {'success': True, 'data': {'orders': [], 'count': 0}})
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path.startswith('/api/zalo/lookup-mvd'):
            try:
                import urllib.parse
                parsed_url = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed_url.query)
                phone_query = params.get('phone', [''])[0].strip()

                target_digits = ''.join(c for c in phone_query if c.isdigit())
                if target_digits.startswith('84') and len(target_digits) >= 10:
                    target_digits = '0' + target_digits[2:]
                target_last9 = target_digits[-9:] if len(target_digits) >= 9 else target_digits

                rows = []
                if _is_supabase_configured():
                    try:
                        sb = get_supabase()
                        if sb:
                            result = sb.table('orders').select('*').execute()
                            rows = result.data or []
                    except Exception as ex:
                        print(f"[!] Supabase lookup error: {ex}")

                if not rows and os.path.exists(DRAFT_FILE):
                    try:
                        with open(DRAFT_FILE, 'r', encoding='utf-8') as f:
                            d = json.load(f)
                        rows = d.get('rows', [])
                    except Exception:
                        pass

                matched = []
                for r in rows:
                    r_phone = str(r.get('receiver_phone', '')).strip()
                    r_digits = ''.join(c for c in r_phone if c.isdigit())
                    if r_digits.startswith('84') and len(r_digits) >= 10:
                        r_digits = '0' + r_digits[2:]
                    r_last9 = r_digits[-9:] if len(r_digits) >= 9 else r_digits

                    note_str = str(r.get('note_name', '')).strip()
                    tag_str = str(r.get('order_tag', '')).strip()

                    is_match = False
                    if target_last9 and (target_last9 == r_last9 or target_last9 in note_str or target_last9 in tag_str or (target_digits and (target_digits in note_str or target_digits in tag_str))):
                        is_match = True

                    if is_match:
                        matched.append({
                            'order_sn': r.get('order_sn', ''),
                            'tracking_no': r.get('tracking_no', ''),
                            'carrier': r.get('carrier', ''),
                            'status_desc': r.get('status_desc', '') or r.get('status_badge_text', ''),
                            'receiver_name': r.get('receiver_name', ''),
                            'receiver_phone': r.get('receiver_phone', ''),
                            'note_name': r.get('note_name', ''),
                            'order_tag': r.get('order_tag', ''),
                            'product_name': r.get('product_name', ''),
                            'cod_amount': r.get('cod_amount', ''),
                            'driver_phone': r.get('driver_phone', ''),
                            'order_time': r.get('order_time', '')
                        })

                self._json(200, {
                    'success': True,
                    'phone': phone_query,
                    'count': len(matched),
                    'orders': matched
                })
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/load-draft':
            # ── Thử tải từ Supabase trước ──
            if _is_supabase_configured():
                try:
                    sb = get_supabase()
                    if sb:
                        result = sb.table('orders').select('*').order('stt').execute()
                        rows = result.data or []
                        # Loại bỏ cột nội bộ Supabase (created_at, updated_at)
                        for row in rows:
                            row.pop('created_at', None)
                            row.pop('updated_at', None)
                        now_str = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                        print(f"[Supabase] Đã tải {len(rows)} đơn hàng từ cloud.")
                        self._json(200, {
                            'rows': rows,
                            'count': len(rows),
                            'updated_at': now_str,
                            'source': 'supabase'
                        })
                        return
                except Exception as e:
                    print(f"[!] Supabase load lỗi, fallback local: {e}")

            # ── Fallback: đọc từ draft.json cục bộ ──
            try:
                if os.path.exists(DRAFT_FILE):
                    with open(DRAFT_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    data['source'] = 'local'
                    self._json(200, data)
                else:
                    self._json(200, {'rows': [], 'count': 0, 'updated_at': None, 'source': 'empty'})
            except Exception as e:
                self._json(500, {'error': f'Không thể đọc dữ liệu: {str(e)}'})

        elif self.path == '/api/supabase-status':
            """Endpoint kiểm tra trạng thái kết nối Supabase."""
            configured = _is_supabase_configured()
            if configured:
                try:
                    sb = get_supabase()
                    sb.table('orders').select('id').limit(1).execute()
                    self._json(200, {
                        'connected': True,
                        'url': SUPABASE_URL[:40] + '...'
                    })
                except Exception as e:
                    self._json(200, {'connected': False, 'error': str(e)})
            else:
                self._json(200, {
                    'connected': False,
                    'configured': False,
                    'message': 'Chưa cấu hình SUPABASE_URL và SUPABASE_KEY trong file .env'
                })

        elif self.path == '/api/proxy/info':
            # Tự động nạp thông tin proxy hiện tại nếu có key mà chưa có IP
            if not proxy_state.get('current_proxy'):
                try:
                    if proxy_state.get('provider') == 'kiotproxy' and proxy_state.get('key'):
                        kiotproxy_get_current()
                    elif proxy_state.get('provider') == 'proxyvn' and proxy_state.get('proxyvn_key'):
                        proxyvn_get_ip()
                except Exception:
                    pass

            kp_k = proxy_state.get('key', '')
            kp_preview = (kp_k[:4] + '...' + kp_k[-4:]) if len(kp_k) > 8 else (kp_k or '')
            pvn_k = proxy_state.get('proxyvn_key', '')
            pvn_preview = (pvn_k[:4] + '...' + pvn_k[-4:]) if len(pvn_k) > 8 else (pvn_k or '')
            self._json(200, {
                'provider': proxy_state.get('provider', 'proxyvn'),
                'enabled': proxy_state.get('enabled', False),
                'auto_rotate': proxy_state.get('auto_rotate', True),
                # KiotProxy
                'key_raw': kp_k,
                'key_preview': kp_preview,
                'has_key': bool(kp_k),
                'region': proxy_state.get('region', ''),
                # ProxyVN
                'proxyvn_key': pvn_k,
                'proxyvn_key_preview': pvn_preview,
                'has_proxyvn_key': bool(pvn_k),
                'proxyvn_nhamang': proxy_state.get('proxyvn_nhamang', 'Random'),
                'proxyvn_tinhthanh': proxy_state.get('proxyvn_tinhthanh', '0'),
                'proxyvn_current_ip': proxy_state.get('proxyvn_current_ip', ''),
                'proxyvn_location': proxy_state.get('proxyvn_location', ''),
                'proxyvn_expire_s': proxy_state.get('proxyvn_expire_s', 0),
                'proxyvn_expire_at': proxy_state.get('proxyvn_expire_at', ''),
                # Common state
                'current': proxy_state.get('current_proxy'),
                'proxy_url': proxy_state.get('proxy_url'),
                'last_check': proxy_state.get('last_check'),
                'last_error': proxy_state.get('last_error')
            })

        elif self.path == '/api/vault/list':
            try:
                items = _load_vault()
                self._json(200, {'success': True, 'items': items or []})
            except Exception as e:
                print(f"[!] Lỗi đọc kho cookie: {e}")
                fb_items = []
                if os.path.exists(VAULT_FILE):
                    try:
                        with open(VAULT_FILE, 'r', encoding='utf-8') as f:
                            fb_items = json.load(f)
                    except Exception:
                        pass
                self._json(200, {'success': True, 'items': fb_items, 'warning': str(e)})

        elif self.path == '/api/templates/list':
            try:
                items = _load_templates()
                self._json(200, {'success': True, 'items': items})
            except Exception as e:
                self._json(500, {'error': f'Lỗi đọc mẫu tin nhắn: {str(e)}'})

        elif self.path == '/api/telegram/info':
            try:
                cfg = _load_telegram_config()
                token = cfg.get('bot_token', '')
                masked_token = (token[:6] + '...' + token[-4:]) if len(token) > 12 else (token or '')
                self._json(200, {
                    'enabled': cfg.get('enabled', False),
                    'chat_id': cfg.get('chat_id', ''),
                    'bot_token_masked': masked_token,
                    'has_token': bool(token),
                    'notify_new_mvd': cfg.get('notify_new_mvd', True),
                    'notify_completed': cfg.get('notify_completed', True),
                    'notify_cancelled': cfg.get('notify_cancelled', True)
                })
            except Exception as e:
                self._json(500, {'error': f'Lỗi đọc Telegram config: {str(e)}'})

        elif self.path == '/api/autoreg/status' or self.path.startswith('/api/autoreg/status?'):
            try:
                if not auto_reg_mgr:
                    return self._json(500, {'error': 'Autoreg manager chưa sẵn sàng'})
                st = auto_reg_mgr.get_status()
                # Kiểm tra số dư CMSNPA (Gửi kèm User-Agent để tránh Cloudflare 403)
                credits = None
                try:
                    headers = {
                        "Authorization": f"Bearer {CMSNPA_KEY}",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "application/json"
                    }
                    req = urllib.request.Request(f"{CMSNPA_BASE}/api/v1/balance", headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        b_data = json.loads(resp.read().decode('utf-8'))
                        if b_data.get('ok'):
                            credits = b_data.get('credits')
                except Exception as _bal_err:
                    print(f"[!] Lỗi đọc số dư CMSNPA: {_bal_err}")

                st['credits'] = credits
                st['services'] = AUTOREG_SERVICES
                st['telegram'] = get_telegram_account_info('refresh' in self.path)
                if not st.get('kiotproxy_key') and proxy_state.get('key'):
                    st['kiotproxy_key'] = proxy_state.get('key')
                self._json(200, {'success': True, 'data': st})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/autoreg/accounts':
            try:
                if not auto_reg_mgr:
                    return self._json(500, {'error': 'Autoreg manager chưa sẵn sàng'})
                accs = auto_reg_mgr.get_accounts()
                self._json(200, {'success': True, 'accounts': accs})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/telegram/status' or self.path.startswith('/api/telegram/status?'):
            try:
                if not tg_auth_mgr:
                    return self._json(500, {'error': 'Telegram auth manager chưa sẵn sàng'})
                is_refresh = 'refresh' in self.path
                info = tg_auth_mgr.get_info(force_refresh=is_refresh)
                self._json(200, {'success': True, 'data': info})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/telegram/slots':
            try:
                if not tg_auth_mgr:
                    return self._json(500, {'error': 'Telegram auth manager chưa sẵn sàng'})
                slots = tg_auth_mgr.get_preset_slots()
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/bot-dks/status' or self.path.startswith('/api/bot-dks/status?'):
            try:
                if not dks_mgr:
                    return self._json(500, {'error': 'DangKyShopee manager chưa sẵn sàng'})
                st = dks_mgr.get_status()
                self._json(200, {'success': True, 'data': st})
            except Exception as e:
                self._json(500, {'error': str(e)})

        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/process':
            try:
                body = self._read_body()
                spc_st = body.get('spc_st', '').strip()
                note_name = body.get('note_name', '').strip()
                if not spc_st:
                    return self._json(400, {'error': 'Vui lòng cung cấp cookie SPC_ST'})
                
                result = extract_cookie_orders(spc_st, note_name=note_name)
                self._json(200, result)
            except Exception as e:
                self._json(500, {'error': f'Lỗi hệ thống: {str(e)}'})

        elif self.path == '/api/save-draft':
            try:
                body = self._read_body()
                rows = body.get('rows', [])
                now_str = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")

                # ── 1. Luôn lưu backup local trước (đảm bảo không mất dữ liệu) ──
                local_data = {'rows': rows, 'count': len(rows), 'updated_at': now_str}
                try:
                    with open(DRAFT_FILE, 'w', encoding='utf-8') as f:
                        json.dump(local_data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    print(f"[!] Không thể ghi draft.json: {e}")

                # ── 2. Thử lưu lên Supabase ──
                if _is_supabase_configured():
                    try:
                        sb = get_supabase()
                        if sb:
                            now_iso = datetime.datetime.utcnow().isoformat()

                            if not rows:
                                # Xóa sạch toàn bộ trên Supabase
                                sb.table('orders').delete().neq('id', '').execute()
                                print("[Supabase] Đã xóa sạch toàn bộ đơn hàng.")
                            else:
                                # Lấy danh sách id đang tồn tại trên Supabase
                                existing_res = sb.table('orders').select('id').execute()
                                existing_ids = {r['id'] for r in (existing_res.data or [])}
                                new_ids = {r['id'] for r in rows if r.get('id')}

                                # Xóa các đơn đã bị remove ở frontend
                                to_delete = existing_ids - new_ids
                                if to_delete:
                                    sb.table('orders').delete().in_('id', list(to_delete)).execute()
                                    print(f"[Supabase] Đã xóa {len(to_delete)} đơn đã hủy.")

                                # Chuẩn bị dữ liệu upsert (thêm updated_at)
                                upsert_rows = []
                                for r in rows:
                                    row_data = dict(r)
                                    row_data['updated_at'] = now_iso
                                    # Đảm bảo all_products là JSON-serializable
                                    if 'all_products' in row_data and isinstance(row_data['all_products'], list):
                                        row_data['all_products'] = row_data['all_products']
                                    upsert_rows.append(row_data)

                                def _safe_upsert_batch(batch):
                                    clean_batch = [dict(item) for item in batch]
                                    for _ in range(6):
                                        try:
                                            sb.table('orders').upsert(clean_batch, on_conflict='id').execute()
                                            return
                                        except Exception as ex:
                                            err_msg = str(ex)
                                            import re
                                            m = re.search(r"Could not find the '([^']+)' column", err_msg)
                                            if m:
                                                missing_c = m.group(1)
                                                for item in clean_batch:
                                                    item.pop(missing_c, None)
                                                continue
                                            raise ex

                                # Upsert theo batch 500
                                BATCH = 500
                                for i in range(0, len(upsert_rows), BATCH):
                                    _safe_upsert_batch(upsert_rows[i:i+BATCH])


                            print(f"[Supabase] Đã lưu {len(rows)} đơn hàng lên cloud.")
                            self._json(200, {
                                'success': True,
                                'count': len(rows),
                                'saved_at': now_str,
                                'source': 'supabase'
                            })
                            return
                    except Exception as e:
                        print(f"[!] Supabase save lỗi, đã lưu local: {e}")
                        self._json(200, {
                            'success': True,
                            'count': len(rows),
                            'saved_at': now_str,
                            'source': 'local',
                            'warning': f'Supabase lỗi, lưu cục bộ: {str(e)[:60]}'
                        })
                        return

                # ── Không có Supabase: chỉ lưu local ──
                self._json(200, {
                    'success': True,
                    'count': len(rows),
                    'saved_at': now_str,
                    'source': 'local'
                })

            except Exception as e:
                self._json(500, {'error': f'Không thể lưu dữ liệu: {str(e)}'})

        elif self.path == '/api/proxy/save':
            try:
                body = self._read_body()
                provider = body.get('provider', 'kiotproxy').strip()
                enabled = bool(body.get('enabled', False))
                auto_rotate = bool(body.get('auto_rotate', True))

                proxy_state['provider'] = provider
                proxy_state['enabled'] = enabled
                proxy_state['auto_rotate'] = auto_rotate

                if provider == 'proxyvn':
                    pv_key = body.get('proxyvn_key', '').strip()
                    if pv_key:
                        proxy_state['proxyvn_key'] = pv_key
                    proxy_state['proxyvn_nhamang'] = body.get('nhamang', 'Random').strip()
                    proxy_state['proxyvn_tinhthanh'] = str(body.get('tinhthanh', '0')).strip()
                else:
                    # KiotProxy
                    kp_key = body.get('key', '').strip()
                    if kp_key:
                        proxy_state['key'] = kp_key
                    proxy_state['region'] = body.get('region', '').strip()

                # Luôn lưu cấu hình xuống đĩa trước
                _save_proxy_config()

                init_res = None
                # Luôn thử kết nối để lấy thông tin IP khi có key
                try:
                    if provider == 'proxyvn' and proxy_state.get('proxyvn_key'):
                        init_res = proxyvn_get_ip()
                    elif provider == 'kiotproxy' and proxy_state.get('key'):
                        init_res = kiotproxy_get_current()
                    _save_proxy_config()
                except Exception as ex:
                    init_res = {'success': False, 'message': f'Lưu thành công, nhưng kết nối proxy lỗi: {str(ex)}'}

                self._json(200, {
                    'success': True,
                    'provider': provider,
                    'enabled': proxy_state['enabled'],
                    'auto_rotate': proxy_state['auto_rotate'],
                    'current': proxy_state.get('current_proxy'),
                    'proxy_url': proxy_state.get('proxy_url'),
                    'init_res': init_res,
                    'message': f'Đã lưu cấu hình {provider} thành công'
                })
            except Exception as e:
                self._json(500, {'error': f'Lỗi lưu cấu hình: {str(e)}'})

        elif self.path == '/api/proxy/toggle':
            try:
                body = self._read_body()
                proxy_state['enabled'] = bool(body.get('enabled', False))
                if proxy_state['enabled'] and not proxy_state.get('current_proxy'):
                    if proxy_state.get('provider') == 'proxyvn' and proxy_state.get('proxyvn_key'):
                        proxyvn_get_ip()
                    elif proxy_state.get('key'):
                        kiotproxy_get_current()
                _save_proxy_config()
                self._json(200, {
                    'success': True,
                    'enabled': proxy_state['enabled'],
                    'current': proxy_state.get('current_proxy')
                })
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/proxy/new-ip':
            try:
                body = self._read_body()
                provider = body.get('provider') or proxy_state.get('provider', 'kiotproxy')
                if provider == 'proxyvn':
                    res = proxyvn_get_ip(nhamang=body.get('nhamang'), tinhthanh=body.get('tinhthanh'))
                else:
                    region = body.get('region')
                    res = kiotproxy_get_new(region=region)
                self._json(200, res)
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/proxy/proxyvn-get-ip':
            try:
                body = self._read_body()
                nhamang = body.get('nhamang')
                tinhthanh = body.get('tinhthanh')
                res = proxyvn_get_ip(nhamang=nhamang, tinhthanh=tinhthanh)
                self._json(200, res)
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/proxy/out':
            try:
                res = kiotproxy_out()
                self._json(200, res)
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/proxy/test-key':
            try:
                body = self._read_body()
                provider = body.get('provider', 'kiotproxy')
                if provider == 'kiotproxy':
                    key = body.get('key', '').strip() or proxy_state.get('key', '')
                    if not key:
                        return self._json(400, {'success': False, 'error': 'Vui lòng nhập Key KiotProxy để kiểm tra'})
                    res = kiotproxy_get_current(key=key)
                    if res.get('success') and res.get('data'):
                        # Lưu key và kích hoạt vào proxy_state
                        proxy_state['key'] = key
                        proxy_state['provider'] = 'kiotproxy'
                        proxy_state['enabled'] = True
                        _save_proxy_config()
                        
                        p_data = res.get('data') or {}
                        p_url = _format_proxy_url(p_data)
                        latency_ms = None
                        if p_url:
                            try:
                                t0 = time.time()
                                ph = urllib.request.ProxyHandler({'http': p_url, 'https': p_url})
                                hh = urllib.request.HTTPSHandler(context=ssl_ctx)
                                op = urllib.request.build_opener(ph, hh)
                                treq = urllib.request.Request('https://api.ipify.org?format=json', headers={'User-Agent': 'ShopeeTracker/4.2'})
                                with op.open(treq, timeout=8) as r:
                                    latency_ms = round((time.time() - t0) * 1000)
                            except Exception:
                                pass
                        
                        self._json(200, {
                            'success': True,
                            'ip': p_data.get('realIpAddress') or p_data.get('host'),
                            'port': p_data.get('httpPort'),
                            'location': p_data.get('location') or p_data.get('region') or 'Việt Nam',
                            'latency_ms': latency_ms,
                            'expiration_at': p_data.get('expirationAt'),
                            'ttl': p_data.get('ttl'),
                            'data': p_data,
                            'message': f"Key hợp lệ! IP: {p_data.get('realIpAddress') or p_data.get('host')}"
                        })
                    else:
                        err_msg = res.get('message') or res.get('error') or 'Không thể kết nối hoặc Key không hợp lệ'
                        self._json(200, {'success': False, 'error': err_msg})
                else:
                    key = body.get('key', '').strip() or proxy_state.get('proxyvn_key', '')
                    nm = body.get('nhamang')
                    tt = body.get('tinhthanh')
                    if not key:
                        return self._json(400, {'success': False, 'error': 'Vui lòng nhập Key ProxyVN để kiểm tra'})
                    res = proxyvn_get_ip(key=key, nhamang=nm, tinhthanh=tt)
                    if res.get('success'):
                        proxy_state['proxyvn_key'] = key
                        proxy_state['provider'] = 'proxyvn'
                        proxy_state['enabled'] = True
                        _save_proxy_config()
                        self._json(200, {
                            'success': True,
                            'ip': res.get('data', {}).get('ip'),
                            'port': res.get('data', {}).get('port'),
                            'location': res.get('data', {}).get('location'),
                            'data': res.get('data'),
                            'message': f"Key hợp lệ! IP: {res.get('data', {}).get('ip')}"
                        })
                    else:
                        self._json(200, {'success': False, 'error': res.get('message', 'Lỗi kết nối ProxyVN')})
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/proxy/test':
            try:
                body = self._read_body()
                provider = body.get('provider') or proxy_state.get('provider', 'kiotproxy')
                key = body.get('key', '').strip()
                if provider == 'kiotproxy' and key:
                    proxy_state['key'] = key
                    proxy_state['provider'] = 'kiotproxy'
                    kiotproxy_get_current(key=key)
                elif provider == 'proxyvn' and key:
                    proxy_state['proxyvn_key'] = key
                    proxy_state['provider'] = 'proxyvn'
                    proxyvn_get_ip(key=key)

                # Nếu chưa có proxy_url thì thử lấy
                if not proxy_state.get('proxy_url'):
                    if proxy_state.get('provider') == 'proxyvn' and proxy_state.get('proxyvn_key'):
                        proxyvn_get_ip()
                    elif proxy_state.get('key'):
                        kiotproxy_get_current()
                p_url = proxy_state.get('proxy_url')
                if not p_url:
                    return self._json(400, {'error': 'Chưa có Proxy đang hoạt động. Vui lòng kiểm tra lại Key.'})
                
                t0 = time.time()
                proxy_handler = urllib.request.ProxyHandler({'http': p_url, 'https': p_url})
                https_handler = urllib.request.HTTPSHandler(context=ssl_ctx)
                opener = urllib.request.build_opener(proxy_handler, https_handler)
                
                test_req = urllib.request.Request(
                    'https://api.ipify.org?format=json',
                    headers={'User-Agent': 'ShopeeTracker/4.2'}
                )
                with opener.open(test_req, timeout=10) as res:
                    ip_data = json.loads(res.read().decode('utf-8'))
                    latency_ms = round((time.time() - t0) * 1000)
                    cur_prov = proxy_state.get('provider', 'kiotproxy')
                    cp = proxy_state.get('current_proxy') or {}
                    self._json(200, {
                        'success': True,
                        'ip': ip_data.get('ip'),
                        'latency_ms': latency_ms,
                        'proxy_url': p_url,
                        'provider': cur_prov,
                        'nhamang': cp.get('nhamang', 'KiotProxy' if cur_prov == 'kiotproxy' else ''),
                        'location': cp.get('location', ''),
                        'expire_at': cp.get('expire_at', '')
                    })
            except Exception as e:
                self._json(500, {'error': f'Kiểm tra kết nối Proxy thất bại: {str(e)}'})

        elif self.path == '/api/vault/save':
            try:
                body = self._read_body()
                item_id = body.get('id', '').strip()
                name = body.get('name', '').strip() or 'Shop mới'
                cookie = body.get('cookie', '').strip()
                tags = body.get('tags', '').strip()
                notes = body.get('notes', '').strip()
                
                if not cookie:
                    return self._json(400, {'error': 'Cookie không được để trống'})
                
                token = clean_cookie_str(cookie)
                vault = _load_vault()
                now_str = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                
                # Kiểm tra sức khỏe cookie trước khi lưu (bọc an toàn tránh lỗi mạng làm hỏng việc lưu)
                try:
                    health = check_cookie_health(token)
                except Exception as ex:
                    health = {'status': 'unknown', 'error': str(ex)[:80]}
                
                if item_id:
                    found = False
                    for it in vault:
                        if it.get('id') == item_id:
                            it['name'] = name
                            it['cookie'] = token
                            it['tags'] = tags
                            it['notes'] = notes
                            it['updated_at'] = now_str
                            it['status'] = health.get('status', 'unknown')
                            if health.get('username'):
                                it['username'] = health.get('username')
                            if health.get('error'):
                                it['last_error'] = health.get('error')
                            found = True
                            break
                    if not found:
                        item_id = str(int(time.time() * 1000))
                        vault.append({
                            'id': item_id,
                            'name': name,
                            'cookie': token,
                            'tags': tags,
                            'notes': notes,
                            'status': health.get('status', 'unknown'),
                            'username': health.get('username', ''),
                            'created_at': now_str,
                            'updated_at': now_str
                        })
                else:
                    item_id = str(int(time.time() * 1000))
                    vault.append({
                        'id': item_id,
                        'name': name,
                        'cookie': token,
                        'tags': tags,
                        'notes': notes,
                        'status': health.get('status', 'unknown'),
                        'username': health.get('username', ''),
                        'created_at': now_str,
                        'updated_at': now_str
                    })
                
                _save_vault(vault)
                self._json(200, {'success': True, 'item_id': item_id, 'health': health, 'items': vault})
            except Exception as e:
                self._json(500, {'error': f'Lỗi lưu shop: {str(e)}'})

        elif self.path == '/api/vault/delete':
            try:
                body = self._read_body()
                item_id = body.get('id', '').strip()
                vault = _load_vault()
                vault = [it for it in vault if it.get('id') != item_id]
                _save_vault(vault)
                self._json(200, {'success': True, 'items': vault})
            except Exception as e:
                self._json(500, {'error': f'Lỗi xóa shop: {str(e)}'})

        elif self.path == '/api/vault/check':
            try:
                body = self._read_body()
                item_id = body.get('id', '').strip()
                check_all = body.get('all', False)
                vault = _load_vault()
                now_str = datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                
                if check_all:
                    for it in vault:
                        ck = it.get('cookie', '')
                        try:
                            h = check_cookie_health(ck)
                        except Exception as ex:
                            h = {'status': 'error', 'error': str(ex)[:80]}
                        it['status'] = h.get('status', 'unknown')
                        it['last_checked'] = now_str
                        if h.get('username'):
                            it['username'] = h.get('username')
                        if h.get('error'):
                            it['last_error'] = h.get('error')
                        else:
                            it['last_error'] = None
                    _save_vault(vault)
                    self._json(200, {'success': True, 'items': vault})
                else:
                    target_item = None
                    for it in vault:
                        if it.get('id') == item_id:
                            target_item = it
                            break
                    if not target_item:
                        return self._json(404, {'error': 'Không tìm thấy shop này trong kho'})
                    try:
                        h = check_cookie_health(target_item.get('cookie', ''))
                    except Exception as ex:
                        h = {'status': 'error', 'error': str(ex)[:80]}
                    target_item['status'] = h.get('status', 'unknown')
                    target_item['last_checked'] = now_str
                    if h.get('username'):
                        target_item['username'] = h.get('username')
                    if h.get('error'):
                        target_item['last_error'] = h.get('error')
                    else:
                        target_item['last_error'] = None
                    _save_vault(vault)
                    self._json(200, {'success': True, 'item': target_item, 'health': h, 'items': vault})
            except Exception as e:
                self._json(500, {'error': f'Lỗi kiểm tra cookie: {str(e)}'})

        elif self.path == '/api/templates/save':
            try:
                body = self._read_body()
                items = body.get('items', [])
                if not isinstance(items, list):
                    return self._json(400, {'error': 'Dữ liệu templates không hợp lệ'})
                _save_templates(items)
                self._json(200, {'success': True, 'items': items})
            except Exception as e:
                self._json(500, {'error': f'Lỗi lưu mẫu tin nhắn: {str(e)}'})

        elif self.path == '/api/telegram/save':
            try:
                body = self._read_body()
                cfg = _load_telegram_config()
                if 'bot_token' in body and body['bot_token'].strip():
                    cfg['bot_token'] = body['bot_token'].strip()
                if 'chat_id' in body:
                    cfg['chat_id'] = body['chat_id'].strip()
                if 'enabled' in body:
                    cfg['enabled'] = bool(body['enabled'])
                if 'notify_new_mvd' in body:
                    cfg['notify_new_mvd'] = bool(body['notify_new_mvd'])
                if 'notify_completed' in body:
                    cfg['notify_completed'] = bool(body['notify_completed'])
                if 'notify_cancelled' in body:
                    cfg['notify_cancelled'] = bool(body['notify_cancelled'])
                _save_telegram_config(cfg)
                self._json(200, {'success': True, 'message': 'Đã lưu cấu hình Telegram'})
            except Exception as e:
                self._json(500, {'error': f'Lỗi lưu Telegram config: {str(e)}'})

        elif self.path == '/api/telegram/test':
            try:
                body = self._read_body()
                msg = body.get('message', '').strip() or '🤖 <b>Shopee Tracker Test:</b> Kết nối Telegram Bot thành công!'
                ok, res_msg = send_telegram_alert(msg)
                if ok:
                    self._json(200, {'success': True, 'message': 'Đã gửi tin nhắn thử nghiệm tới Telegram!'})
                else:
                    self._json(400, {'error': f'Không thể gửi tin nhắn Telegram: {res_msg}'})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/order/tracking-timeline':
            try:
                body = self._read_body()
                order_id = str(body.get('order_id', '')).strip()
                cookie_raw = body.get('cookie_raw', '').strip()
                if not order_id:
                    return self._json(400, {'error': 'Thiếu mã order_id'})
                res = fetch_order_tracking_timeline(order_id, cookie_raw)
                self._json(200, {'success': True, 'data': res})
            except Exception as e:
                self._json(500, {'error': f'Lỗi lấy hành trình đơn hàng: {str(e)}'})

        elif self.path == '/api/autoreg/start':
            try:
                if not auto_reg_mgr:
                    return self._json(500, {'error': 'Autoreg manager chưa sẵn sàng'})
                body = self._read_body()
                server_id = body.get('server_id', 'dyn_ab1eb87836')
                count = int(body.get('count', 1))
                delay = int(body.get('delay', 10))
                kiotproxy_key = body.get('kiotproxy_key', '').strip()
                use_proxy = bool(body.get('use_proxy', False))
                # Tự động lưu key nếu có nhập
                if kiotproxy_key:
                    proxy_state['key'] = kiotproxy_key
                    _save_proxy_config()
                ok, msg = auto_reg_mgr.start(server_id, count, delay, kiotproxy_key, use_proxy)
                if ok:
                    self._json(200, {'success': True, 'message': msg})
                else:
                    self._json(400, {'error': msg})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/autoreg/test-kiotproxy':
            try:
                body = self._read_body()
                key = body.get('key', '').strip() or proxy_state.get('key', '').strip()
                if not key:
                    return self._json(400, {'success': False, 'error': 'Vui lòng nhập Key KiotProxy'})
                res_tuple = get_kiotproxy_ip(key, rotate=False)
                p_str = res_tuple[0]
                p_note = res_tuple[1]
                p_err = res_tuple[2]
                if p_str:
                    proxy_state['key'] = key
                    _save_proxy_config()
                    self._json(200, {'success': True, 'proxy': p_str, 'note': p_note})
                else:
                    self._json(200, {'success': False, 'error': p_err or 'Không thể kết nối proxy với Key này'})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/autoreg/stop':
            try:
                if not auto_reg_mgr:
                    return self._json(500, {'error': 'Autoreg manager chưa sẵn sàng'})
                ok, msg = auto_reg_mgr.stop()
                self._json(200, {'success': True, 'message': msg})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/autoreg/clear':
            try:
                if not auto_reg_mgr:
                    return self._json(500, {'error': 'Autoreg manager chưa sẵn sàng'})
                auto_reg_mgr.clear_accounts()
                self._json(200, {'success': True, 'message': 'Đã xóa lịch sử tài khoản'})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/autoreg/import-to-vault':
            try:
                body = self._read_body()
                cookie = body.get('cookie', '').strip()
                name = body.get('name', '').strip() or 'Acc Shopee Mới'
                if not cookie:
                    return self._json(400, {'error': 'Thiếu cookie'})
                
                vault = _load_vault()
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                item_id = str(int(time.time() * 1000))
                vault.insert(0, {
                    'id': item_id,
                    'name': name,
                    'cookie': cookie,
                    'tags': 'AutoReg, Shopee',
                    'notes': f'Tạo tự động lúc {now_str}',
                    'status': 'unknown',
                    'username': name,
                    'created_at': now_str,
                    'updated_at': now_str
                })
                _save_vault(vault)
                self._json(200, {'success': True, 'message': 'Đã đưa vào Kho Cookie thành công!'})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/telegram/send-code':
            try:
                if not tg_auth_mgr:
                    return self._json(500, {'success': False, 'error': 'Telegram auth manager chưa sẵn sàng'})
                body = self._read_body()
                phone = body.get('phone', '').strip()
                if not phone:
                    return self._json(400, {'success': False, 'error': 'Vui lòng nhập số điện thoại'})
                res = tg_auth_mgr.send_code(phone)
                self._json(200, res)
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/telegram/verify-code':
            try:
                if not tg_auth_mgr:
                    return self._json(500, {'success': False, 'error': 'Telegram auth manager chưa sẵn sàng'})
                body = self._read_body()
                code = body.get('code', '').strip()
                phone = body.get('phone', '').strip()
                phone_code_hash = body.get('phone_code_hash', '').strip()
                res = tg_auth_mgr.verify_code(code, phone=phone, phone_code_hash=phone_code_hash)
                self._json(200, res)
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/telegram/verify-2fa':
            try:
                if not tg_auth_mgr:
                    return self._json(500, {'success': False, 'error': 'Telegram auth manager chưa sẵn sàng'})
                body = self._read_body()
                password = body.get('password', '').strip()
                res = tg_auth_mgr.verify_2fa(password)
                self._json(200, res)
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/telegram/import-session':
            try:
                if not tg_auth_mgr:
                    return self._json(500, {'success': False, 'error': 'Telegram auth manager chưa sẵn sàng'})
                body = self._read_body()
                session_str = body.get('session', '').strip()
                res = tg_auth_mgr.import_string_session(session_str)
                self._json(200, res)
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/telegram/logout':
            try:
                if not tg_auth_mgr:
                    return self._json(500, {'success': False, 'error': 'Telegram auth manager chưa sẵn sàng'})
                res = tg_auth_mgr.logout()
                self._json(200, res)
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/telegram/load-default-slot':
            try:
                if not tg_auth_mgr:
                    return self._json(500, {'success': False, 'error': 'Telegram auth manager chưa sẵn sàng'})
                res = tg_auth_mgr.load_default_slot()
                self._json(200, res)
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/zalo/save-orders':
            try:
                body = self._read_body()
                orders = body.get('orders', [])
                zalo_file = os.path.join(DIRECTORY, "zalo_orders.json")
                with open(zalo_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        "orders": orders,
                        "updated_at": datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
                        "count": len(orders)
                    }, f, ensure_ascii=False, indent=2)
                self._json(200, {'success': True, 'count': len(orders), 'message': f'Đã lưu {len(orders)} đơn hàng từ Zalo'})
            except Exception as e:
                self._json(500, {'success': False, 'error': str(e)})

        elif self.path == '/api/bot-dks/start':
            try:
                if not dks_mgr:
                    return self._json(500, {'error': 'DangKyShopee manager chưa sẵn sàng'})
                body = self._read_body()
                config = body.get('config', {})
                nicks = body.get('nicks', [])
                ok, msg = dks_mgr.start(config, nicks)
                if ok:
                    self._json(200, {'success': True, 'message': msg})
                else:
                    self._json(400, {'error': msg})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/bot-dks/stop':
            try:
                if not dks_mgr:
                    return self._json(500, {'error': 'DangKyShopee manager chưa sẵn sàng'})
                ok, msg = dks_mgr.stop()
                self._json(200, {'success': True, 'message': msg})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/bot-dks/clear-logs':
            try:
                if not dks_mgr:
                    return self._json(500, {'error': 'DangKyShopee manager chưa sẵn sàng'})
                dks_mgr.clear_logs()
                self._json(200, {'success': True, 'message': 'Đã làm sạch nhật ký'})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/bot-dks/clear-queue':
            try:
                if not dks_mgr:
                    return self._json(500, {'error': 'DangKyShopee manager chưa sẵn sàng'})
                ok, msg = dks_mgr.clear_queue()
                if ok:
                    self._json(200, {'success': True, 'message': msg})
                else:
                    self._json(400, {'error': msg})
            except Exception as e:
                self._json(500, {'error': str(e)})

        elif self.path == '/api/bot-dks/parse-address':
            try:
                body = self._read_body()
                raw_addr = body.get('text', '').strip()
                parsed = parse_vietnamese_address(raw_addr) if parse_vietnamese_address else {}
                self._json(200, {'success': True, 'data': parsed})
            except Exception as e:
                self._json(500, {'error': str(e)})

        else:
            self._json(404, {'error': 'Endpoint không tồn tại'})

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode('utf-8')
        return json.loads(raw)

    def _json(self, status_code, data):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')


class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_server():
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    # In thông báo trạng thái khởi động
    print(f"[*] Shopee Tracking Sheet Server v4.2 - Supabase Edition")
    if _is_supabase_configured():
        print(f"[*] Supabase: ✅ Đã cấu hình — {SUPABASE_URL[:40]}...")
        print(f"[*] Dữ liệu sẽ được lưu/tải từ Supabase PostgreSQL (cloud)")
    else:
        print(f"[!] Supabase: ⚠️  Chưa cấu hình — đang dùng file cục bộ (draft.json)")
        print(f"[!] Để bật cloud storage: điền SUPABASE_URL và SUPABASE_KEY vào file .env")
    print(f"[*] Server running on http://localhost:{PORT}")
    print(f"-" * 60)
    
    server_address = ('', PORT)
    with ThreadedHTTPServer(server_address, TrackingRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")

if __name__ == '__main__':
    start_server()
