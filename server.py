"""
Shopee Tracking Sheet Backend
Direct Shopee Mobile Gateway (x-api-source: rn)
Supports Sheet View: Order SN, Tracking MVĐ, Receiver, Address, COD, Status Badges, Draft Save/Load
Additional Columns: Product Link, Shipper Phone, Order Time, Last Check, Full Detail
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

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DRAFT_FILE = os.path.join(DIRECTORY, "draft.json")

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
    if 'SPC_ST=' in raw:
        parts = raw.split(';')
        for p in parts:
            p = p.strip()
            if p.startswith('SPC_ST='):
                return p[7:].strip()
    return raw

def fetch_shopee_json(url, headers, timeout=10):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=timeout) as res:
        return json.loads(res.read().decode('utf-8'))

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
            tracking_no = shipping.get('tracking_number') or ''
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

            # 5. Sản phẩm & Link Sản Phẩm
            products = []
            product_url = ""
            info_card = d.get('info_card', {}) or {}
            for pc in info_card.get('parcel_cards', []):
                for grp in pc.get('product_info', {}).get('item_groups', []):
                    for it in grp.get('items', []):
                        name = it.get('name')
                        if name:
                            products.append(name)
                        if not product_url and it.get('item_id') and it.get('shop_id'):
                            product_url = f"https://shopee.vn/product/{it.get('shop_id')}/{it.get('item_id')}"
            
            product_display = products[0] if products else '--'

            # 6. COD & Thanh toán
            payment_info = info_card.get('parcel_cards', [{}])[0].get('payment_info', {})
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
            ctime = tracking_info.get('ctime') or d.get('ctime') or int(time.time())
            dt = datetime.datetime.fromtimestamp(ctime)
            order_date = dt.strftime('%Y-%m-%d')
            order_day = dt.strftime('%d')
            order_time = dt.strftime('%H:%M %d/%m/%Y')

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
                'driver_phone': driver_phone,
                'all_products': products,
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
                'driver_phone': '',
                'all_products': [],
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
            self._json(200, {'status': 'ok', 'engine': 'shopee-sheet-v4.1'})
        elif self.path == '/api/load-draft':
            try:
                if os.path.exists(DRAFT_FILE):
                    with open(DRAFT_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self._json(200, data)
                else:
                    self._json(200, {'rows': [], 'count': 0, 'updated_at': None})
            except Exception as e:
                self._json(500, {'error': f'Không thể đọc draft: {str(e)}'})
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
                data = {
                    'rows': rows,
                    'count': len(rows),
                    'updated_at': now_str
                }
                with open(DRAFT_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                self._json(200, {'success': True, 'count': len(rows), 'saved_at': now_str})
            except Exception as e:
                self._json(500, {'error': f'Không thể lưu draft: {str(e)}'})

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
    
    server_address = ('', PORT)
    with ThreadedHTTPServer(server_address, TrackingRequestHandler) as httpd:
        print(f"[*] Shopee Tracking Sheet Server running on http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")

if __name__ == '__main__':
    start_server()
