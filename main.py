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
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

# ================= HELPERS =================
async def get_accounts():
    accounts = []
    for k, v in os.environ.items():
        if k.startswith("TG_SESSION_"):
            async with TelegramClient(StringSession(v), API_ID, API_HASH) as c:
                me = await c.get_me()
                name = f"{me.first_name} {me.last_name}" if me.last_name else me.first_name
                accounts.append((k, name))
    return sorted(accounts, key=lambda x: x[0])

async def send_accounts(event):
    buttons = [
        [Button.inline(f"📸 {name}", key.encode())]
        for key, name in await get_accounts()
    ]
    await event.respond("📋 اختر الحساب:", buttons=buttons)

# ================= START =================
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    uid = event.sender_id
    if uid not in AUTHORIZED_USERS:
        await event.respond("🔐 أرسل رمز الدخول")
        return

    state[uid] = {
        "step": "choose_account",
        "delay": 10,
        "sent": 0,
        "running": False
    }

    await event.respond(
        "اختر طريقة الدخول:",
        buttons=[
            [Button.inline("🛡 Session", b"protected")],
            [Button.inline("📲 دخول مؤقت", b"temp")]
        ]
    )

# ================= CALLBACK =================
@bot.on(events.CallbackQuery)
async def cb(event):
    await event.answer()
    uid = event.sender_id
    s = state.get(uid)
    if not s:
        return

    data = event.data.decode()

    if data == "protected":
        await send_accounts(event)
        s["step"] = "choose_account"
        return

    if data == "temp":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل رقم الهاتف")
        return

    if s["step"] == "choose_account":
        sess = os.environ.get(data)
        if not sess:
            await event.respond("❌ Session غير موجود")
            return
        c = TelegramClient(StringSession(sess), API_ID, API_HASH)
        await c.start()
        s["client"] = c
        s["step"] = "mode"
        await choose_mode(event)
        return

    if data == "transfer":
        s["mode"] = "transfer"
        s["step"] = "delay"
        await event.respond("⏱️ أرسل وقت التأخير بالثواني")
        return

    if data == "steal":
        s["mode"] = "steal"
        await choose_steal_mode(event)
        return

    if data in ("fast", "all", "protected"):
        s["send_mode"] = data
        s["step"] = "link"
        await event.respond("🔗 أرسل رابط القناة")
        return

    if data == "stop":
        s["running"] = False
        await event.respond("⏹️ تم الإيقاف")
        return

# ================= TEMP LOGIN =================
@bot.on(events.NewMessage)
async def flow(event):
    uid = event.sender_id
    s = state.get(uid)
    if not s:
        return

    txt = event.text.strip()

    if s["step"] == "temp_phone":
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

    if s["step"] == "temp_code":
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

    if s["step"] == "temp_2fa":
        await s["client"].sign_in(password=txt)
        s["step"] = "mode"
        await choose_mode(event)
        return

    if s["step"] == "delay":
        s["delay"] = int(txt)
        s["step"] = "link"
        await event.respond("🔗 أرسل رابط القناة")
        return

    if s["step"] == "link":
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
            [Button.inline("📤 نقل", b"transfer")],
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
        await asyncio.sleep(s["delay"])

    await s["status"].edit("✅ انتهت العملية")

bot.run_until_disconnected()
