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
    b"s50": 50,
    b"s100": 100,
    b"s150": 150,
    b"s200": 200
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
                [Button.inline("📲 مؤقت", b"temp")],
                [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
            ]
        )
        return

    # TEMP LOGIN
    if s.get("step") == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = c
        await c.connect()
        sent = await c.send_code_request(text)
        s.update({"client": c, "phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
        await event.respond("🔑 أرسل الكود")
        return

    if s.get("step") == "temp_code":
        try:
            await s["client"].sign_in(phone=s["phone"], code=text, phone_code_hash=s["hash"])
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 أرسل رمز 2FA")
            return
        await show_main_menu(event)
        return

    if s.get("step") == "temp_2fa":
        await s["client"].sign_in(password=text)
        await show_main_menu(event)
        return

    # TRANSFER TARGET
    if s.get("step") == "transfer_target":
        s["target"] = text
        s["running"] = True
        key = f"me->{text}"
        progress = TRANSFER_DATA.get(key, {"last_id": 0, "sent": 0})
        s.update(progress)
        s["status"] = await event.respond("🚀 بدء النقل", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid))
        return

    # STEAL LINK
    if s.get("step") == "steal_link":
        s["source"] = text
        s["running"] = True
        s["status"] = await event.respond("⚡ بدء السرقة", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
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
        s["client"] = TelegramClient(StringSession(os.environ[d.decode()]), API_ID, API_HASH)
        await s["client"].start()
        await show_main_menu(event)
        return

    if d == b"temp":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل رقم الهاتف")
        return

    if d == b"clear_temp":
        for c in TEMP_SESSIONS.values():
            await c.log_out()
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم تسجيل خروج المؤقت")
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
        btns = [[Button.inline(f"{v['target']} ({v['sent']})", f"res_{i}".encode())]
                for i, v in enumerate(TRANSFER_DATA.values())]
        await event.respond("اختر للاستكمال:", buttons=btns)
        return

    if d.startswith(b"res_"):
        idx = int(d.decode().split("_")[1])
        key = list(TRANSFER_DATA.keys())[idx]
        s.update(TRANSFER_DATA[key])
        s["running"] = True
        s["status"] = await event.respond("▶️ استكمال", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid))
        return

    if d == b"steal":
        await event.respond(
            "⚡ اختر السرعة:",
            buttons=[
                [Button.inline("50", b"s50"), Button.inline("100", b"s100")],
                [Button.inline("150", b"s150"), Button.inline("200", b"s200")]
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
                await s["status"].edit(f"📊 {sent}/{total}")
            continue

        await c.send_file(dst, m.video, caption=clean_caption(m.text))
        sent += 1
        last_id = m.id

        TRANSFER_DATA[f"me->{s['target']}"] = {
            "target": s["target"],
            "last_id": last_id,
            "sent": sent
        }
        save_transfer()

        if sent % STATUS_UPDATE_EVERY == 0:
            await s["status"].edit(f"📊 {sent}/{total}")

    if batch:
        await c.send_file(dst, batch)
        sent += len(batch)

    await s["status"].edit(f"✅ انتهى\n📊 {sent}/{total}")

bot.run_until_disconnected()
