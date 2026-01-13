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
TRANSFER_FILE = "transfer_saved.json"
STATUS_UPDATE_EVERY = 10

STEAL_SPEEDS = {
    b"steal_slow": 50,
    b"steal_medium": 100,
    b"steal_fast": 150,
    b"steal_max": 200
}

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

# ================= TRANSFER PROGRESS =================
def load_transfer():
    if os.path.exists(TRANSFER_FILE):
        with open(TRANSFER_FILE) as f:
            return json.load(f)
    return {}

def save_transfer():
    with open(TRANSFER_FILE, "w") as f:
        json.dump(TRANSFER_DATA, f, indent=2)

TRANSFER_DATA = load_transfer()
TEMP_PROGRESS = {}  # حفظ التقدم للحسابات المؤقتة

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}
TEMP_SESSIONS = {}

# ================= HELPERS =================
def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    for k, v in os.environ.items():
        if k.startswith("TG_SESSION_"):
            try:
                async with TelegramClient(StringSession(v), API_ID, API_HASH) as c:
                    me = await c.get_me()
                    accs.append((k, me.first_name))
            except:
                pass
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

    # ===== TEMP LOGIN FLOW =====
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

    # ===== TRANSFER FLOW =====
    if step == "source":
        s["source"] = text
        s["step"] = "target"
        await event.respond("🔗 أرسل رابط القناة الهدف")
        return

    if step == "target":
        s["target"] = text
        s["running"] = True
        key = f"{s.get('source')}->{s.get('target')}"
        if s.get("client") in TEMP_SESSIONS.values():
            last_id = TEMP_PROGRESS.get(key, {}).get("last_id", 0)
            sent_count = TEMP_PROGRESS.get(key, {}).get("sent", 0)
        else:
            last_id = TRANSFER_DATA.get(key, {}).get("last_id", 0)
            sent_count = TRANSFER_DATA.get(key, {}).get("sent", 0)
        s["last_id"] = last_id
        s["sent"] = sent_count
        s["status"] = await event.respond(
            f"🚀 بدء النقل...\n📊 {s['sent']} / ؟",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )
        asyncio.create_task(run(uid))
        return

    # ===== STEAL LINK =====
    if step == "steal_link":
        s["source"] = text
        s["running"] = True
        s["status"] = await event.respond(
            f"⚡ بدء السرقة...\n📊 0 / ؟",
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
        accs = await get_accounts()
        if not accs:
            await event.respond("❌ لا توجد Sessions صالحة")
            return
        btns = [[Button.inline(n, k.encode())] for k, n in accs]
        await event.respond("اختر الحساب:", buttons=btns)
        s["step"] = "choose_session"
        return

    if s.get("step") == "choose_session":
        s["client"] = TelegramClient(
            StringSession(os.environ[d.decode()]),
            API_ID,
            API_HASH
        )
        await s["client"].start()
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
        TEMP_PROGRESS.clear()
        await event.respond("🧹 تم تسجيل خروج الحسابات المؤقتة")
        return

    # ===== MAIN MENU =====
    if d == b"transfer_menu":
        await show_transfer_menu(event)
        return

    if d == b"new_transfer":
        s.clear()
        s["mode"] = "transfer"
        s["step"] = "source"
        await event.respond("🔗 أرسل رابط القناة المصدر")
        return

    if d == b"resume":
        # دمج القنوات السيشن + المؤقت
        btns = []
        # القنوات المحفوظة من السيشن
        for i, (key, v) in enumerate(TRANSFER_DATA.items()):
            title = v["title"]
            sent = v["sent"]
            btns.append([Button.inline(f"{title} ({sent})", f"res_s_{i}".encode())])
        # القنوات المؤقتة
        for i, (key, v) in enumerate(TEMP_PROGRESS.items()):
            title = key.split("->")[0]
            sent = v["sent"]
            btns.append([Button.inline(f"{title} (TEMP) ({sent})", f"res_t_{i}".encode())])
        if not btns:
            await event.respond("❌ لا توجد قنوات محفوظة")
            return
        await event.respond("اختر قناة للاستكمال:", buttons=btns)
        return

    if d.startswith(b"res_s_"):
        idx = int(d.decode().split("_")[2])
        key = list(TRANSFER_DATA.keys())[idx]
        v = TRANSFER_DATA[key]
        s.update({
            "mode": "transfer",
            "step": "source",
            "source": v["source"],
            "target": v["target"],
            "last_id": v["last_id"],
            "sent": v["sent"]
        })
        await event.respond("🔗 أرسل رابط القناة الهدف (يمكن ترك نفس القديمة)")
        return

    if d.startswith(b"res_t_"):
        idx = int(d.decode().split("_")[2])
        key = list(TEMP_PROGRESS.keys())[idx]
        v = TEMP_PROGRESS[key]
        s.update({
            "mode": "transfer",
            "step": "source",
            "source": key.split("->")[0],
            "target": key.split("->")[1],
            "last_id": v["last_id"],
            "sent": v["sent"]
        })
        await event.respond("🔗 أرسل رابط القناة الهدف (يمكن ترك نفس القديمة)")
        return

    if d == b"reset":
        TRANSFER_DATA.clear()
        TEMP_PROGRESS.clear()
        save_transfer()
        await event.respond("🗑️ تم مسح كل القنوات المحفوظة")
        return

    if d == b"steal_speed":
        await event.respond(
            "⚡ اختر سرعة السرقة:",
            buttons=[
                [Button.inline("🐢 بطيئ (50)", b"steal_slow")],
                [Button.inline("⚖️ متوسط (100)", b"steal_medium")],
                [Button.inline("🚀 سريع جدًا (150)", b"steal_fast")],
                [Button.inline("💀 السرعة الأبدية (200)", b"steal_max")]
            ]
        )
        return

    if d in STEAL_SPEEDS:
        s["mode"] = "steal"
        s["step"] = "steal_link"
        s["steal_batch"] = STEAL_SPEEDS[d]
        await event.respond(f"⚡ تم اختيار السرعة: {s['steal_batch']}\n🔗 أرسل رابط القناة")
        return

    if d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link"})
        await event.respond("🔗 أرسل رابط القناة المحمية")
        return

    if d == b"stop":
        s["running"] = False
        return

# ================= MENUS =================
async def show_main_menu(event):
    await event.respond(
        "اختر العملية:",
        buttons=[
            [Button.inline("📤 نقل", b"transfer_menu")],
            [Button.inline("⚡ السرقة", b"steal_speed")],
            [Button.inline("🔓 السرقة المحمية", b"steal_protected")]
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

# ================= RUN =================
async def run(uid):
    s = state[uid]
    c = s["client"]

    if s["mode"] == "transfer":
        src = await c.get_entity(s["source"])
        dst = await c.get_entity(s["target"])
    else:
        src = await c.get_entity(s["source"])
        dst = await c.get_entity("me")

    total = 0
    async for m in c.iter_messages(src):
        if m.video:
            total += 1

    sent = s.get("sent", 0)
    last_id = s.get("last_id", 0)
    batch = []

    async for m in c.iter_messages(src, offset_id=last_id):
        if not s["running"]:
            break
        if not m.video:
            continue

        if s["mode"] == "steal":
            batch.append(m.video)
            if len(batch) >= s.get("steal_batch", 50):
                await c.send_file(dst, batch)
                sent += len(batch)
                batch.clear()
                await s["status"].edit(f"⚡ السرقة...\n📊 {sent} / {total}")
            continue

        await c.send_file(dst, m.video, caption=clean_caption(m.text))
        sent += 1
        last_id = m.id

        # حفظ التقدم
        if s.get("client") in TEMP_SESSIONS.values():
            key = f"{s['source']}->{s['target']}"
            TEMP_PROGRESS[key] = {"last_id": last_id, "sent": sent}
        else:
            key = f"{s['source']}->{s['target']}"
            TRANSFER_DATA[key] = {
                "title": src.title,
                "source": s["source"],
                "target": s["target"],
                "last_id": last_id,
                "sent": sent
            }
            save_transfer()

        # تحديث العداد
        if sent % STATUS_UPDATE_EVERY == 0 or sent == total:
            await s["status"].edit(f"📊 {sent} / {total}", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])

        if s["mode"] == "transfer":
            await asyncio.sleep(s.get("delay", 10))
        if s["mode"] == "steal_protected":
            await asyncio.sleep(3)

    if s["mode"] == "steal" and batch:
        await c.send_file(dst, batch)
        sent += len(batch)

    await s["status"].edit(f"✅ انتهت العملية\n📊 {sent} / {total}")

bot.run_until_disconnected()
