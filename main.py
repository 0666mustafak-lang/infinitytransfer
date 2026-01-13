import asyncio
import os
import re
import json
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"
CHANNELS_FILE = "saved_channels.json"

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

# ================= CHANNELS STORAGE =================
def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_channels(data):
    with open(CHANNELS_FILE, "w") as f:
        json.dump(data, f, indent=2)

SAVED_CHANNELS = load_channels()

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}
TEMP_SESSIONS = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

# ================= HELPERS =================
async def get_accounts():
    accounts = []
    for key, value in os.environ.items():
        if key.startswith("TG_SESSION_"):
            async with TelegramClient(StringSession(value), API_ID, API_HASH) as client:
                me = await client.get_me()
                full_name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name
                accounts.append((key, full_name))
    accounts.sort(key=lambda x: int(re.search(r'\d+', x[0]).group()))
    return accounts

async def send_accounts_buttons(uid, event):
    accounts = await get_accounts()
    buttons = [[Button.inline(f"📸 {name}", key)] for key, name in accounts]
    buttons.append([Button.inline("🔄 تحديث الحسابات", "refresh_accounts")])
    await event.respond("📋 اختر الحساب:", buttons=buttons)

# ================= MAIN MENU =================
async def main_menu(event):
    await event.respond(
        "اهلا وسهلا في بوتي 🥺\nاختر طريقة الدخول 👇",
        buttons=[
            [Button.inline("🛡 الحسابات المحمية (Session)", "protected_session")],
            [Button.inline("📲 دخول مؤقت بالرقم", "temporary_login")],
            [Button.inline("🧹 تسجيل خروج المؤقت", "clear_temp_sessions")]
        ]
    )

# ================= START =================
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    uid = event.sender_id
    if uid not in AUTHORIZED_USERS:
        await event.respond("🔐 أرسل رمز الدخول")
        return
    state[uid] = {"step": "main_menu"}
    await main_menu(event)

# ================= AUTH HANDLER =================
@bot.on(events.NewMessage)
async def auth_only(event):
    uid = event.sender_id
    txt = (event.text or "").strip()

    if uid not in AUTHORIZED_USERS:
        try:
            await event.delete()
        except:
            pass

        if txt in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            save_authorized(uid)
            state[uid] = {"step": "main_menu"}
            await event.respond("✅ تم الدخول")
            await main_menu(event)
        else:
            await event.respond("❌ رمز خاطئ")
        return

# ================= CALLBACK =================
@bot.on(events.CallbackQuery)
async def cb(event):
    await event.answer()
    uid = event.sender_id
    s = state.get(uid)
    if not s:
        return

    data = event.data.decode()

    if data == "protected_session":
        await send_accounts_buttons(uid, event)
        s["step"] = "choose_account"
        return

    if data == "temporary_login":
        s["step"] = "temporary_login"
        await event.respond("📲 أرسل رقم الهاتف مع المفتاح الدولي")
        return

    if data == "clear_temp_sessions":
        for cl in TEMP_SESSIONS.values():
            await cl.log_out()
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم تسجيل الخروج المؤقت")
        return

    if s.get("step") == "choose_account":
        session_str = os.environ.get(data)
        if not session_str:
            await event.respond("❌ Session غير موجود")
            return
        s["client"] = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await s["client"].start()
        await choose_mode(event)
        return

# ================= TEMP LOGIN FLOW =================
@bot.on(events.NewMessage)
async def flow_temp(event):
    uid = event.sender_id
    s = state.get(uid)
    if not s:
        return

    # إرسال الرقم
    if s.get("step") == "temporary_login":
        phone = event.text.strip()
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = client

        await client.connect()
        sent = await client.send_code_request(phone)

        s["client"] = client
        s["phone"] = phone
        s["phone_hash"] = sent.phone_code_hash
        s["step"] = "temporary_code"

        await event.respond("✅ تم إرسال كود التحقق 📩\n🔑 أرسل الكود:")
        return

    # استقبال الكود
    if s.get("step") == "temporary_code":
        code = event.text.strip()
        try:
            await s["client"].sign_in(
                phone=s["phone"],
                code=code,
                phone_code_hash=s["phone_hash"]
            )
        except SessionPasswordNeededError:
            s["step"] = "temporary_2fa"
            await event.respond("🔐 الحساب محمي بمصادقة ثنائية\n✍️ أرسل كلمة مرور 2FA:")
            return
        except:
            await event.respond("❌ الكود غير صحيح")
            return

        s["step"] = "logged"
        await event.respond("✅ تم تسجيل الدخول بنجاح")
        await choose_mode(event)
        return

    # استقبال 2FA
    if s.get("step") == "temporary_2fa":
        password = event.text.strip()
        try:
            await s["client"].sign_in(password=password)
        except:
            await event.respond("❌ كلمة المرور غير صحيحة")
            return

        s["step"] = "logged"
        await event.respond("✅ تم تسجيل الدخول بنجاح (2FA)")
        await choose_mode(event)
        return

# ================= MENUS =================
async def choose_mode(event):
    await event.respond(
        "اختر العملية:",
        buttons=[
            [Button.inline("📤 نقل الفيديوهات", b"transfer")],
            [Button.inline("🕵️‍♂️ سرقة", b"steal")]
        ]
    )

# ================= RUN =================
bot.run_until_disconnected()
