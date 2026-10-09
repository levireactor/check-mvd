@echo off
chcp 65001 >nul
title KÍCH HOẠT VÀ MỞ TOOL ZALO ORDER BOT
color 0A
echo ================================================================
echo           ZALO ORDER FILTER BOT - LỌC ĐƠN HÀNG ZALO WEB
echo ================================================================
echo.
echo [*] Thư mục tiện ích Extension: %~dp0zalo_extension
echo.
echo HƯỚNG DẪN 3 BƯỚC CỰC NHANH:
echo 1. Trình duyệt sẽ mở trang quản lý tiện ích: chrome://extensions/
echo 2. Bật công tắc "Chế độ dành cho nhà phát triển" (Developer Mode) ở góc phải trên.
echo 3. Nhấp "Tải tiện ích đã giải nén" (Load Unpacked) -> Chọn thư mục zalo_extension đang mở!
echo.
echo ================================================================
echo [*] Đang mở thư mục Extension trong File Explorer...
start "" explorer.exe "%~dp0zalo_extension"

echo [*] Đang mở Zalo Web (https://chat.zalo.me)...
start "" https://chat.zalo.me

echo.
echo Hãy mở tab mới trên trình duyệt Chrome/Edge và gõ: chrome://extensions
echo Sau đó nạp thư mục "%~dp0zalo_extension" vào nhé!
echo.
echo ================================================================
pause
