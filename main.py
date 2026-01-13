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

MAX_RECENT = 7
SESSION_LIST_DELAY = 3  # ⏱️ غيّر الرقم براحتك (ثواني)

# ================= AUTH =================
def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE) as f:
            return set(map(int, f.read().splitlines()))
    return set()

def save_authorized(uid):
    with open(AUTH_FILE, "a") as f:
        f.write(f"{uid}\n")

AUTHORIZED_USERS = load_authorized()

# ================= CHANNEL MEMORY =================
def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE) as f:
            return json.load(f)
    return []

def save_channels():
    with open(CHANNELS_FILE, "w") as f:
        json.dump(RECENT_CHANNELS, f, indent=2, ensure_ascii=False)

RECENT_CHANNELS = load_channels()

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

state = {}
TEMP_SESSIONS = {}

# ================= HELPERS =================
def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '').strip()

# ================= SESSION LOADER =================
async def get_accounts():
    accs = []

    for k in sorted(os.environ):
        if not k.startswith("TG_SESSION_"):
            continue

        session_str = os.environ.get(k)
        if not session_str or len(session_str) < 50:
            continue

        try:
            client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await client.connect()

            if not await client.is_user_authorized():
                await client.disconnect()
                continue

            me = await client.get_me()
            accs.append((k, me.first_name or "NoName"))

            await client.disconnect()

        except Exception as e:
            print(f"SESSION ERROR {k}: {e}")

    return accs

# ================= MESSAGE ROUTER =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.setdefault(uid, {})

    # ===== AUTH =====
    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            save_authorized(uid)
            await event.respond("✅ تم الدخول، أرسل /start")
        else:
            await event.respond("🔐 أرسل رمز الدخول")
        return

    # ===== START =====
    if text == "/start":
        s.clear()
        await event.respond(
            "اختر طريقة الدخول:",
            buttons=[
                [Button.inline("🛡 الحسابات المحمية (Session)", b"sessions")],
                [Button.inline("📲 دخول مؤقت", b"temp")],
                [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
            ]
        )
        return

    step = s.get("step")

    # ===== TEMP LOGIN =====
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = c
        await c.connect()
        sent = await c.send_code_request(text)
        s.update({
            "client": c,
            "phone": text,
            "hash": sent.phone_code_hash,
            "step": "temp_code"
        })
        await event.respond("🔑 أرسل كود التحقق")
        return

    if step == "temp_code":
        try:
            await s["client"].sign_in(
                phone=s["phone"],
                code=text,
                phone_code_hash=s["hash"]
            )
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 أرسل رمز 2FA")
            return

        s["step"] = "main"
        await show_main_menu(event)
        return

    if step == "temp_2fa":
        await s["client"].sign_in(password=text)
        s["step"] = "main"
        await show_main_menu(event)
        return

    # ===== TRANSFER / STEAL INPUT =====
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"
        await event.respond("🔗 أرسل رابط القناة / الكروب")
        return

    if step in ("target", "steal_link"):
        key = "target" if s["mode"] == "transfer" else "source"
        s[key] = text
        s["running"] = True
        s["status"] = await event.respond(
            "🚀 بدء العملية...",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )
        asyncio.create_task(run(uid))
        return

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    await event.answer()
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    # ===== SESSION LOGIN =====
    if d == b"sessions":
        msg = await event.respond("⏳ جاري فحص حسابات Session...")
        await asyncio.sleep(SESSION_LIST_DELAY)

        accs = await get_accounts()
        count = len(accs)

        if count == 0:
            await msg.edit(
                "❌ لا توجد حسابات Session صالحة\n\n"
                "• الحساب مبند\n"
                "• السيشن منتهي\n"
                "• تسجيل خروج من جهاز آخر\n\n"
                "⬅️ استخدم الدخول المؤقت"
            )
            return

        btns = [[Button.inline(n, k.encode())] for k, n in accs]
        await msg.edit(
            f"🛡 تم العثور على {count} حساب Session\n\nاختر الحساب:",
            buttons=btns
        )
        s["step"] = "choose_session"
        return

    if s.get("step") == "choose_session":
        session_key = d.decode()
        session_str = os.environ.get(session_key)

        if not session_str:
            await event.respond("❌ السيشن غير موجود")
            return

        s["client"] = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await s["client"].connect()

        if not await s["client"].is_user_authorized():
            await event.respond("❌ السيشن غير صالح")
            return

        s["step"] = "main"
        await show_main_menu(event)
        return

    # ===== TEMP =====
    if d == b"temp":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل رقم الهاتف")
        return

    if d == b"clear_temp":
        for c in TEMP_SESSIONS.values():
            await c.log_out()
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم تسجيل خروج الحسابات المؤقتة")
        return

    # ===== MAIN MENU =====
    if d == b"transfer_menu":
        await show_transfer_menu(event)
        return

    if d == b"new_transfer":
        s.update({"mode": "transfer", "step": "delay", "last_id": 0, "sent": 0})
        await event.respond("⏱️ أرسل التأخير (افتراضي 10)")
        return

    if d == b"steal":
        s.update({"mode": "steal", "step": "steal_link"})
        await event.respond("🔗 أرسل رابط القناة / الكروب")
        return

    if d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link"})
        await event.respond("🔗 أرسل رابط القناة / الكروب")
        return

    if d == b"stop":
        s["running"] = False
        return

# ================= MENUS =================
async def show_main_menu(event):
    await event.respond(
        "اختر العملية:",
        buttons=[
            [Button.inline("📤 نقل عادي", b"transfer_menu")],
            [Button.inline("⚡ السرقة", b"steal")],
            [Button.inline("🔓 السرقة المحمية", b"steal_protected")]
        ]
    )

async def show_transfer_menu(event):
    await event.respond(
        "قائمة النقل:",
        buttons=[
            [Button.inline("📤 نقل جديد", b"new_transfer")]
        ]
    )

# ================= RUN =================
async def run(uid):
    s = state[uid]
    c = s["client"]

    src = await c.get_entity("me" if s["mode"] == "transfer" else s["source"])
    dst = await c.get_entity(s.get("target", "me"))

    async for m in c.iter_messages(src, offset_id=s.get("last_id", 0)):
        if not s["running"]:
            break
        if not m.video:
            continue

        await c.send_file(dst, m.video, caption=clean_caption(m.text))
        s["last_id"] = m.id
        s["sent"] += 1

        await asyncio.sleep(s.get("delay", 3))

    await s["status"].edit("✅ انتهت العملية")

bot.run_until_disconnected()
