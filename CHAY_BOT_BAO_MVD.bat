@echo off
chcp 65001 >nul
title BOT TELEGRAM BÁO NHẢY MÃ VẬN ĐƠN SHOPEE 24/7
color 0A
echo ================================================================
echo       BOT TELEGRAM TỰ ĐỘNG BÁO NHẢY MÃ VẬN ĐƠN SHOPEE 24/7
echo ================================================================
echo.
echo [*] Thư mục làm việc: %~dp0
echo [*] Chế độ: Quét ngầm định kỳ & Phản hồi lệnh Telegram Bot
echo.
echo CÁCH HOẠT ĐỘNG:
echo 1. Bot tự động đọc danh sách đơn hàng từ draft.json / Supabase.
echo 2. Định kỳ kiểm tra các đơn chưa có mã vận đơn.
echo 3. Khi người bán bàn giao hàng và Shopee sinh mã vận đơn mới:
echo    - Bot lập tức bắn thông báo Telegram chi tiết kèm link tra cứu!
echo    - Cập nhật thẳng mã vận đơn vào bảng dữ liệu web.
echo 4. Bạn có thể chat trực tiếp với Bot trên Telegram:
echo    - Gõ /check để quét ngay lập tức
echo    - Gõ /mvd để xem danh sách mã vận đơn mới
echo    - Gõ /pending để xem đơn chưa có mã
echo    - Gõ /status để xem trạng thái
echo.
echo ================================================================
echo [*] Đang khởi động Bot Telegram MVD Watcher...
echo.
cd /d "%~dp0"
python telegram_mvd_watcher.py
pause
