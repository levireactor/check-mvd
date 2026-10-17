# -*- coding: utf-8 -*-
"""
MODULE TỰ ĐỘNG HÓA CHUYỂN ĐỔI LINK SHOPEE AFFILIATE BẰNG SELENIUM (CHROME THẬT)
- Không cần Open API, không cần Secret Key, không sợ WAF/Captcha Shopee chặn!
- Cơ chế: Kết nối vào Chrome thật qua cổng Remote Debugging (port 9222) với profile độc lập lưu vĩnh viễn.
"""

import os
import sys
import time
import socket
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(DIRECTORY, "chrome_aff_profile")
PORT = 9222
DEFAULT_PORTAL_URL = "https://affiliate.shopee.vn/offer/custom_link?mmp_pid=an_17320160631&affiliate_id=17324610663&pid=affiliates&utm_source=an_17320160631&utm_medium=affiliates&utm_content=meoidungkhoa&af_siteid=an_17320160631"

def get_chrome_path():
    """Tự động tìm kiếm đường dẫn Chrome hoặc Edge Chromium trên máy Windows"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]

def get_chromedriver_service():
    """Lấy đường dẫn chromedriver tối ưu để kết nối ngay lập tức không bị delay"""
    # 1. Tìm trong cache của Selenium
    cache_base = os.path.expandvars(r"%USERPROFILE%\.cache\selenium\chromedriver\win64")
    if os.path.exists(cache_base):
        for root, dirs, files in os.walk(cache_base):
            if "chromedriver.exe" in files:
                return Service(os.path.join(root, "chromedriver.exe"))
    # 2. Tìm trong thư mục dự án
    local_driver = os.path.join(DIRECTORY, "chromedriver.exe")
    if os.path.exists(local_driver):
        return Service(local_driver)
    # 3. Dùng Service mặc định
    return Service()

def is_chrome_running():
    """Kiểm tra cổng 9222 đã có Chrome lắng nghe chưa"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.6)
        s.connect(('127.0.0.1', PORT))
        s.close()
        return True
    except Exception:
        return False

def launch_chrome_affiliate():
    """Khởi động trình duyệt Chrome độc lập cho Shopee Affiliate (Độc lập, bền vững)"""
    if is_chrome_running():
        return True, "Chrome Shopee Affiliate đã đang chạy sẵn sàng"

    os.makedirs(PROFILE_DIR, exist_ok=True)
    chrome_bin = get_chrome_path()

    # Sử dụng cmd start để tiến trình Chrome hoàn toàn độc lập với Python
    start_cmd = (
        f'start "" "{chrome_bin}" '
        f'--remote-debugging-port={PORT} '
        f'--remote-allow-origins=* '
        f'--user-data-dir="{PROFILE_DIR}" '
        f'--no-first-run --no-default-browser-check '
        f'"{DEFAULT_PORTAL_URL}"'
    )

    try:
        subprocess.Popen(
            start_cmd,
            shell=True,
            creationflags=0x00000008 | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        # Chờ Chrome sẵn sàng tối đa 10s
        for _ in range(20):
            time.sleep(0.5)
            if is_chrome_running():
                return True, "Đã khởi động trình duyệt Chrome Shopee Affiliate thành công"
        return False, "Không kết nối được cổng Chrome 9222 sau khi khởi động"
    except Exception as e:
        return False, f"Lỗi khởi động Chrome: {str(e)}"

def convert_link_via_selenium(product_link, timeout=15):
    """
    Điều khiển Chrome tự động dán link vào https://affiliate.shopee.vn/offer/custom_link
    và lấy link rút gọn s.shopee.vn trả về.
    """
    product_link = product_link.strip()
    if not product_link:
        return False, "Link sản phẩm trống"

    # Nếu Chrome chưa chạy, tự khởi động
    if not is_chrome_running():
        ok, msg = launch_chrome_affiliate()
        if not ok:
            return False, f"Chưa thể kết nối Chrome: {msg}. Hãy bấm đúp chạy file MO_CHROME_AFFILIATE.bat trên máy."
        time.sleep(2)

    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{PORT}")
    options.add_argument("--remote-allow-origins=*")

    service = get_chromedriver_service()
    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=options)

        # Kiểm tra xem đã có tab affiliate.shopee.vn chưa
        target_tab = None
        for handle in driver.window_handles:
            try:
                driver.switch_to.window(handle)
                if "affiliate.shopee.vn" in driver.current_url:
                    target_tab = handle
                    break
            except Exception:
                continue

        if not target_tab:
            driver.get(DEFAULT_PORTAL_URL)
            time.sleep(2)
        else:
            if "custom_link" not in driver.current_url:
                driver.get(DEFAULT_PORTAL_URL)
                time.sleep(2)

        time.sleep(1)
        cur_url = driver.current_url.lower()
        if "login" in cur_url or "buyer/login" in cur_url:
            return False, "Trình duyệt chưa đăng nhập tài khoản Shopee Affiliate! Vui lòng đăng nhập trên cửa sổ Chrome Shopee Affiliate vừa mở (chỉ cần đăng nhập 1 lần), sau đó thử lại."

        # 1. Tìm ô nhập link sản phẩm (textarea trên trang Custom Link)
        input_elem = None
        selectors = [
            "textarea",
            "textarea[placeholder*='link']",
            "textarea[placeholder*='liên kết']",
            "textarea[placeholder*='http']",
            "input[type='text']",
            ".custom-link-input"
        ]

        for sel in selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in elems:
                    if el.is_displayed():
                        input_elem = el
                        break
                if input_elem:
                    break
            except Exception:
                continue

        if not input_elem:
            return False, "Không tìm thấy ô nhập link trên trang Shopee Affiliate. Hãy đảm bảo bạn đã đăng nhập và đang ở trang Custom Link."

        # 2. Xóa và kích hoạt sự kiện input/change cho React/Vue
        driver.execute_script("""
            const el = arguments[0];
            const val = arguments[1];
            el.focus();
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        """, input_elem, product_link)

        time.sleep(0.3)
        try:
            # Nhấn thêm phím space rồi backspace để kích hoạt triệt để state của Vue/React
            input_elem.send_keys(" ")
            input_elem.send_keys(Keys.BACK_SPACE)
        except Exception:
            pass
        time.sleep(0.5)

        # 3. Tìm và bấm nút "Lấy link" / "Tạo link"
        button_clicked = False
        button_xpaths = [
            "//button[contains(., 'Lấy link')]",
            "//button[contains(., 'Lấy liên kết')]",
            "//button[contains(., 'Tạo link')]",
            "//button[contains(., 'Tạo liên kết')]",
            "//button[contains(translate(., 'GET LINK', 'get link'), 'get link')]",
            "//button[contains(translate(., 'GENERATE', 'generate'), 'generate')]",
            "//button[contains(@class, 'shopee-button--primary')]"
        ]

        for xpath in button_xpaths:
            try:
                btns = driver.find_elements(By.XPATH, xpath)
                for btn in btns:
                    if btn.is_displayed() and btn.is_enabled():
                        driver.execute_script("arguments[0].click();", btn)
                        button_clicked = True
                        break
                if button_clicked:
                    break
            except Exception:
                continue

        if not button_clicked:
            # Thử click button đầu tiên có màu cam hoặc primary
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for b in buttons:
                try:
                    text = b.text.strip().lower()
                    if any(k in text for k in ["lấy link", "tạo link", "get link", "generate"]) and b.is_enabled():
                        driver.execute_script("arguments[0].click();", b)
                        button_clicked = True
                        break
                except Exception:
                    continue

        if not button_clicked:
            return False, "Không tìm thấy nút 'Lấy link' hoặc nút đang bị khóa trên trang Shopee Affiliate"

        # 4. Chờ link kết quả s.shopee.vn xuất hiện
        short_link = None
        start_wait = time.time()
        while time.time() - start_wait < timeout:
            time.sleep(0.5)
            try:
                # Quét JavaScript trên toàn bộ DOM (input, a, body)
                found = driver.execute_script("""
                    // Quét các thẻ input / textarea kết quả
                    const inputs = Array.from(document.querySelectorAll('input, textarea'));
                    for (const inp of inputs) {
                        const val = inp.value || '';
                        if (val.includes('s.shopee.vn') || val.includes('shp.ee') || val.includes('shope.ee')) {
                            const m = val.match(/https?:\\/\\/(s\\.shopee\\.vn|vn\\.shp\\.ee|shope\\.ee)\\/[a-zA-Z0-9_-]+/);
                            if (m) return m[0];
                        }
                    }
                    // Quét các thẻ link a
                    const links = Array.from(document.querySelectorAll('a'));
                    for (const a of links) {
                        const href = a.href || '';
                        if (href.includes('s.shopee.vn') || href.includes('shp.ee') || href.includes('shope.ee')) {
                            const m = href.match(/https?:\\/\\/(s\\.shopee\\.vn|vn\\.shp\\.ee|shope\\.ee)\\/[a-zA-Z0-9_-]+/);
                            if (m) return m[0];
                        }
                    }
                    // Quét innerText toàn trang
                    const bodyMatch = document.body.innerText.match(/https?:\\/\\/(s\\.shopee\\.vn|vn\\.shp\\.ee|shope\\.ee)\\/[a-zA-Z0-9_-]+/);
                    if (bodyMatch) return bodyMatch[0];
                    return null;
                """)
                if found:
                    short_link = found.strip()
                    break
            except Exception:
                pass

        if short_link:
            return True, short_link
        else:
            return False, "Đã bấm nút 'Lấy link' nhưng không thấy link s.shopee.vn xuất hiện trong thời gian chờ"

    except Exception as e:
        return False, f"Lỗi thao tác Selenium: {str(e)}"
    finally:
        if driver:
            try:
                # Ngắt kết nối session của Selenium, giữ trình duyệt Chrome port 9222 tiếp tục hoạt động
                driver.quit()
            except Exception:
                pass
