/**
 * Core Parser Engine - Bóc tách thông tin đơn hàng từ tin nhắn Zalo
 * Xử lý: Tên KH, SĐT lách, Link SP, Voucher, Địa chỉ cũ & Địa chỉ mới (sáp nhập)
 */

const VIETNAMESE_NUM_WORDS = {
  'không': '0', 'khong': '0', 'kh': '0', 'o': '0', 'O': '0', 'zero': '0',
  'một': '1', 'mot': '1', 'mốt': '1', 'one': '1',
  'hai': '2', 'two': '2',
  'ba': '3', 'three': '3',
  'bốn': '4', 'bon': '4', 'tư': '4', 'tu': '4', 'four': '4',
  'năm': '5', 'nam': '5', 'lăm': '5', 'lam': '5', 'five': '5',
  'sáu': '6', 'sau': '6', 'six': '6',
  'bảy': '7', 'bay': '7', 'bẩy': '7', 'seven': '7',
  'tám': '8', 'tam': '8', 'eight': '8',
  'chín': '9', 'chin': '9', 'nine': '9'
};

// Từ điển mẫu sáp nhập hành chính (Xã/Phường/Huyện tiêu biểu)
const ADMINISTRATIVE_MERGERS = [
  {
    province: "Hà Nội",
    old_names: ["Phường Hàng Bạc", "Phường Hàng Đào"],
    new_name: "Phường Hàng Gai (dự kiến nhập ĐVHC)",
    note: "Sáp nhập phường quận Hoàn Kiếm"
  },
  {
    province: "Nam Định",
    old_names: ["Xã Yên Bình", "Xã Yên Minh", "Xã Yên Dương"],
    new_name: "Xã Tân Minh (Huyện Ý Yên)",
    note: "Sáp nhập theo NQ sắp xếp ĐVHC huyện Ý Yên"
  },
  {
    province: "Hải Phòng",
    old_names: ["Huyện Thủy Nguyên"],
    new_name: "Thành phố Thủy Nguyên",
    note: "Nâng cấp lên thành phố trực thuộc Hải Phòng"
  },
  {
    province: "Bắc Giang",
    old_names: ["Huyện Yên Dũng"],
    new_name: "Thành phố Bắc Giang (sáp nhập)",
    note: "Sáp nhập toàn bộ huyện Yên Dũng vào TP Bắc Giang"
  },
  {
    province: "TP. Hồ Chí Minh",
    old_names: ["Quận 2", "Quận 9", "Quận Thủ Đức"],
    new_name: "Thành phố Thủ Đức",
    note: "Đã thành lập TP Thủ Đức"
  }
];

class ZaloOrderParser {
  /**
   * Giải mã và chuẩn hóa số điện thoại thật của Việt Nam (kể cả khách gõ chữ, lách dấu)
   */
  static cleanPhoneNumber(text) {
    if (!text) return null;

    let raw = text.toLowerCase();

    // 1. Thay thế chữ 'o' hoặc 'O' đứng ngay trước chữ số: 'o98' -> '098'
    raw = raw.replace(/\bo(?=\d)/gi, '0');
    raw = raw.replace(/(?<=\s)o(?=\d)/gi, '0');
    raw = raw.replace(/^o(?=\d)/gi, '0');

    // 2. Chuyển các từ chữ số tiếng Việt sang số
    for (const [word, digit] of Object.entries(VIETNAMESE_NUM_WORDS)) {
      if (word === 'o' || word === 'O') continue;
      const reg = new RegExp(`(^|[^a-z0-9à-ỹ])${word}([^a-z0-9à-ỹ]|$)`, 'gi');
      raw = raw.replace(reg, `$1${digit}$2`);
    }

    // 3. Chuẩn hóa các dấu cách/chấm/gạch nối: gom chuỗi số tiềm năng
    const phoneSegments = raw.match(/(?:(?:\+84|84|0)[\s.\-_/0-9]{8,25})/g) || [];
    
    for (const seg of phoneSegments) {
      let clean = seg.replace(/[^0-9]/g, '');
      if (clean.startsWith('84') && clean.length === 11) {
        clean = '0' + clean.slice(2);
      }
      if (/^(03|05|07|08|09)\d{8}$/.test(clean)) {
        return clean;
      }
    }

    // Quét dự phòng: lấy tất cả các chữ số liên tiếp sau khi đã dịch chữ sang số
    const digitsOnly = raw.replace(/[^0-9]/g, '');
    const fallbackMatch = digitsOnly.match(/(0[35789]\d{8})/);
    if (fallbackMatch) {
      return fallbackMatch[1];
    }

    return null;
  }

  /**
   * Bóc tách tất cả link sản phẩm (Shopee, TikTok, Lazada...)
   */
  static extractProductUrls(text) {
    if (!text) return [];
    const urlRegex = /(https?:\/\/[^\s<>"'\)]+|www\.[^\s<>"'\)]+)/gi;
    const matches = text.match(urlRegex) || [];
    const productUrls = [];

    for (let url of matches) {
      if (url.startsWith('www.')) url = 'https://' + url;
      // Lọc các link sàn TMĐT hoặc link rút gọn
      if (/shopee\.vn|shp\.ee|tiktok\.com|lazada\.vn|tiki\.vn|s\.shopee\.vn/i.test(url)) {
        productUrls.push(url);
      } else {
        // Link web thông thường
        productUrls.push(url);
      }
    }
    return [...new Set(productUrls)];
  }

  /**
   * Bóc tách mã giảm giá (Voucher)
   */
  static extractVoucher(text) {
    if (!text) return null;

    // Pattern nhận diện: "mã: ...", "voucher: ...", "áp mã ...", "code: ..."
    const voucherPatterns = [
      /(?:mã(?:\s*giảm(?:\s*giá)?)?|voucher|code|áp\s*mã|mã\s*đặt)\s*[:=–-]?\s*([a-zA-Z0-9_\-]{4,25})/i,
      /\b([A-Z0-9]{2,15}(?:50K|100K|30K|20K|15K|FREESHIP|EXTRA|LIVE|SALE|SHOP)[A-Z0-9]*)\b/i,
      /\b(GIAM\d+K?|MGG\d+|VOUCHER\d+)\b/i
    ];

    for (const pattern of voucherPatterns) {
      const match = text.match(pattern);
      if (match && match[1]) {
        // Loại trừ nếu trùng với domain web hoặc số điện thoại
        const val = match[1].trim();
        if (!/^(https?|com|vn|net|0\d{9})$/i.test(val)) {
          return val.toUpperCase();
        }
      }
    }
    return null;
  }

  /**
   * Trích xuất Tên khách hàng từ tin nhắn
   */
  static extractCustomerName(text, fallbackName = "") {
    if (!text) return fallbackName || "Khách hàng";

    // Tìm các từ khóa: Tên: ..., Người nhận: ..., Khách: ...
    const namePatterns = [
      /(?:tên(?:\s*người\s*nhận|\s*khách)?|người\s*nhận|họ\s*tên)\s*[:=–-]?\s*([A-ZÀ-Ỹa-zà-ỹ\s]{2,30})/i,
      /(?:gửi(?:\s*cho)?|ship(?:\s*cho)?)\s*[:=–-]?\s*([A-ZÀ-Ỹa-zà-ỹ\s]{2,30})(?:,|\n|\s*-|\s*sđt|\s*địa)/i
    ];

    for (const p of namePatterns) {
      const match = text.match(p);
      if (match && match[1]) {
        let name = match[1].trim();
        // Loại bỏ từ rác cuối dòng
        name = name.split(/\n|,|-|sđt|đt|sdt/i)[0].trim();
        if (name.length >= 2 && name.length <= 35 && !/\d/.test(name)) {
          return name;
        }
      }
    }

    return fallbackName || "Khách hàng";
  }

  /**
   * Bóc tách địa chỉ (Cũ & Mới sau sáp nhập) bằng Rule nội bộ
   */
  static extractAddressRuleBased(text) {
    if (!text) return { address_raw: "", address_old: "", address_new: "", note: "" };

    // Tìm dòng hoặc cụm từ chứa địa chỉ
    const addrKeywords = /(?:địa\s*chỉ|đc|dc|đ\/c|gửi\s*về|nhận\s*tại)\s*[:=–-]?\s*([^\n\r]+)/i;
    const match = text.match(addrKeywords);
    
    let rawAddress = "";
    if (match && match[1]) {
      rawAddress = match[1].trim();
    } else {
      // Tìm dòng có các từ hành chính hoặc địa danh: làng, cổng làng, thôn, xóm, ấp, phố, đường, ngõ, ngách, số nhà, xã, phường, thị trấn, quận, huyện, tỉnh...
      const lines = text.split('\n');
      for (let line of lines) {
        line = line.replace(/^[0-9\u20e3\ufe0f\s\-:–\.\(\)\[\]\*]+/, '').trim(); // Loại bỏ tiền tố 1️⃣, 2️⃣, 1., -
        if (/(cổng\s*làng|làng|thôn|xóm|ấp|phố|đường|ngõ|ngách|hẻm|số\s*nhà|khu|tổ|xã|phường|thị\s*trấn|quận|huyện|tỉnh|tp\.|tp\s|hà\s*nội|hồ\s*chí\s*minh)/i.test(line)) {
          rawAddress = line.trim();
          break;
        }
      }
    }

    let addressOld = rawAddress;
    let addressNew = rawAddress;
    let note = "";

    // Đối chiếu với từ điển sáp nhập
    for (const item of ADMINISTRATIVE_MERGERS) {
      for (const oldName of item.old_names) {
        if (rawAddress.toLowerCase().includes(oldName.toLowerCase())) {
          addressOld = rawAddress;
          addressNew = rawAddress.replace(new RegExp(oldName, 'gi'), item.new_name);
          note = `${item.note}: ${oldName} -> ${item.new_name}`;
          break;
        }
      }
    }

    return {
      address_raw: rawAddress,
      address_old: addressOld || rawAddress,
      address_new: addressNew || rawAddress,
      note: note
    };
  }

  /**
   * Tích hợp AI (Google Gemini API) để bóc tách thông minh 100%
   * Tự động tra cứu địa chỉ hành chính cũ vs mới sau sáp nhập cấp xã/huyện
   */
  static async extractWithGemini(apiKey, text, senderName = "") {
    if (!apiKey) {
      return null;
    }

    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${apiKey}`;

    const prompt = `
Bạn là chuyên viên bóc tách đơn hàng chat Zalo tại Việt Nam.
Hãy phân tích tin nhắn sau từ khách hàng (Tên Zalo: "${senderName}"):
"""
${text}
"""

Nhiệm vụ:
1. Trích xuất tên người nhận hàng (customer_name).
2. Giải mã số điện thoại thật của Việt Nam (phone_clean) dạng 10 chữ số (chuẩn hóa các biến thể lách chữ như "không", "o9...", "chấm", "khoảng cách").
3. Link sản phẩm (product_url): Link Shopee, TikTok, Lazada...
4. Mã giảm giá / Voucher khách muốn đặt (voucher_code).
5. Phân tích địa chỉ nhận hàng:
   - address_old: Địa chỉ theo tên cũ trước khi sáp nhập xã/phường/huyện (nếu có thông tin).
   - address_new: Địa chỉ hành chính mới chuẩn hóa sau sáp nhập theo các nghị quyết sắp xếp đơn vị hành chính 2023-2025 của UBTVQH Việt Nam.
   - address_merged_note: Ghi chú ngắn gọn về việc sáp nhập (ví dụ: Xã A đã sáp nhập vào Xã B).

Chỉ trả về ĐÚNG 1 JSON Object (không kèm markdown \`\`\`json):
{
  "customer_name": "...",
  "phone_clean": "...",
  "product_url": "...",
  "voucher_code": "...",
  "address_old": "...",
  "address_new": "...",
  "address_merged_note": "..."
}
`;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: { responseMimeType: "application/json" }
        })
      });

      if (!response.ok) {
        console.warn("[Gemini API Error]", await response.text());
        return null;
      }

      const data = await response.json();
      const outputText = data.candidates?.[0]?.content?.parts?.[0]?.text;
      if (outputText) {
        return JSON.parse(outputText);
      }
    } catch (err) {
      console.error("[Gemini Extraction Failed]", err);
    }
    return null;
  }

  /**
   * Hàm tổng hợp - Chạy bóc tách đầy đủ (Hybrid: AI + Rule Fallback)
   */
  static async parseOrderMessage(text, senderName = "", apiKey = "") {
    // 1. Nếu có Gemini API Key -> Thử chạy AI trước
    if (apiKey) {
      const aiResult = await this.extractWithGemini(apiKey, text, senderName);
      if (aiResult) {
        return {
          customer_name: aiResult.customer_name || senderName || "Khách hàng",
          phone: aiResult.phone_clean || this.cleanPhoneNumber(text),
          product_urls: aiResult.product_url ? [aiResult.product_url] : this.extractProductUrls(text),
          voucher: aiResult.voucher_code || this.extractVoucher(text),
          address_old: aiResult.address_old || "",
          address_new: aiResult.address_new || "",
          address_note: aiResult.address_merged_note || "",
          raw_text: text,
          engine: "Gemini AI"
        };
      }
    }

    // 2. Chạy Rule-based Engine (Offline, tức thì)
    const phone = this.cleanPhoneNumber(text);
    const urls = this.extractProductUrls(text);
    const voucher = this.extractVoucher(text);
    const name = this.extractCustomerName(text, senderName);
    const addr = this.extractAddressRuleBased(text);

    return {
      customer_name: name,
      phone: phone,
      product_urls: urls,
      voucher: voucher,
      address_old: addr.address_old,
      address_new: addr.address_new,
      address_note: addr.note,
      raw_text: text,
      engine: "Regex & Rules"
    };
  }

  /**
   * Chuẩn hóa SĐT về chuỗi chỉ gồm số và lấy 9 chữ số đuôi để so sánh
   */
  static cleanPhoneDigits(phone) {
    if (!phone) return "";
    let digits = String(phone).replace(/\D/g, '');
    if (digits.startsWith('84') && digits.length >= 10) {
      digits = '0' + digits.slice(2);
    }
    return digits;
  }

  /**
   * So khớp 2 số điện thoại (chính xác theo 9 số cuối)
   */
  static isSamePhone(p1, p2) {
    const d1 = this.cleanPhoneDigits(p1).slice(-9);
    const d2 = this.cleanPhoneDigits(p2).slice(-9);
    return d1 && d2 && d1 === d2;
  }

  /**
   * Tìm TẤT CẢ các đơn hàng trong Sheet khớp với Số Điện Thoại
   * (Kiểm tra cả receiver_phone, note_name và order_tag)
   */
  static findAllOrdersByPhone(phone, sheetRows = []) {
    if (!phone || !Array.isArray(sheetRows) || sheetRows.length === 0) return [];
    const targetDigits = this.cleanPhoneDigits(phone);
    const targetLast9 = targetDigits.slice(-9);
    if (!targetLast9) return [];

    const results = [];
    for (const row of sheetRows) {
      const rowPhone = row.receiver_phone || row.phone || row.sdt || row.customer_phone || "";
      const noteStr = String(row.note_name || "");
      const tagStr = String(row.order_tag || "");

      let isMatch = false;
      if (this.isSamePhone(targetLast9, rowPhone)) {
        isMatch = true;
      } else if (noteStr.includes(targetLast9) || tagStr.includes(targetLast9) || (targetDigits.length >= 8 && (noteStr.includes(targetDigits) || tagStr.includes(targetDigits)))) {
        isMatch = true;
      }

      if (isMatch) {
        results.push(row);
      }
    }
    return results;
  }

  /**
   * Tìm đơn hàng đầu tiên trong Sheet theo Số Điện Thoại
   */
  static findOrderByPhone(phone, sheetRows = []) {
    const all = this.findAllOrdersByPhone(phone, sheetRows);
    return all.length > 0 ? all[0] : null;
  }

  /**
   * Tạo tin nhắn mẫu chuyên nghiệp báo mã vận đơn cho 1 đơn hàng
   */
  static buildTrackingReplyMessage(order) {
    if (!order) return "";
    const mvd = order.tracking_no || order.mvd || "Đang cập nhật";
    const carrier = order.carrier || order.don_vi_vc || "Đơn vị vận chuyển";
    const status = order.status_desc || order.status_badge_text || order.trang_thai || "Đang vận chuyển";
    const name = order.receiver_name || order.customer_name || "bạn";
    const cod = order.cod_amount || (order.cod_val ? `${Number(order.cod_val).toLocaleString('vi-VN')} đ` : "");
    const product = order.product_name || "";
    const shipperPhone = order.driver_phone || "";

    let lines = [];
    lines.push(`Dạ chào ${name}, shop gửi bạn thông tin đơn hàng nhé:`);
    lines.push(`📦 Mã vận đơn: ${mvd} (${carrier})`);
    lines.push(`🚚 Trạng thái: ${status}`);
    if (product) {
      const shortProd = product.length > 50 ? product.substring(0, 47) + "..." : product;
      lines.push(`🛍️ Sản phẩm: ${shortProd}`);
    }
    if (cod && cod !== "0 đ" && cod !== "0") {
      lines.push(`💰 Tiền COD cần thanh toán: ${cod}`);
    }
    if (shipperPhone) {
      lines.push(`📞 Số điện thoại Shipper: ${shipperPhone}`);
    }
    lines.push(`👉 Bạn vui lòng để ý điện thoại để shipper liên hệ giao hàng nhé! Cảm ơn bạn ❤️`);

    return lines.join("\n");
  }

  /**
   * Tạo tin nhắn trả lời tự động cho khách khi có 1 hoặc nhiều đơn theo SĐT
   */
  static buildMultiOrderTrackingMessage(phone, ordersList = []) {
    if (!ordersList || ordersList.length === 0) {
      return `Dạ chào bạn, shop đã kiểm tra hệ thống theo SĐT ${phone} nhưng hiện tại chưa thấy đơn hàng nào có mã vận đơn. Bạn vui lòng kiểm tra lại SĐT hoặc gửi tin nhắn để shop hỗ trợ nhé!`;
    }

    if (ordersList.length === 1) {
      return this.buildTrackingReplyMessage(ordersList[0]);
    }

    let lines = [];
    lines.push(`Dạ chào bạn, shop đã tra cứu thấy [${ordersList.length}] đơn hàng gắn SĐT ${phone} của bạn nhé:`);
    lines.push("");

    ordersList.forEach((o, idx) => {
      const mvd = o.tracking_no || "Đang cập nhật";
      const carrier = o.carrier || "ĐVVC";
      const status = o.status_desc || "Đang vận chuyển";
      const cod = o.cod_amount || (o.cod_val ? `${Number(o.cod_val).toLocaleString('vi-VN')} đ` : "");
      const prod = o.product_name ? (o.product_name.length > 40 ? o.product_name.substring(0, 37) + '...' : o.product_name) : "";

      lines.push(`📦 ĐƠN ${idx + 1}:`);
      lines.push(`• Mã vận đơn: ${mvd} (${carrier})`);
      lines.push(`• Trạng thái: ${status}`);
      if (prod) lines.push(`• Sản phẩm: ${prod}`);
      if (cod && cod !== "0 đ" && cod !== "0") lines.push(`• Tiền COD: ${cod}`);
      lines.push("");
    });

    lines.push(`👉 Bạn vui lòng để ý điện thoại để shipper liên hệ giao hàng nhé! Cảm ơn bạn ❤️`);
    return lines.join("\n");
  }
}

// Export cho browser content script / popup
if (typeof window !== 'undefined') {
  window.ZaloOrderParser = ZaloOrderParser;
}

