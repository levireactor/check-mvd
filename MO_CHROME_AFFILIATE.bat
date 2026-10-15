@echo off
chcp 65001 >nul
title TRÌNH DUYỆT CHROME SHOPEE AFFILIATE (SELENIUM PASSIVE)
color 0B
echo ================================================================
echo       TRÌNH DUYỆT CHROME TỰ ĐỘNG HÓA SHOPEE AFFILIATE
echo    - Cổng kết nối tự động: 9222
echo    - Profile lưu trữ cố định: d:\tool pee\chrome_aff_profile
echo ================================================================
echo.
echo [*] Đang khởi động Google Chrome cho Shopee Affiliate...

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
) else (
    set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

start "" "%CHROME_BIN%" --remote-debugging-port=9222 --user-data-dir="%~dp0chrome_aff_profile" --no-first-run --no-default-browser-check "https://affiliate.shopee.vn/offer/custom_link?mmp_pid=an_17320160631&affiliate_id=17324610663&pid=affiliates&utm_source=an_17320160631&utm_medium=affiliates&utm_content=meoidungkhoa&af_siteid=an_17320160631"

echo [*] Trình duyệt Chrome đã được mở!
echo [*] Vui lòng đăng nhập tài khoản Shopee Affiliate của bạn (chỉ cần đăng nhập 1 lần).
echo [*] Sau đó bạn có thể để cửa sổ này chạy ngầm để Tool tự động lấy link s.shopee.vn!
echo.
pause
