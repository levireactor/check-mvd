"""
Script kiểm thử bộ Parser bóc tách tin nhắn Zalo độc lập (Python).
Dùng để test logic lọc số điện thoại lách chữ, link sản phẩm, mã voucher và địa chỉ sáp nhập.
"""

import re
import json
import sys

# Đảm bảo in tiếng Việt mượt mà trên console Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

VIETNAMESE_NUM_WORDS = {
    'không': '0', 'khong': '0', 'kh': '0', 'o': '0', 'zero': '0',
    'một': '1', 'mot': '1', 'mốt': '1', 'one': '1',
    'hai': '2', 'two': '2',
    'ba': '3', 'three': '3',
    'bốn': '4', 'bon': '4', 'tư': '4', 'tu': '4', 'four': '4',
    'năm': '5', 'nam': '5', 'lăm': '5', 'lam': '5', 'five': '5',
    'sáu': '6', 'sau': '6', 'six': '6',
    'bảy': '7', 'bay': '7', 'bẩy': '7', 'seven': '7',
    'tám': '8', 'tam': '8', 'eight': '8',
    'chín': '9', 'chin': '9', 'nine': '9'
}

# Bảng mẫu sáp nhập hành chính
ADMINISTRATIVE_MERGERS = [
    {
        "province": "Nam Định",
        "old_names": ["Xã Yên Bình", "Xã Yên Minh", "Xã Yên Dương"],
        "new_name": "Xã Tân Minh (Huyện Ý Yên)",
        "note": "Sáp nhập 3 xã thành xã Tân Minh theo NQ UBTVQH"
    },
    {
        "province": "Bắc Giang",
        "old_names": ["Huyện Yên Dũng"],
        "new_name": "Thành phố Bắc Giang",
        "note": "Sáp nhập toàn bộ huyện Yên Dũng vào TP Bắc Giang"
    },
    {
        "province": "TP. Hồ Chí Minh",
        "old_names": ["Quận 2", "Quận 9", "Quận Thủ Đức"],
        "new_name": "Thành phố Thủ Đức",
        "note": "Sáp nhập 3 quận thành lập TP Thủ Đức"
    }
]

def clean_phone_number(text: str) -> str:
    """Giải mã SĐT kể cả viết chữ, ký tự đặc biệt, lách luật"""
    if not text:
        return ""
    raw = text.lower()

    # 1. Thay thế chữ 'o' hoặc 'O' đứng ngay trước chữ số: 'o98' -> '098'
    raw = re.sub(r'\bo(?=\d)', '0', raw)
    raw = re.sub(r'(?<=\s)o(?=\d)', '0', raw)
    raw = re.sub(r'^o(?=\d)', '0', raw)

    # 2. Thay thế các từ chữ số tiếng Việt
    for word, digit in VIETNAMESE_NUM_WORDS.items():
        if word in ['o', 'O']:
            continue
        raw = re.sub(rf'\b{word}\b', digit, raw)

    # 3. Tìm đoạn số có khả năng là SĐT
    # Gom các cụm có thể là số điện thoại
    candidates = re.findall(r'(?:(?:\+84|84|0)[\s.\-_/0-9]{8,25})', raw)
    for seg in candidates:
        clean = re.sub(r'[^0-9]', '', seg)
        if clean.startswith('84') and len(clean) == 11:
            clean = '0' + clean[2:]
        if re.match(r'^(03|05|07|08|09)\d{8}$', clean):
            return clean

    # Quét dự phòng: lấy tất cả các chữ số liên tiếp sau khi đã dịch chữ sang số
    digits_only = re.sub(r'[^0-9]', '', raw)
    m = re.search(r'(0[35789]\d{8})', digits_only)
    if m:
        return m.group(1)
    return ""

def extract_product_urls(text: str) -> list:
    """Lấy link sản phẩm"""
    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
    matches = re.findall(url_pattern, text)
    cleaned = []
    for u in matches:
        if u.startswith('www.'):
            u = 'https://' + u
        cleaned.append(u)
    return list(dict.fromkeys(cleaned))

def extract_voucher(text: str) -> str:
    """Lấy mã giảm giá"""
    patterns = [
        r'(?:mã(?:\s*giảm(?:\s*giá)?)?|voucher|code|áp\s*mã|mã\s*đặt)\s*[:=–-]?\s*([a-zA-Z0-9_\-]{4,25})',
        r'\b([A-Z0-9]{2,15}(?:50K|100K|30K|20K|15K|FREESHIP|EXTRA|LIVE|SALE|SHOP)[A-Z0-9]*)\b'
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m and m.group(1):
            val = m.group(1).strip()
            if not re.match(r'^(https?|com|vn|net|0\d{9})$', val, re.IGNORECASE):
                return val.upper()
    return ""

def extract_customer_name(text: str, fallback: str = "Khách hàng") -> str:
    """Lấy tên khách hàng"""
    patterns = [
        r'(?:tên(?:\s*người\s*nhận|\s*khách)?|người\s*nhận|họ\s*tên)\s*[:=–-]?\s*([A-ZÀ-Ỹa-zà-ỹ\s]{2,30})',
        r'(?:gửi(?:\s*cho)?|ship(?:\s*cho)?)\s*[:=–-]?\s*([A-ZÀ-Ỹa-zà-ỹ\s]{2,30})(?:,|\n|\s*-|\s*sđt|\s*địa)'
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m and m.group(1):
            name = m.group(1).strip()
            name = re.split(r'\n|,|-|sđt|đt|sdt', name, flags=re.IGNORECASE)[0].strip()
            if 2 <= len(name) <= 35 and not re.search(r'\d', name):
                return name
    return fallback

def extract_address(text: str) -> dict:
    """Bóc tách và đối chiếu địa chỉ sáp nhập"""
    match = re.search(r'(?:địa\s*chỉ|đc|dc|đ\/c|gửi\s*về|nhận\s*tại)\s*[:=–-]?\s*([^\n\r]+)', text, re.IGNORECASE)
    raw = match.group(1).strip() if match else ""
    if not raw:
        for line in text.splitlines():
            if re.search(r'(thôn|xóm|ấp|phố|đường|xã|phường|thị\s*trấn|quận|huyện|tỉnh|tp\.)', line, re.IGNORECASE):
                raw = line.strip()
                break

    old_addr = raw
    new_addr = raw
    note = ""

    for item in ADMINISTRATIVE_MERGERS:
        for old_name in item["old_names"]:
            if old_name.lower() in raw.lower():
                old_addr = raw
                new_addr = re.sub(re.escape(old_name), item["new_name"], raw, flags=re.IGNORECASE)
                note = f"{item['note']}: {old_name} -> {item['new_name']}"
                break

    return {
        "address_old": old_addr,
        "address_new": new_addr,
        "note": note
    }

def test_parse():
    sample_message = """
    Chào shop, đặt hộ mình đơn này nhé:
    Tên người nhận: Nguyễn Thùy Trang
    Sđt: o98 765 43 hai một
    Link mua: https://s.shopee.vn/8A1B2C3D
    Nhớ áp mã giúp mình: GIAM50KT4
    Địa chỉ: Thôn Đông, Xã Yên Bình, Huyện Ý Yên, Tỉnh Nam Định
    """
    
    print("--- TIN NHẮN ĐẦU VÀO ---")
    print(sample_message.strip())
    print("\n--- KẾT QUẢ BÓC TÁCH ---")
    
    name = extract_customer_name(sample_message, "Trang Zalo")
    phone = clean_phone_number(sample_message)
    urls = extract_product_urls(sample_message)
    voucher = extract_voucher(sample_message)
    addr = extract_address(sample_message)
    
    result = {
        "Tên khách hàng": name,
        "SĐT thật (Clean)": phone,
        "Link sản phẩm": urls,
        "Mã giảm giá": voucher,
        "Địa chỉ mới (Sau sáp nhập)": addr["address_new"],
        "Địa chỉ cũ (Trước sáp nhập)": addr["address_old"],
        "Ghi chú sáp nhập": addr["note"]
    }
    
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    test_parse()
