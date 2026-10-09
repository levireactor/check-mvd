@echo off
chcp 65001 >nul
title BOT ZALO TỰ ĐỘNG PHẢN HỒI MÃ VẬN ĐƠN 24/7
color 0B
echo ================================================================
echo      BOT ZALO TỰ ĐỘNG PHẢN HỒI TRA CỨU MÃ VẬN ĐƠN 24/7
echo ================================================================
echo.
echo [*] Thư mục làm việc: %~dp0
echo [*] Profile riêng của Bot: %~dp0zalo_bot_profile
echo.
echo CÁCH HOẠT ĐỘNG:
echo 1. Trình duyệt Chrome sẽ mở ra với môi trường riêng biệt (Profile độc lập).
echo 2. Đăng nhập nick Zalo bạn muốn dùng làm Bot (quét mã QR hoặc nhập SĐT).
echo    (Lưu ý: Chỉ cần đăng nhập 1 lần duy nhất, lần sau mở lên sẽ tự nhớ nick).
echo 3. Giữ cửa sổ trình duyệt này mở trên máy:
echo    - Khi khách nhắn tin chào hỏi -> Bot tự chào và hướng dẫn gửi SĐT!
echo    - Khi khách nhắn Số Điện Thoại -> Bot tự tra Sheet và gửi ngay mã vận đơn!
echo.
echo ================================================================
echo [*] Đang kiểm tra và khởi chạy máy chủ dữ liệu Sheet (Port 8080)...
start /b python server.py >nul 2>&1

echo [*] Đang mở trình duyệt Bot Zalo với tiện ích tự động...
timeout /t 2 >nul

:: Thử mở Google Chrome với extension và profile riêng
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="%~dp0zalo_bot_profile" --load-extension="%~dp0zalo_extension" "https://chat.zalo.me"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --user-data-dir="%~dp0zalo_bot_profile" --load-extension="%~dp0zalo_extension" "https://chat.zalo.me"
) else if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --user-data-dir="%~dp0zalo_bot_profile" --load-extension="%~dp0zalo_extension" "https://chat.zalo.me"
) else (
    start "" https://chat.zalo.me
)

echo.
echo [*] Bot Zalo đã được kích hoạt thành công!
echo [*] Hãy giữ cửa sổ này mở để duy trì máy chủ dữ liệu Sheet.
echo ================================================================
pause
