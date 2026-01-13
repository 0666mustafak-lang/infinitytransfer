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

DEFAULT_DELAY = 10  # ⏱️ التأخير الافتراضي للنقل فقط

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

# ================= CHANNELS =================
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
    return re.sub(r'(?:^|\s)@\w+|https?://\S+', '', txt or '')

# ================= HELPERS =================
async def get_accounts():
    accounts = []
    for key, value in os.environ.items():
        if key.startswith("TG_SESSION_"):
            async with TelegramClient(StringSession(value), API_ID, API_HASH) as c:
                me = await c.get_me()
                name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name
                accounts.append((key, name))
    accounts.sort(key=lambda x: x[0])
    return accounts

async def send_accounts_buttons(event):
    accounts = await get_accounts()
    buttons = [
        [Button.inline(f"📸 {name}", key.encode())]
        for key, name in accounts
    ]
    buttons.append([Button.inline("🔄 تحديث الحسابات", b"refresh_accounts")])
    await event.respond("📋 اختر الحساب:", buttons=buttons)

# ================= START =================
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    uid = event.sender_id
    if uid not in AUTHORIZED_USERS:
        await event.respond("🔐 أرسل رمز الدخول")
        return

    state[uid] = {"step": "main"}
    await event.respond(
        "اهلا وسهلا 🥺\nاختر طريقة الدخول 👇",
        buttons=[
            [Button.inline("🛡 الحسابات المحمية (Session)", b"protected_session")],
            [Button.inline("📲 دخول مؤقت بالرقم", b"temporary_login")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp_sessions")]
        ]
    )

# ================= AUTH HANDLER =================
@bot.on(events.NewMessage)
async def auth_handler(event):
    uid = event.sender_id
    txt = (event.text or "").strip()

    if uid in AUTHORIZED_USERS:
        return

    if txt in AUTH_CODES:
        AUTHORIZED_USERS.add(uid)
        save_authorized(uid)
        await event.respond("✅ تم الدخول، أرسل /start")
    else:
        await event.respond("❌ رمز خاطئ")

# ================= CALLBACK =================
@bot.on(events.CallbackQuery)
async def cb(event):
    await event.answer()
    uid = event.sender_id
    s = state.get(uid)
    if not s:
        return

    data = event.data

    if data == b"protected_session":
        s["step"] = "choose_account"
        await send_accounts_buttons(event)
        return

    if data == b"temporary_login":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل رقم الهاتف مع المفتاح الدولي")
        return

    if data == b"clear_temp_sessions":
        for cl in TEMP_SESSIONS.values():
            await cl.log_out()
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم تسجيل خروج جميع الحسابات المؤقتة")
        return

    if data == b"refresh_accounts":
        await send_accounts_buttons(event)
        return

    if s.get("step") == "choose_account":
        key = event.data.decode()
        session_str = os.environ.get(key)
        if not session_str:
            await event.respond("❌ Session غير موجود")
            return

        s["client"] = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await s["client"].start()
        s["step"] = "mode"
        await choose_mode(event)
        return

    if data == b"transfer":
        s["mode"] = "transfer"
        s["delay"] = DEFAULT_DELAY
        s["step"] = "delay"
        await event.respond(
            f"⏱️ أرسل التأخير بالثواني (الافتراضي {DEFAULT_DELAY})"
        )
        return

    if data == b"steal":
        s["mode"] = "steal"
        s["step"] = "steal_mode"
        await choose_steal_mode(event)
        return

    if data in (b"fast", b"all", b"protected"):
        s["send_mode"] = data.decode()
        s["step"] = "link"
        await event.respond("🔗 أرسل رابط القناة")
        return

    if data == b"stop":
        s["running"] = False
        await event.respond("⏹️ تم الإيقاف")
        return

# ================= TEMP LOGIN + FLOW =================
@bot.on(events.NewMessage)
async def flow(event):
    uid = event.sender_id
    s = state.get(uid)
    if not s:
        return

    txt = (event.text or "").strip()

    if s.get("step") == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = c
        await c.connect()
        sent = await c.send_code_request(txt)
        s.update({
            "client": c,
            "phone": txt,
            "hash": sent.phone_code_hash,
            "step": "temp_code"
        })
        await event.respond("🔑 أرسل كود التحقق")
        return

    if s.get("step") == "temp_code":
        try:
            await s["client"].sign_in(
                phone=s["phone"],
                code=txt,
                phone_code_hash=s["hash"]
            )
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 أرسل رمز 2FA")
            return

        s["step"] = "mode"
        await choose_mode(event)
        return

    if s.get("step") == "temp_2fa":
        await s["client"].sign_in(password=txt)
        s["step"] = "mode"
        await choose_mode(event)
        return

    if s.get("step") == "delay":
        if txt.isdigit():
            s["delay"] = int(txt)
        else:
            s["delay"] = DEFAULT_DELAY
        s["step"] = "link"
        await event.respond("🔗 أرسل رابط القناة")
        return

    if s.get("step") == "link":
        s["link"] = txt
        s["running"] = True
        s["sent"] = 0
        s["status"] = await event.respond(
            "🚀 بدء العملية...",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )
        asyncio.create_task(run(uid))
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

async def choose_steal_mode(event):
    await event.respond(
        "اختر طريقة السرقة:",
        buttons=[
            [Button.inline("⚡ fast", b"fast")],
            [Button.inline("📦 all", b"all")],
            [Button.inline("🔓 protected", b"protected")]
        ]
    )

# ================= RUN =================
async def run(uid):
    s = state[uid]
    c = s["client"]

    src = await c.get_entity("me") if s["mode"] == "transfer" else await c.get_entity(s["link"])
    dst = await c.get_entity(s["link"]) if s["mode"] == "transfer" else await c.get_entity("me")

    msgs = [m async for m in c.iter_messages(src) if m.video]
    total = len(msgs)

    for m in msgs:
        if not s["running"]:
            break

        await c.send_file(dst, m.video, caption=clean_caption(m.text))
        s["sent"] += 1

        await s["status"].edit(
            f"📊 {s['sent']} / {total}",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )

        # ⏱️ التأخير فقط للنقل
        if s["mode"] == "transfer":
            await asyncio.sleep(s.get("delay", DEFAULT_DELAY))

    await s["status"].edit("✅ انتهت العملية")

bot.run_until_disconnected()
