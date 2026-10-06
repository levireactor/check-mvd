# -*- coding: utf-8 -*-
"""
Telegram Auth & Session Manager
Quản lý đăng nhập Telethon trực tiếp qua Web API:
- Gửi OTP qua SĐT
- Xác nhận OTP
- Xác nhận mật khẩu 2FA
- Import / Export StringSession
- Tự động khôi phục session từ biến môi trường TELEGRAM_SESSION (hỗ trợ Render/Heroku)
- CƠ CHẾ CHỐNG LOCK HOÀN TOÀN: Sử dụng in-memory StringSession thay vì SQLite session file,
  giúp nhiều tiến trình (server, worker, login_telegram) chạy đồng thời mà KHÔNG BAO GIỜ bị 'database is locked'.
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
STR_SESSION_FILE = os.path.join(DIRECTORY, "session_master.string_session")
API_ID = 33946669
API_HASH = "d88d388e5810305e722af0cc61a3a80a"

# Slot Telegram mặc định có sẵn của hệ thống
DEFAULT_TELEGRAM_SLOT = {
    "id": "slot_master",
    "name": "chubin đặng",
    "phone": "+84967193558",
    "username": "senykaroa",
    "user_id": 5183005662,
    "string_session": "1BVtsOG4Bu38H6CC0ejYTb2vsIn0Lstvy_TQceV4970quNkL-wrcoaaIwkBcYx9N-9aHsqQmjKadPsm6PE0m3PcvJiIjIpJlMRVvZm_RJvojNT3-vtQeflr7IAoojIACOto5xL7xy75iM99WPDvGLCSo4OuMLDxgFpG3IzuDOe4e0fcdt0YkAhivyuCmpyzxEMXOrSzeDRrb-_Co5-3W6zw8D0kULxwB0C5AIfu13E_CrKeBrV05-dEdgobetD-q1fIQ0hGQ1vMJiDwyP87zgxeLiUYp2Zs17VL8yl-57xV4grlHtpZgrEJ8-EA7l9uMrPnH5xmRBFVqN6st8hZ9-951TP1xeW_o="
}

def get_string_session_str():
    """Lấy chuỗi session string từ các nguồn ưu tiên cao nhất, tuyệt đối không bị khóa file"""
    # 1. File session_master.string_session
    if os.path.exists(STR_SESSION_FILE):
        try:
            with open(STR_SESSION_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    # 2. Biến môi trường TELEGRAM_SESSION
    env_str = os.environ.get("TELEGRAM_SESSION", "").strip()
    if env_str:
        return env_str

    # 3. File .env
    env_file = os.path.join(DIRECTORY, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TELEGRAM_SESSION="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
        except Exception:
            pass

    # 4. Slot Telegram mặc định
    if DEFAULT_TELEGRAM_SLOT.get("string_session"):
        return DEFAULT_TELEGRAM_SLOT["string_session"].strip()

    # 5. Fallback trích xuất từ SQLite file session_master.session nếu có
    if os.path.exists(SESSION_FILE):
        try:
            from telethon.sessions import SQLiteSession
            sq_sess = SQLiteSession(SESSION_NAME)
            if sq_sess.auth_key:
                val = StringSession.save(sq_sess)
                if val:
                    try:
                        with open(STR_SESSION_FILE, "w", encoding="utf-8") as f:
                            f.write(val)
                    except Exception:
                        pass
                    return val
        except Exception:
            pass

    return ""

def get_telethon_session():
    """
    Trả về StringSession Telethon (In-Memory).
    Tránh hoàn toàn lỗi 'database is locked' của SQLite trên Windows khi nhiều tiến trình chạy song song.
    """
    s_str = get_string_session_str()
    return StringSession(s_str)

def save_session_string(session_str):
    """Lưu chuỗi StringSession vào file session_master.string_session và đồng bộ sang SQLite an toàn"""
    session_str = (session_str or "").strip()
    if not session_str:
        return
    try:
        with open(STR_SESSION_FILE, "w", encoding="utf-8") as f:
            f.write(session_str)
    except Exception as e:
        print(f"[TelegramAuth] Lỗi lưu session string: {e}")

    # Đồng bộ sang session_master.session với WAL mode nếu cần tương thích ngược
    try:
        import sqlite3
        conn = sqlite3.connect(SESSION_FILE, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.close()

        target = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        temp_sess = StringSession(session_str)
        target.session.set_dc(temp_sess.dc_id, temp_sess.server_address, temp_sess.port)
        target.session.auth_key = temp_sess.auth_key
        target.session.save()
        target.disconnect()
    except Exception:
        pass


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
        
        # Tự động nạp session từ biến môi trường hoặc slot mặc định nếu trên server không có file .session
        self._auto_restore_from_env()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro, timeout=35):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def _auto_restore_from_env(self):
        """Khôi phục session từ TELEGRAM_SESSION trong biến môi trường hoặc .env hoặc DEFAULT_TELEGRAM_SLOT nếu chưa có session"""
        existing_str = get_string_session_str()
        if existing_str and not os.path.exists(STR_SESSION_FILE):
            save_session_string(existing_str)
            return

        if existing_str or os.path.exists(SESSION_FILE):
            return

        default_str = DEFAULT_TELEGRAM_SLOT.get("string_session", "").strip()
        if default_str:
            print("[TelegramAuth] 👑 Tự động dùng Slot Telegram mặc định (chubin đặng)...")
            try:
                self.import_string_session(default_str)
                print("[TelegramAuth] ✅ Đã kích hoạt phiên Telegram mặc định thành công!")
            except Exception as e:
                print(f"[TelegramAuth] ⚠️ Tự động kích hoạt session thất bại: {e}")

    def load_default_slot(self):
        """Kích hoạt ngay slot Telegram mặc định của hệ thống"""
        session_str = DEFAULT_TELEGRAM_SLOT.get("string_session")
        res = self.import_string_session(session_str)
        if res.get("success"):
            res["message"] = f"🎉 Đã kích hoạt Slot mặc định ({DEFAULT_TELEGRAM_SLOT['name']} - {DEFAULT_TELEGRAM_SLOT['phone']}) thành công!"
            res["is_default_slot"] = True
        return res

    def get_preset_slots(self):
        """Lấy danh sách các slot tài khoản có sẵn trong hệ thống"""
        curr = self.get_info()
        is_active = (curr.get("phone") == DEFAULT_TELEGRAM_SLOT["phone"]) or (curr.get("user_id") == DEFAULT_TELEGRAM_SLOT["user_id"])
        return [
            {
                "id": DEFAULT_TELEGRAM_SLOT["id"],
                "name": DEFAULT_TELEGRAM_SLOT["name"],
                "phone": DEFAULT_TELEGRAM_SLOT["phone"],
                "username": DEFAULT_TELEGRAM_SLOT["username"],
                "user_id": DEFAULT_TELEGRAM_SLOT["user_id"],
                "string_session": DEFAULT_TELEGRAM_SLOT["string_session"],
                "is_active": is_active,
                "badge": "Mặc định hệ thống"
            }
        ]

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
        if not str_session:
            str_session = get_string_session_str()

        return {
            "connected": True,
            "name": full_name,
            "phone": phone_str,
            "username": me.username or "",
            "user_id": getattr(me, "id", None),
            "string_session": str_session
        }

    def get_info(self, force_refresh=False):
        """Kiểm tra trạng thái đăng nhập Telegram hiện tại - Sử dụng StringSession, không lock SQLite"""
        now = time.time()
        if not force_refresh and self._cache["info"] and (now - self._cache["ts"] < 180):
            return self._cache["info"]

        session_str = get_string_session_str()
        if not session_str and not os.path.exists(SESSION_FILE):
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
            sess = get_telethon_session()
            client = TelegramClient(sess, API_ID, API_HASH)
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
        """Gửi mã OTP đến tài khoản Telegram qua In-memory StringSession"""
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
                
                # Khởi tạo In-Memory client mới, KHÔNG chạm vào file SQLite để tránh lock
                self._pending_client = TelegramClient(StringSession(), API_ID, API_HASH)
                await self._pending_client.connect()
                
                # Nếu đã đăng nhập rồi thì thông báo luôn
                if await self._pending_client.is_user_authorized():
                    me = await self._pending_client.get_me()
                    info = self._extract_user_info(me, self._pending_client)
                    saved_str = self._pending_client.session.save()
                    save_session_string(saved_str)
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
                    return {"success": False, "error": "Phiên xác thực đã hết hạn, vui lòng gửi lại mã OTP."}

                p = phone or self._phone
                h = phone_code_hash or self._phone_code_hash

                if not p or not h:
                    return {"success": False, "error": "Phiên xác thực đã hết hạn, vui lòng gửi lại mã OTP."}

                try:
                    await client.sign_in(phone=p, code=code, phone_code_hash=h)
                    me = await client.get_me()
                    info = self._extract_user_info(me, client)
                    saved_str = client.session.save()
                    save_session_string(saved_str)
                    info["string_session"] = saved_str
                    await client.disconnect()
                    self._pending_client = None
                    self._cache["info"] = info
                    self._cache["ts"] = time.time()
                    return {
                        "success": True,
                        "account": info,
                        "string_session": saved_str,
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
                    saved_str = client.session.save()
                    save_session_string(saved_str)
                    info["string_session"] = saved_str
                    await client.disconnect()
                    self._pending_client = None
                    self._cache["info"] = info
                    self._cache["ts"] = time.time()
                    return {
                        "success": True,
                        "account": info,
                        "string_session": saved_str,
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

                # Lưu vào file StringSession và SQLite (nếu có thể)
                save_session_string(session_str)

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

                session_str = get_string_session_str()
                if session_str:
                    try:
                        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
                        await client.connect()
                        if await client.is_user_authorized():
                            await client.log_out()
                        else:
                            await client.disconnect()
                    except Exception:
                        pass

                if os.path.exists(STR_SESSION_FILE):
                    try:
                        os.remove(STR_SESSION_FILE)
                    except Exception:
                        pass

                if os.path.exists(SESSION_FILE):
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
