# -*- coding: utf-8 -*-
"""
MODULE TỰ ĐỘNG HÓA CHUYỂN ĐỔI LINK SHOPEE AFFILIATE BẰNG SELENIUM (CHROME THẬT)
Không cần Open API, Không cần Sub ID, Không sợ bị Shopee chặn Bot / Captcha!
Cơ chế: Kết nối vào Chrome thật qua cổng Remote Debugging (port 9222) và profile lưu vĩnh viễn.
"""

import os
import sys
import time
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_aff_profile")
PORT = 9222

def is_chrome_running():
    """Kiểm tra cổng 9222 đã có Chrome lắng nghe chưa"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.connect(('127.0.0.1', PORT))
        s.close()
        return True
    except Exception:
        return False

def launch_chrome_affiliate():
    """Khởi động trình duyệt Chrome độc lập cho Shopee Affiliate"""
    if is_chrome_running():
        return True, "Chrome Shopee Affiliate đã đang chạy sẵn sàng"

    os.makedirs(PROFILE_DIR, exist_ok=True)
    cmd = [
        CHROME_PATH,
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://affiliate.shopee.vn/offer/custom_link"
    ]
    try:
        subprocess.Popen(cmd)
        # Chờ Chrome sẵn sàng
        for _ in range(15):
            time.sleep(0.5)
            if is_chrome_running():
                return True, "Đã mở trình duyệt Chrome Shopee Affiliate thành công"
        return False, "Không kết nối được cổng Chrome sau khi khởi động"
    except Exception as e:
        return False, f"Lỗi khởi động Chrome: {e}"

def convert_link_via_selenium(product_link, timeout=15):
    """
    Điều khiển Chrome tự động dán link và lấy link rút gọn s.shopee.vn
    """
    product_link = product_link.strip()
    if not product_link:
        return False, "Link sản phẩm trống"

    # Nếu Chrome chưa chạy, tự khởi động
    if not is_chrome_running():
        ok, msg = launch_chrome_affiliate()
        if not ok:
            return False, f"Chưa thể kết nối Chrome: {msg}"
        time.sleep(2)

    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{PORT}")

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        
        # Kiểm tra xem đã có tab custom_link chưa
        target_tab = None
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if "affiliate.shopee.vn" in driver.current_url:
                target_tab = handle
                break

        if not target_tab:
            driver.get("https://affiliate.shopee.vn/offer/custom_link")
            time.sleep(2)
        else:
            if "custom_link" not in driver.current_url:
                driver.get("https://affiliate.shopee.vn/offer/custom_link")
                time.sleep(2)

        # Chờ trang tải và kiểm tra đăng nhập
        time.sleep(1)
        if "login" in driver.current_url.lower():
            return False, "Trình duyệt chưa đăng nhập tài khoản Shopee Affiliate! Vui lòng đăng nhập trên cửa sổ Chrome."

        # 1. Tìm ô nhập link sản phẩm (textarea hoặc input)
        input_elem = None
        selectors = [
            "textarea",
            "input[type='text']",
            "input[placeholder*='http']",
            "input[placeholder*='shopee']",
            ".custom-link-input",
            "textarea[placeholder*='link']"
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
            return False, "Không tìm thấy ô nhập link trên trang Shopee Affiliate"

        # 2. Xóa và nhập link sản phẩm mới
        input_elem.clear()
        time.sleep(0.2)
        # Nếu clear chưa sạch, dùng script
        driver.execute_script("arguments[0].value = '';", input_elem)
        input_elem.send_keys(product_link)
        time.sleep(0.5)

        # 3. Tìm và bấm nút "Lấy link" / "Tạo link"
        button_clicked = False
        button_selectors = [
            "//button[contains(text(), 'Lấy link')]",
            "//button[contains(text(), 'Tạo link')]",
            "//button[contains(text(), 'Lấy liên kết')]",
            "//button[contains(text(), 'Tạo liên kết')]",
            "//button[contains(., 'Lấy link')]",
            "//button[contains(., 'Tạo link')]",
            "//button[@type='button' and contains(@class, 'shopee-button')]"
        ]

        for xpath in button_selectors:
            try:
                btn = driver.find_element(By.XPATH, xpath)
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    button_clicked = True
                    break
            except Exception:
                continue

        if not button_clicked:
            # Thử click button đầu tiên có màu cam hoặc primary
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for b in buttons:
                text = b.text.strip().lower()
                if any(k in text for k in ["lấy link", "tạo link", "get link", "generate"]):
                    b.click()
                    button_clicked = True
                    break

        if not button_clicked:
            return False, "Không tìm thấy nút 'Lấy link' trên trang Shopee Affiliate"

        # 4. Chờ link kết quả s.shopee.vn xuất hiện
        short_link = None
        start_wait = time.time()
        while time.time() - start_wait < timeout:
            time.sleep(0.5)
            # Quét tất cả thẻ a, input, div chứa s.shopee.vn
            try:
                # Tìm trong input kết quả
                res_inputs = driver.find_elements(By.XPATH, "//input[contains(@value, 's.shopee.vn')]")
                for r_in in res_inputs:
                    val = r_in.get_attribute("value")
                    if val and "s.shopee.vn" in val:
                        short_link = val.strip()
                        break
                if short_link:
                    break

                # Tìm trong thẻ a
                links = driver.find_elements(By.XPATH, "//a[contains(@href, 's.shopee.vn')]")
                for l in links:
                    href = l.get_attribute("href")
                    if href and "s.shopee.vn" in href:
                        short_link = href.strip()
                        break
                if short_link:
                    break

                # Tìm bằng JavaScript quét toàn bộ trang
                js_link = driver.execute_script("""
                    const m = document.body.innerText.match(/https:\\/\\/s\\.shopee\\.vn\\/[a-zA-Z0-9_-]+/);
                    return m ? m[0] : null;
                """)
                if js_link:
                    short_link = js_link
                    break
            except Exception:
                pass

        if short_link:
            return True, short_link
        else:
            return False, "Đã bấm nút nhưng không thấy link s.shopee.vn xuất hiện trong thời gian chờ"

    except Exception as e:
        return False, f"Lỗi thao tác Selenium: {str(e)}"
