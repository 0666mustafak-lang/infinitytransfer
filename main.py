import os
import re
import json
import asyncio
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"

# ================= GLOBALS =================
state = {}
TEMP_SESSIONS = {}
ACCOUNTS_CACHE = {}

# ================= AUTH =================
def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, "r") as f:
            return set(map(int, f.read().splitlines()))
    return set()

def save_authorized(uid):
    with open(AUTH_FILE, "a") as f:
        f.write(f"{uid}\n")

AUTHORIZED_USERS = load_authorized()

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ================= HELPERS =================
async def get_accounts():
    accounts = []
    ACCOUNTS_CACHE.clear()

    for key, value in os.environ.items():
        if key.startswith("TG_SESSION_"):
            try:
                async with TelegramClient(StringSession(value), API_ID, API_HASH) as client:
                    me = await client.get_me()
                    name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name
                    accounts.append((key, name))
                    ACCOUNTS_CACHE[key] = value
            except:
                pass

    accounts.sort(key=lambda x: int(re.search(r"\d+", x[0]).group()))
    return accounts

async def send_accounts_buttons(event):
    accounts = await get_accounts()
    if not accounts:
        await event.respond("❌ لا توجد حسابات محفوظة")
        return

    buttons = [
        [Button.inline(f"📸 {name}", key.encode())]
        for key, name in accounts
    ]
    await event.respond("📋 اختر الحساب:", buttons=buttons)

# ================= MENUS =================
async def main_menu(event):
    await event.respond(
        "اهلا وسهلا 👋\nاختر طريقة الدخول:",
        buttons=[
            [Button.inline("🛡 الحسابات المحمية (Session)", b"protected_session")],
            [Button.inline("📲 دخول مؤقت بالرقم", b"temporary_login")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
        ]
    )

async def choose_mode(event):
    await event.respond(
        "اختر العملية:",
        buttons=[
            [Button.inline("📤 نقل الفيديوهات", b"transfer")],
            [Button.inline("🕵️‍♂️ سرقة", b"steal")]
        ]
    )

# ================= START =================
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    uid = event.sender_id
    if uid not in AUTHORIZED_USERS:
        await event.respond("🔐 أرسل رمز الدخول")
        return
    state[uid] = {"step": "menu"}
    await main_menu(event)

# ================= MESSAGE HANDLER =================
@bot.on(events.NewMessage)
async def handler(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.get(uid)

    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            save_authorized(uid)
            state[uid] = {"step": "menu"}
            await event.respond("✅ تم الدخول")
            await main_menu(event)
        else:
            await event.respond("❌ رمز خاطئ")
        return

    if not s:
        return

    # ===== TEMP LOGIN =====
    if s.get("step") == "temp_phone":
        phone = text
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = client
        await client.connect()
        sent = await client.send_code_request(phone)

        s.update({
            "client": client,
            "phone": phone,
            "hash": sent.phone_code_hash,
            "step": "temp_code"
        })
        await event.respond("📩 أرسل كود التحقق")
        return

    if s.get("step") == "temp_code":
        try:
            await s["client"].sign_in(
                phone=s["phone"],
                code=text,
                phone_code_hash=s["hash"]
            )
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 أرسل كلمة مرور 2FA")
            return
        except:
            await event.respond("❌ كود خاطئ")
            return

        s["step"] = "logged"
        await event.respond("✅ تم تسجيل الدخول")
        await choose_mode(event)

    if s.get("step") == "temp_2fa":
        try:
            await s["client"].sign_in(password=text)
        except:
            await event.respond("❌ كلمة المرور خطأ")
            return

        s["step"] = "logged"
        await event.respond("✅ تم تسجيل الدخول")
        await choose_mode(event)

# ================= CALLBACK =================
@bot.on(events.CallbackQuery)
async def callbacks(event):
    await event.answer()
    uid = event.sender_id
    s = state.get(uid)
    if not s:
        return

    data = event.data.decode()

    if data == "protected_session":
        s["step"] = "choose_account"
        await send_accounts_buttons(event)

    elif data == "temporary_login":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل رقم الهاتف مع المفتاح")

    elif data == "clear_temp":
        for cl in TEMP_SESSIONS.values():
            try:
                await cl.log_out()
            except:
                pass
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم تسجيل الخروج")

    elif s.get("step") == "choose_account":
        session_str = ACCOUNTS_CACHE.get(data)
        if not session_str:
            await event.respond("❌ Session غير موجود")
            return

        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.start()
        s["client"] = client
        s["step"] = "logged"
        await choose_mode(event)

    elif data in ("transfer", "steal"):
        await event.respond("🚧 هذه الميزة غير مفعلة بعد")

# ================= RUN =================
bot.run_until_disconnected()
