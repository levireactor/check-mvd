"""
Script chuyển dữ liệu từ draft.json lên Supabase.
Chạy 1 lần sau khi đã điền SUPABASE_URL và SUPABASE_KEY vào file .env
"""
import json, os, datetime, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
DRAFT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'draft.json')

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

if not os.path.exists(DRAFT_FILE):
    print("⚠️  Không tìm thấy draft.json. Không có dữ liệu để migrate.")
    exit(0)

with open(DRAFT_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

rows = data.get('rows', [])
if not rows:
    print("⚠️  draft.json rỗng. Không có dữ liệu để migrate.")
    exit(0)

print(f"🔍 Tìm thấy {len(rows)} đơn hàng trong draft.json")
print(f"🌐 Đang kết nối Supabase: {SUPABASE_URL[:40]}...")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
now_iso = datetime.datetime.utcnow().isoformat()

# Thêm timestamp vào mỗi row
for r in rows:
    r['updated_at'] = now_iso

BATCH = 500
total = 0
for i in range(0, len(rows), BATCH):
    batch = rows[i:i+BATCH]
    sb.table('orders').upsert(batch, on_conflict='id').execute()
    total += len(batch)
    print(f"   ✅ Đã migrate {total}/{len(rows)} đơn hàng...")

print(f"\n🎉 Hoàn tất! Đã migrate {len(rows)} đơn hàng lên Supabase.")
print("   Bạn có thể kiểm tra trong Supabase Dashboard → Table Editor → orders")
