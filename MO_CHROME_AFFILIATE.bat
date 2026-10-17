@echo off
chcp 65001 >nul
title TRÌNH DUYỆT CHROME SHOPEE AFFILIATE (SELENIUM PASSIVE)
color 0B
echo ================================================================
echo       TRÌNH DUYỆT CHROME TỰ ĐỘNG HÓA SHOPEE AFFILIATE
echo    - Cổng kết nối tự động: 9222
echo    - Profile lưu trữ cố định: %~dp0chrome_aff_profile
echo ================================================================
echo.
echo [*] Đang khởi động Google Chrome cho Shopee Affiliate...

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) else if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
) else (
    set "CHROME_BIN=chrome.exe"
)

start "" "%CHROME_BIN%" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="%~dp0chrome_aff_profile" --no-first-run --no-default-browser-check "https://affiliate.shopee.vn/offer/custom_link?mmp_pid=an_17320160631&affiliate_id=17324610663&pid=affiliates&utm_source=an_17320160631&utm_medium=affiliates&utm_content=meoidungkhoa&af_siteid=an_17320160631"

echo.
echo [*] Trình duyệt Chrome Shopee Affiliate đã được mở!
echo [*] HƯỚNG DẪN:
echo     1. Đăng nhập tài khoản Shopee Affiliate của bạn trên cửa sổ Chrome vừa mở.
echo        (Chỉ cần đăng nhập 1 lần duy nhất, dữ liệu đăng nhập được lưu vĩnh viễn).
echo     2. Sau khi vào được trang web, bạn có thể thu nhỏ cửa sổ Chrome này lại.
echo     3. Quay lại Tool dangkyshopee.html để kiểm tra và tự động lấy link s.shopee.vn!
echo.
echo ================================================================
pause
