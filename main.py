import asyncio
import os
import re
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"

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

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

state = {}
TEMP_SESSIONS = {}

# ================= MEMORY =================
RECENT_CHANNELS = []   # آخر 7 قنوات
MAX_RECENT = 7

# ================= HELPERS =================
def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    res = []
    for k, v in os.environ.items():
        if k.startswith("TG_SESSION_"):
            async with TelegramClient(StringSession(v), API_ID, API_HASH) as c:
                me = await c.get_me()
                res.append((k, me.first_name))
    return res

async def send_accounts(event):
    accs = await get_accounts()
    btns = [[Button.inline(f"📸 {n}", k.encode())] for k, n in accs]
    btns.append([Button.inline("🔄 تحديث الحسابات", b"refresh_acc")])
    await event.respond("اختر الحساب:", buttons=btns)

# ================= START =================
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    uid = event.sender_id
    if uid not in AUTHORIZED_USERS:
        await event.respond("🔐 أرسل رمز الدخول")
        return

    state[uid] = {}
    await event.respond(
        "اختر:",
        buttons=[
            [Button.inline("🛡 Sessions", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp_login")],
            [Button.inline("▶️ استكمال", b"resume")],
            [Button.inline("🗑️ إعادة ضبط", b"reset")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ]
    )

# ================= AUTH HANDLER =================
@bot.on(events.NewMessage)
async def auth(event):
    uid = event.sender_id
    if uid in AUTHORIZED_USERS:
        return
    if (event.text or "").strip() in AUTH_CODES:
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

    d = event.data

    # ===== الحسابات =====
    if d == b"sessions":
        s["step"] = "choose_acc"
        await send_accounts(event)

    elif d == b"refresh_acc":
        await send_accounts(event)

    elif s.get("step") == "choose_acc":
        key = d.decode()
        s["client"] = TelegramClient(StringSession(os.environ[key]), API_ID, API_HASH)
        await s["client"].start()
        await choose_mode(event)

    # ===== تسجيل مؤقت =====
    elif d == b"temp_login":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل الرقم")

    elif d == b"clear_temp":
        for c in TEMP_SESSIONS.values():
            await c.log_out()
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم الخروج")

    # ===== العمليات =====
    elif d == b"transfer":
        s["mode"] = "transfer"
        s["step"] = "delay"
        await event.respond("⏱️ التأخير (افتراضي 10)")

    elif d == b"steal_fast":
        s["mode"] = "steal_fast"
        s["step"] = "link"
        await event.respond("🔗 رابط القناة")

    elif d == b"steal_protected":
        s["mode"] = "steal_protected"
        s["step"] = "link"
        await event.respond("🔗 رابط القناة")

    # ===== الاستكمال =====
    elif d == b"resume":
        if not RECENT_CHANNELS:
            await event.respond("❌ لا توجد قنوات محفوظة")
            return
        btns = []
        for i, c in enumerate(RECENT_CHANNELS):
            btns.append([Button.inline(f"{c['title']} ({c['sent']})", f"res_{i}".encode())])
        await event.respond("اختر قناة:", buttons=btns)

    elif d.startswith(b"res_"):
        idx = int(d.decode().split("_")[1])
        s.update(RECENT_CHANNELS[idx])
        s["mode"] = "transfer"
        s["running"] = True
        s["status"] = await event.respond(
            "🚀 استكمال...",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )
        asyncio.create_task(run(uid))

    # ===== إعادة ضبط =====
    elif d == b"reset":
        RECENT_CHANNELS.clear()
        await event.respond("🗑️ تم مسح كل القنوات")

    elif d == b"stop":
        s["running"] = False

# ================= FLOW =================
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
        s.update({"client": c, "phone": txt, "hash": sent.phone_code_hash, "step": "temp_code"})
        await event.respond("🔑 أرسل الكود")

    elif s.get("step") == "temp_code":
        try:
            await s["client"].sign_in(phone=s["phone"], code=txt, phone_code_hash=s["hash"])
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 كلمة المرور")
            return
        await choose_mode(event)

    elif s.get("step") == "temp_2fa":
        await s["client"].sign_in(password=txt)
        await choose_mode(event)

    elif s.get("step") == "delay":
        s["delay"] = int(txt) if txt.isdigit() else 10
        s["step"] = "link"
        await event.respond("🔗 رابط القناة")

    elif s.get("step") == "link":
        s["link"] = txt
        s.setdefault("sent", 0)
        s["running"] = True
        s["status"] = await event.respond(
            "🚀 بدء...",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )
        asyncio.create_task(run(uid))

# ================= MENUS =================
async def choose_mode(event):
    await event.respond(
        "اختر:",
        buttons=[
            [Button.inline("📤 نقل عادي", b"transfer")],
            [Button.inline("⚡ النقل الشامل", b"steal_fast")],
            [Button.inline("🔓 السرقة المحمية", b"steal_protected")]
        ]
    )

# ================= RUN =================
async def run(uid):
    s = state[uid]
    c = s["client"]

    src = await c.get_entity(s["link"])
    dst = await c.get_entity("me")

    async for m in c.iter_messages(src, offset_id=s.get("last_id", 0)):
        if not s["running"]:
            break
        if not m.video:
            continue

        await c.send_file(dst, m.video, caption=clean_caption(m.text))

        s["sent"] += 1
        s["last_id"] = m.id

        if s["mode"] == "transfer":
            RECENT_CHANNELS[:] = [x for x in RECENT_CHANNELS if x["link"] != s["link"]]
            RECENT_CHANNELS.insert(0, {
                "title": src.title,
                "link": s["link"],
                "last_id": s["last_id"],
                "sent": s["sent"]
            })
            del RECENT_CHANNELS[MAX_RECENT:]
            await asyncio.sleep(s.get("delay", 10))

        elif s["mode"] == "steal_protected":
            await asyncio.sleep(3)

    await s["status"].edit("✅ انتهت")

bot.run_until_disconnected()
