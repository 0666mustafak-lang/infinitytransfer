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
TRANSFER_FILE = "transfer_saved.json"

STEAL_SPEEDS = {
    b"steal_50": 50,
    b"steal_100": 100,
    b"steal_150": 150,
    b"steal_200": 200
}

STATUS_UPDATE_EVERY = 10

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

# ================= TRANSFER MEMORY =================
def load_transfer():
    if os.path.exists(TRANSFER_FILE):
        with open(TRANSFER_FILE) as f:
            return json.load(f)
    return {}

def save_transfer():
    with open(TRANSFER_FILE, "w") as f:
        json.dump(TRANSFER_DATA, f, indent=2)

TRANSFER_DATA = load_transfer()

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

    # AUTH
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
                [Button.inline("🛡 Sessions", b"sessions")],
                [Button.inline("📲 مؤقت", b"temp")]
            ]
        )
        return

    # TARGET FOR TRANSFER
    if s.get("step") == "transfer_target":
        s["target"] = text
        s["running"] = True

        key = f"me->{s['target']}"
        progress = TRANSFER_DATA.get(key, {"last_id": 0, "sent": 0})

        s["last_id"] = progress["last_id"]
        s["sent"] = progress["sent"]

        s["status"] = await event.respond(
            f"🚀 بدء النقل\n📊 {s['sent']} / ؟",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )
        asyncio.create_task(run(uid))
        return

    # STEAL LINK
    if s.get("step") == "steal_link":
        s["source"] = text
        s["running"] = True
        s["status"] = await event.respond(
            "⚡ بدء السرقة\n📊 0 / ؟",
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
        await show_main_menu(event)
        return

    if d == b"temp":
        s["client"] = TelegramClient(StringSession(), API_ID, API_HASH)
        await s["client"].connect()
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل رقم الهاتف")
        return

    if d == b"transfer":
        s["mode"] = "transfer"
        s["step"] = "transfer_target"
        await event.respond("🎯 أرسل رابط الهدف")
        return

    if d == b"resume":
        if not TRANSFER_DATA:
            await event.respond("❌ لا يوجد استكمال")
            return
        btns = []
        for i, (k, v) in enumerate(TRANSFER_DATA.items()):
            btns.append([Button.inline(f"{v['target']} ({v['sent']})", f"res_{i}".encode())])
        await event.respond("اختر للاستكمال:", buttons=btns)
        return

    if d.startswith(b"res_"):
        idx = int(d.decode().split("_")[1])
        key = list(TRANSFER_DATA.keys())[idx]
        s.update({
            "mode": "transfer",
            "target": TRANSFER_DATA[key]["target"],
            "last_id": TRANSFER_DATA[key]["last_id"],
            "sent": TRANSFER_DATA[key]["sent"],
            "running": True
        })
        s["status"] = await event.respond(
            f"▶️ استكمال\n📊 {s['sent']} / ؟",
            buttons=[[Button.inline("⏹️ إيقاف", b"stop")]]
        )
        asyncio.create_task(run(uid))
        return

    if d == b"steal":
        await event.respond(
            "⚡ اختر سرعة السرقة:",
            buttons=[
                [Button.inline("50", b"steal_50"), Button.inline("100", b"steal_100")],
                [Button.inline("150", b"steal_150"), Button.inline("200", b"steal_200")]
            ]
        )
        return

    if d in STEAL_SPEEDS:
        s["mode"] = "steal"
        s["batch"] = STEAL_SPEEDS[d]
        s["step"] = "steal_link"
        await event.respond("🔗 أرسل رابط القناة")
        return

    if d == b"stop":
        s["running"] = False

# ================= MENUS =================
async def show_main_menu(event):
    await event.respond(
        "اختر العملية:",
        buttons=[
            [Button.inline("📤 نقل", b"transfer")],
            [Button.inline("▶️ استكمال", b"resume")],
            [Button.inline("⚡ سرقة", b"steal")]
        ]
    )

# ================= RUN =================
async def run(uid):
    s = state[uid]
    c = s["client"]

    if s["mode"] == "transfer":
        src = await c.get_entity("me")
        dst = await c.get_entity(s["target"])
    else:
        src = await c.get_entity(s["source"])
        dst = await c.get_entity("me")

    total = sum(1 async for m in c.iter_messages(src) if m.video)
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
            if len(batch) >= s["batch"]:
                await c.send_file(dst, batch)
                sent += len(batch)
                batch.clear()
                await s["status"].edit(f"📊 {sent} / {total}")
            continue

        await c.send_file(dst, m.video, caption=clean_caption(m.text))
        sent += 1
        last_id = m.id

        key = f"me->{s['target']}"
        TRANSFER_DATA[key] = {
            "target": s["target"],
            "last_id": last_id,
            "sent": sent
        }
        save_transfer()

        if sent % STATUS_UPDATE_EVERY == 0:
            await s["status"].edit(f"📊 {sent} / {total}")

    if batch:
        await c.send_file(dst, batch)
        sent += len(batch)

    await s["status"].edit(f"✅ انتهى\n📊 {sent} / {total}")

bot.run_until_disconnected()
