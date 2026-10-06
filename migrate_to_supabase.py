"""
Script chuyển dữ liệu từ draft.json và cookie_vault.json lên Supabase.
Chạy 1 lần sau khi đã điền SUPABASE_URL và SUPABASE_KEY vào file .env
"""
import json, os, datetime, sys, re
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(DIRECTORY, '.env')
DRAFT_FILE = os.path.join(DIRECTORY, 'draft.json')
VAULT_FILE = os.path.join(DIRECTORY, 'cookie_vault.json')

SUPABASE_URL = ""
SUPABASE_KEY = ""

if os.path.exists(ENV_FILE):
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            if key.strip() == 'SUPABASE_URL':
                SUPABASE_URL = val.strip()
            elif key.strip() == 'SUPABASE_KEY':
                SUPABASE_KEY = val.strip()

if not SUPABASE_URL or 'your-project' in SUPABASE_URL:
    print("❌ Chưa cấu hình SUPABASE_URL trong file .env!")
    print("   Hướng dẫn: Mở file .env và điền URL + KEY từ Supabase dashboard.")
    exit(1)

try:
    from supabase import create_client
except ImportError:
    print("❌ Chưa cài supabase-py. Chạy: pip install supabase")
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

# ── 1. MIGRATE ORDERS ──
if os.path.exists(DRAFT_FILE):
    with open(DRAFT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    rows = data.get('rows', [])
    if rows:
        print(f"🔍 Tìm thấy {len(rows)} đơn hàng trong draft.json")
        for r in rows:
            r['updated_at'] = now_iso
            r.pop('created_at', None)

        def _safe_upsert(batch):
            clean_batch = [dict(it) for it in batch]
            for _ in range(6):
                try:
                    sb.table('orders').upsert(clean_batch, on_conflict='id').execute()
                    return
                except Exception as ex:
                    m = re.search(r"Could not find the '([^']+)' column", str(ex))
                    if m:
                        c = m.group(1)
                        print(f"   [!] Bảng orders thiếu cột '{c}', tự động bỏ qua để tiếp tục lưu...")
                        for it in clean_batch:
                            it.pop(c, None)
                        continue
                    raise ex

        BATCH = 500
        for i in range(0, len(rows), BATCH):
            _safe_upsert(rows[i:i+BATCH])
        print(f"🎉 Hoàn tất migrate {len(rows)} đơn hàng lên Supabase 'orders'!")
    else:
        print("ℹ️  draft.json không có đơn hàng nào để migrate.")
else:
    print("⚠️  Không tìm thấy draft.json.")

# ── 2. MIGRATE COOKIE VAULT ──
if os.path.exists(VAULT_FILE):
    try:
        with open(VAULT_FILE, 'r', encoding='utf-8') as f:
            v_items = json.load(f)
        if isinstance(v_items, list) and v_items:
            print(f"🔍 Tìm thấy {len(v_items)} shop/cookie trong cookie_vault.json")
            try:
                sb.table('cookie_vault').upsert(v_items, on_conflict='id').execute()
                print(f"🎉 Hoàn tất migrate {len(v_items)} shop lên Supabase 'cookie_vault'!")
            except Exception as e:
                err_s = str(e)
                if 'PGRST205' in err_s or 'schema cache' in err_s:
                    print("⚠️  Bảng 'cookie_vault' chưa được tạo trên Supabase.")
                    print("   👉 Hãy mở file 'supabase_setup.sql' và dán vào Supabase SQL Editor để kích hoạt lưu Cloud!")
                else:
                    print(f"⚠️  Lỗi migrate cookie_vault: {e}")
    except Exception as e:
        print(f"⚠️  Lỗi đọc cookie_vault.json: {e}")

print("\n✅ Quá trình kiểm tra và migrate hoàn tất!")
