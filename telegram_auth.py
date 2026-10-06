# -*- coding: utf-8 -*-
"""
Telegram Auth & Session Manager
Quản lý đăng nhập Telethon trực tiếp qua Web API:
- Gửi OTP qua SĐT
- Xác nhận OTP
- Xác nhận mật khẩu 2FA
- Import / Export StringSession
- Tự động khôi phục session từ biến môi trường TELEGRAM_SESSION (hỗ trợ Render/Heroku)
"""

import asyncio
import os
import sys
import time
import threading
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError
)

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
SESSION_NAME = os.path.join(DIRECTORY, "session_master")
SESSION_FILE = SESSION_NAME + ".session"
API_ID = 33946669
API_HASH = "d88d388e5810305e722af0cc61a3a80a"

class TelegramAuthManager:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        self._pending_client = None
        self._phone = None
        self._phone_code_hash = None
        self._lock = threading.Lock()
        
        self._cache = {"info": None, "ts": 0}
        
        # Tự động nạp session từ biến môi trường nếu trên server không có file .session
        self._auto_restore_from_env()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro, timeout=35):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def _auto_restore_from_env(self):
        """Khôi phục session từ TELEGRAM_SESSION trong biến môi trường hoặc .env nếu file session chưa tồn tại"""
        if os.path.exists(SESSION_FILE):
            return
        
        env_session = os.environ.get("TELEGRAM_SESSION", "").strip()
        if not env_session:
            env_file = os.path.join(DIRECTORY, ".env")
            if os.path.exists(env_file):
                try:
                    with open(env_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("TELEGRAM_SESSION="):
                                env_session = line.split("=", 1)[1].strip()
                                break
                except Exception:
                    pass
        
        if env_session:
            print("[TelegramAuth] 🔄 Tìm thấy TELEGRAM_SESSION trong môi trường, đang khôi phục...")
            try:
                self.import_string_session(env_session)
                print("[TelegramAuth] ✅ Đã khôi phục session từ TELEGRAM_SESSION thành công!")
            except Exception as e:
                print(f"[TelegramAuth] ⚠️ Khôi phục session từ TELEGRAM_SESSION thất bại: {e}")

    def _extract_user_info(self, me, client=None):
        name_parts = [me.first_name or "", me.last_name or ""]
        full_name = " ".join([p for p in name_parts if p]).strip() or me.username or "Telegram User"
        phone_str = f"+{me.phone}" if me.phone else ""
        
        str_session = ""
        if client and hasattr(client, "session"):
            try:
                str_session = StringSession.save(client.session)
            except Exception:
                pass

        return {
            "connected": True,
            "name": full_name,
            "phone": phone_str,
            "username": me.username or "",
            "user_id": getattr(me, "id", None),
            "string_session": str_session
        }

    def get_info(self, force_refresh=False):
        """Kiểm tra trạng thái đăng nhập Telegram hiện tại"""
        now = time.time()
        if not force_refresh and self._cache["info"] and (now - self._cache["ts"] < 180):
            return self._cache["info"]

        if not os.path.exists(SESSION_FILE):
            res = {
                "connected": False,
                "name": "Chưa kết nối",
                "phone": "",
                "username": "",
                "string_session": ""
            }
            self._cache["info"] = res
            self._cache["ts"] = now
            return res

        async def _check():
            client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
            await client.connect()
            try:
                if await client.is_user_authorized():
                    me = await client.get_me()
                    info = self._extract_user_info(me, client)
                else:
                    info = {
                        "connected": False,
                        "name": "Chưa kết nối",
                        "phone": "",
                        "username": "",
                        "string_session": ""
                    }
            finally:
                await client.disconnect()
            return info

        try:
            res = self._run_async(_check(), timeout=15)
            self._cache["info"] = res
            self._cache["ts"] = now
            return res
        except Exception as e:
            res = {
                "connected": False,
                "name": "Lỗi kết nối",
                "phone": "",
                "username": "",
                "string_session": "",
                "error": str(e)
            }
            self._cache["info"] = res
            self._cache["ts"] = now
            return res

    def send_code(self, phone):
        """Gửi mã OTP đến tài khoản Telegram"""
        phone = phone.strip()
        if not phone.startswith("+"):
            if phone.startswith("0"):
                phone = "+84" + phone[1:]
            elif phone.startswith("84"):
                phone = "+" + phone
            else:
                phone = "+84" + phone

        async def _send():
            with self._lock:
                if self._pending_client and self._pending_client.is_connected():
                    try:
                        await self._pending_client.disconnect()
                    except Exception:
                        pass
                self._pending_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
                await self._pending_client.connect()
                
                # Nếu đã đăng nhập rồi thì thông báo luôn
                if await self._pending_client.is_user_authorized():
                    me = await self._pending_client.get_me()
                    info = self._extract_user_info(me, self._pending_client)
                    await self._pending_client.disconnect()
                    self._pending_client = None
                    self._cache["info"] = info
                    self._cache["ts"] = time.time()
                    return {
                        "success": True,
                        "already_logged_in": True,
                        "account": info,
                        "message": f"Tài khoản {info['name']} đã được đăng nhập sẵn!"
                    }

                sent_code = await self._pending_client.send_code_request(phone)
                self._phone = phone
                self._phone_code_hash = sent_code.phone_code_hash
                return {
                    "success": True,
                    "phone": phone,
                    "phone_code_hash": sent_code.phone_code_hash,
                    "message": f"Đã gửi mã OTP đến App Telegram của số {phone}. Vui lòng mở ứng dụng Telegram để lấy mã 5 số."
                }

        try:
            return self._run_async(_send(), timeout=25)
        except PhoneNumberInvalidError:
            return {"success": False, "error": "Số điện thoại không hợp lệ! Vui lòng kiểm tra lại."}
        except FloodWaitError as e:
            return {"success": False, "error": f"Thao tác quá nhiều lần! Vui lòng chờ {e.seconds} giây trước khi thử lại."}
        except Exception as e:
            return {"success": False, "error": f"Lỗi gửi OTP: {str(e)}"}

    def verify_code(self, code, phone=None, phone_code_hash=None):
        """Xác nhận mã OTP nhận từ Telegram"""
        code = str(code).replace(" ", "").replace("-", "").strip()
        if not code:
            return {"success": False, "error": "Vui lòng nhập mã OTP."}

        async def _verify():
            with self._lock:
                client = self._pending_client
                if not client or not client.is_connected():
                    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
                    await client.connect()
                    self._pending_client = client

                p = phone or self._phone
                h = phone_code_hash or self._phone_code_hash

                if not p or not h:
                    return {"success": False, "error": "Phiên xác thực đã hết hạn, vui lòng gửi lại mã OTP."}

                try:
                    await client.sign_in(phone=p, code=code, phone_code_hash=h)
                    me = await client.get_me()
                    info = self._extract_user_info(me, client)
                    await client.disconnect()
                    self._pending_client = None
                    self._cache["info"] = info
                    self._cache["ts"] = time.time()
                    return {
                        "success": True,
                        "account": info,
                        "string_session": info.get("string_session", ""),
                        "message": f"🎉 Liên kết Telegram thành công! Xin chào {info['name']}."
                    }
                except SessionPasswordNeededError:
                    return {
                        "success": False,
                        "need_2fa": True,
                        "message": "Tài khoản của bạn đã kích hoạt Mật khẩu 2 lớp (2FA). Vui lòng nhập mật khẩu xác nhận."
                    }
                except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                    return {"success": False, "error": "Mã xác nhận (OTP) không đúng hoặc đã hết hạn!"}
                except Exception as e:
                    return {"success": False, "error": f"Lỗi xác thực OTP: {str(e)}"}

        try:
            return self._run_async(_verify(), timeout=25)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_2fa(self, password):
        """Xác nhận mật khẩu bảo mật 2 lớp (2FA)"""
        password = str(password).strip()
        if not password:
            return {"success": False, "error": "Vui lòng nhập mật khẩu 2FA."}

        async def _verify_pass():
            with self._lock:
                client = self._pending_client
                if not client or not client.is_connected():
                    return {"success": False, "error": "Phiên xác thực đã hết hạn, vui lòng gửi lại mã OTP từ đầu."}

                try:
                    await client.sign_in(password=password)
                    me = await client.get_me()
                    info = self._extract_user_info(me, client)
                    await client.disconnect()
                    self._pending_client = None
                    self._cache["info"] = info
                    self._cache["ts"] = time.time()
                    return {
                        "success": True,
                        "account": info,
                        "string_session": info.get("string_session", ""),
                        "message": f"🎉 Xác thực 2FA thành công! Xin chào {info['name']}."
                    }
                except PasswordHashInvalidError:
                    return {"success": False, "error": "Mật khẩu 2FA không chính xác!"}
                except Exception as e:
                    return {"success": False, "error": f"Lỗi xác thực 2FA: {str(e)}"}

        try:
            return self._run_async(_verify_pass(), timeout=25)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def import_string_session(self, session_str):
        """Nhập trực tiếp StringSession của Telethon mà không cần OTP"""
        session_str = str(session_str).strip()
        if not session_str:
            return {"success": False, "error": "Vui lòng nhập chuỗi StringSession."}

        async def _import():
            str_client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await str_client.connect()
            try:
                if not await str_client.is_user_authorized():
                    return {"success": False, "error": "Chuỗi StringSession không hợp lệ hoặc đã hết hạn!"}
                
                me = await str_client.get_me()
                info = self._extract_user_info(me, str_client)

                # Chép thông tin sang file sqlite session_master
                with self._lock:
                    if self._pending_client and self._pending_client.is_connected():
                        await self._pending_client.disconnect()
                    
                    target = TelegramClient(SESSION_NAME, API_ID, API_HASH)
                    target.session.set_dc(str_client.session.dc_id, str_client.session.server_address, str_client.session.port)
                    target.session.auth_key = str_client.session.auth_key
                    target.session.save()
                    target.disconnect()

                self._cache["info"] = info
                self._cache["ts"] = time.time()
                return {
                    "success": True,
                    "account": info,
                    "string_session": session_str,
                    "message": f"🎉 Kích hoạt chuỗi Session thành công cho {info['name']}!"
                }
            finally:
                await str_client.disconnect()

        try:
            return self._run_async(_import(), timeout=25)
        except Exception as e:
            return {"success": False, "error": f"Lỗi nhập chuỗi Session: {str(e)}"}

    def logout(self):
        """Đăng xuất và hủy liên kết tài khoản Telegram"""
        async def _logout():
            with self._lock:
                if self._pending_client and self._pending_client.is_connected():
                    try:
                        await self._pending_client.disconnect()
                    except Exception:
                        pass
                    self._pending_client = None

                if os.path.exists(SESSION_FILE):
                    try:
                        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
                        await client.connect()
                        if await client.is_user_authorized():
                            await client.log_out()
                        else:
                            await client.disconnect()
                    except Exception:
                        pass
                    
                    try:
                        os.remove(SESSION_FILE)
                    except Exception:
                        pass

                empty_info = {
                    "connected": False,
                    "name": "Chưa kết nối",
                    "phone": "",
                    "username": "",
                    "string_session": ""
                }
                self._cache["info"] = empty_info
                self._cache["ts"] = time.time()
                return {"success": True, "message": "Đã huỷ liên kết tài khoản Telegram thành công!"}

        try:
            return self._run_async(_logout(), timeout=20)
        except Exception as e:
            return {"success": False, "error": f"Lỗi huỷ liên kết: {str(e)}"}


# Khởi tạo instance dùng chung cho server
tg_auth_mgr = TelegramAuthManager()
