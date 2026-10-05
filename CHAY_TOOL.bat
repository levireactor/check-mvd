@echo off
chcp 65001 >nul
title Shopee Sheet Manager - Tool Check Đơn & Mã Vận Đơn
color 0B
echo ================================================================
echo           SHOPEE SHEET MANAGER - CÔNG CỤ CHECK ĐƠN HÀNG
echo ================================================================
echo.
echo [*] Thư mục làm việc: %~dp0
echo [*] Đang mở trình duyệt tại: http://localhost:8080/
echo [*] Máy chủ Shopee Mobile Gateway đang hoạt động...
echo.
echo Nhấn Ctrl + C hoặc đóng cửa sổ này nếu muốn dừng Tool.
echo ================================================================
cd /d "%~dp0"
start "" http://localhost:8080
python server.py
pause
