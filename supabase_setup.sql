-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- SHOPEE TRACKER PRO - SUPABASE DATABASE SETUP & MIGRATION
-- Chạy đoạn mã này trong Supabase Dashboard -> SQL Editor -> Run
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 1. BẢNG QUẢN LÝ ĐƠN HÀNG (orders)
CREATE TABLE IF NOT EXISTS public.orders (
    id TEXT PRIMARY KEY,
    order_id TEXT,
    order_sn TEXT,
    tracking_no TEXT,
    has_tracking BOOLEAN DEFAULT FALSE,
    carrier TEXT,
    status_desc TEXT,
    status_badge_type TEXT,
    status_badge_text TEXT,
    receiver_name TEXT,
    receiver_phone TEXT,
    receiver_address TEXT,
    product_name TEXT,
    product_url TEXT,
    product_image TEXT,
    driver_phone TEXT,
    all_products JSONB,
    timeline JSONB,
    cod_val NUMERIC DEFAULT 0,
    cod_amount TEXT,
    payment_status TEXT,
    order_date TEXT,
    order_day TEXT,
    order_time TEXT,
    last_check TEXT,
    timestamp BIGINT,
    order_tag TEXT,
    cookie_preview TEXT,
    cookie_raw TEXT,
    note_name TEXT,
    stt INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Bổ sung các cột nếu bảng orders đã được tạo từ trước nhưng thiếu
ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS product_image TEXT;
ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS timeline JSONB;
ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS all_products JSONB;

-- 2. BẢNG KHO COOKIE & QUẢN LÝ SHOP (cookie_vault)
CREATE TABLE IF NOT EXISTS public.cookie_vault (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cookie TEXT NOT NULL,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    status TEXT DEFAULT 'unknown',
    username TEXT DEFAULT '',
    last_error TEXT,
    last_checked TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- 3. TẮT RLS ĐỂ TOOL ĐỌC GHI QUA API
ALTER TABLE public.orders DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.cookie_vault DISABLE ROW LEVEL SECURITY;
