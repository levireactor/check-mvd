@echo off
chcp 65001 >nul
title DIEU PHOI BOT @dangkyshopee_bot (CART + DIA CHI)
color 0A
echo ================================================================
echo      HE THONG TU DONG DIEU PHOI BOT @dangkyshopee_bot
echo        - Lenh 1: /addtocart (Link san pham)
echo        - Lenh 2: /diachi hoac /addressnew (Wizard dia chi)
echo ================================================================
echo.
echo [*] Dang mo giao dien tren trinh duyet...
start "" http://localhost:8080/dangkyshopee.html

echo [*] Kiem tra may chu Backend...
tasklist /fi "imagename eq python.exe" | find /i "python.exe" >nul
if errorlevel 1 (
    echo [*] Dang khoi dong may chu backend server.py...
    cd /d "%~dp0"
    python server.py
) else (
    echo [*] May chu backend da dang chay san sang!
    echo [*] Giao dien web da duoc mo tai: http://localhost:8080/dangkyshopee.html
    echo.
    echo Nhan phim bat ky de thoat cua so nay (Server van tiep tuc chay ngam)...
    pause >nul
)
