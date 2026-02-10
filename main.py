import asyncio
import os
import re
import json
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# استيراد Pyrogram لميزة التنظيف
from pyrogram import Client as PyroClient, enums

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
        json.dump(RECENT_CHANNELS, f, indent=2)

RECENT_CHANNELS = load_channels()
MAX_RECENT = 7

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

state = {}
TEMP_SESSIONS = {}

# ================= HELPERS =================
def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    # فحص سريع للحسابات المحمية
    for k in sorted(os.environ.keys()):
        if not k.startswith("TG_SESSION_"):
            continue
        try:
            # استخدام اتصال سريع للفحص
            async with TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH) as c:
                me = await c.get_me()
                accs.append((k, me.first_name or me.username or "NoName"))
        except Exception:
            continue
    return accs

# ================= MESSAGE ROUTER =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.setdefault(uid, {})

    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            save_authorized(uid)
            await event.respond("✅ تم الدخول، أرسل /start")
        else:
            await event.respond("🔐 أرسل رمز الدخول")
        return

    if text == "/start":
        s.clear()
        await event.respond(
            "اختر طريقة الدخول:",
            buttons=[
                [Button.inline("🛡 الحسابات المحمية", b"sessions")],
                [Button.inline("📲 دخول مؤقت", b"temp")],
                [Button.inline("🔑 استخراج سيشن", b"extract_session")],
                [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
            ]
        )
        return

    step = s.get("step")

    # ===== TEMP LOGIN & EXTRACT =====
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = c
        await c.connect()
        sent = await c.send_code_request(text)
        s.update({"client": c, "phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
        await event.respond("🔑 أرسل كود التحقق")
        return

    if step == "temp_code":
        try:
            await s["client"].sign_in(phone=s["phone"], code=text, phone_code_hash=s["hash"])
            s["raw_session"] = s["client"].session.save()
            if s.get("extract_mode"):
                await event.respond(f"✅ تم استخراج السيشن:\n\n`{s['raw_session']}`")
                s["extract_mode"] = False
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 أرسل رمز 2FA")
            return
        s["step"] = "main"
        await show_main_menu(event)
        return

    if step == "temp_2fa":
        await s["client"].sign_in(password=text)
        s["raw_session"] = s["client"].session.save()
        if s.get("extract_mode"):
            await event.respond(f"✅ تم استخراج السيشن:\n\n`{s['raw_session']}`")
            s["extract_mode"] = False
        s["step"] = "main"
        await show_main_menu(event)
        return

    # ===== TRANSFER =====
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"
        await event.respond("🔗 أرسل الهدف")
        return

    if step == "target":
        s["target"] = text
        s["running"] = True
        s["status"] = await event.respond(
            "🚀 بدء العملية...",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )
        asyncio.create_task(run(uid))
        return

    # ===== STEAL =====
    if step == "steal_link":
        s["source"] = text
        s["running"] = True
        s["status"] = await event.respond(
            "⚡ بدء السرقة...",
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

    if d == b"sessions":
        accs = await get_accounts()
        if not accs:
            await event.respond("❌ لا توجد حسابات")
            return
        btns = [[Button.inline(n, k.encode())] for k, n in accs]
        await event.respond(f"🛡 الحسابات:", buttons=btns)
        s["step"] = "choose_session"
        return

    if s.get("step") == "choose_session":
        sess_str = os.environ[d.decode()]
        s["client"] = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
        await s["client"].start()
        s["raw_session"] = sess_str
        s["step"] = "main"
        await show_main_menu(event)
        return

    if d == b"temp":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل رقم الهاتف")
        return

    if d == b"extract_session":
        s["extract_mode"] = True
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل رقم الهاتف")
        return

    if d == b"clear_temp":
        for c in TEMP_SESSIONS.values():
            try: await c.log_out()
            except: pass
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم تسجيل الخروج")
        return

    if d == b"transfer_menu":
        await show_transfer_menu(event)
        return

    if d == b"new_transfer":
        s.update({"mode": "transfer", "step": "delay", "last_id": 0, "sent": 0})
        await event.respond("⏱️ أرسل التأخير")
        return

    if d == b"resume":
        if not RECENT_CHANNELS:
            await event.respond("❌ لا توجد عمليات")
            return
        btns = [[Button.inline(f"{c['title']} ({c['sent']})", f"res_{i}".encode())] for i, c in enumerate(RECENT_CHANNELS)]
        await event.respond("اختر قناة:", buttons=btns)
        return

    if d.startswith(b"res_"):
        ch = RECENT_CHANNELS[int(d.decode().split("_")[1])]
        s.update(ch)
        s["mode"] = "transfer"
        s["running"] = True
        s["status"] = await event.respond("▶️ استكمال...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid))
        return

    if d == b"reset":
        RECENT_CHANNELS.clear()
        save_channels()
        await event.respond("🗑️ تم المسح")
        return

    if d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "last_id": 0, "sent": 0})
        await event.respond("🔗 أرسل رابط القناة")
        return

    if d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "last_id": 0, "sent": 0})
        await event.respond("🔗 أرسل رابط القناة")
        return

    if d == b"clean_menu":
        asyncio.create_task(pyro_clean_logic(uid))
        return

    if d == b"stop":
        s["running"] = False

# ================= MENUS =================
async def show_main_menu(event):
    await event.respond(
        "اختر العملية:",
        buttons=[
            [Button.inline("📤 النقل", b"transfer_menu")],
            [Button.inline("⚡ السرقة", b"steal")],
            [Button.inline("🔓 السرقة المحمية", b"steal_protected")],
            [Button.inline("🧹 تنظيف الإدمن", b"clean_menu")]
        ]
    )

async def show_transfer_menu(event):
    await event.respond(
        "قائمة النقل:",
        buttons=[
            [Button.inline("📤 نقل جديد", b"new_transfer")],
            [Button.inline("▶️ استكمال", b"resume")],
            [Button.inline("🗑️ إعادة ضبط", b"reset")]
        ]
    )

# ================= CLEAN LOGIC =================
async def pyro_clean_logic(uid):
    s = state[uid]
    if not s.get("raw_session"):
        await bot.send_message(uid, "❌ سجل دخول أولاً")
        return
    lmsg = await bot.send_message(uid, "🔍 فحص الحساب...")
    try:
        async with PyroClient(f"p_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
            btns = []
            async for d in pc.get_dialogs(limit=50):
                if d.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
                    try:
                        m = await pc.get_chat_member(d.chat.id, "me")
                        if m.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                            btns.append([Button.inline(f"🧹 {d.chat.title}", f"pclean_{d.chat.id}".encode())])
                    except: continue
            if btns: await lmsg.edit("✅ اختر لتنظيفه:", buttons=btns)
            else: await lmsg.edit("❌ لا توجد قنوات إدمن")
    except Exception as e: await lmsg.edit(f"❌ خطأ: {e}")

# ================= RUN =================
async def run(uid):
    s = state[uid]
    c = s["client"]

    if s["mode"] == "transfer":
        src = await c.get_entity("me")
        dst = await c.get_entity(s["target"])
    else:
        src = await c.get_entity(s["source"])
        dst = "me"

    msgs = await c.get_messages(src, limit=0)
    total = msgs.total
    batch = []

    # استخدام نفس محرك السرقة القديم بالضبط
    async for m in c.iter_messages(src, offset_id=s.get("last_id", 0)):
        if not s["running"]: break
        if not m.video: continue

        if s["mode"].startswith("steal"):
            batch.append(m.video)
            if len(batch) == 10:
                await c.send_file(dst, batch)
                s["sent"] += len(batch)
                await s["status"].edit(f"📊 {s['sent']} / {total}")
                batch.clear()
            s["last_id"] = m.id
            continue # السرقة سريعة بدون delay

        # نظام النقل
        await c.send_file(dst, m.video, caption=clean_caption(m.text))
        s["last_id"] = m.id
        s["sent"] += 1
        await s["status"].edit(f"📊 {s['sent']} / {total}")

        RECENT_CHANNELS[:] = [x for x in RECENT_CHANNELS if x.get("target") != s.get("target")]
        RECENT_CHANNELS.insert(0, {"title": getattr(dst, 'title', 'Target'), "target": s.get("target"), "last_id": s["last_id"], "sent": s["sent"]})
        del RECENT_CHANNELS[MAX_RECENT:]; save_channels()
        await asyncio.sleep(s.get("delay", 10))

    if batch:
        await c.send_file(dst, batch)
        s["sent"] += len(batch)
        await s["status"].edit(f"📊 {s['sent']} / {total}")

    await s["status"].edit("✅ انتهت العملية")

bot.run_until_disconnected()
