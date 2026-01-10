import asyncio
import os
import re
import json
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

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

SAVED_CHANNELS = load_channels()  # uid -> list of channels

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}
TEMP_SESSIONS = {}  # لتخزين الجلسات المؤقتة بالذاكرة

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

async def send_channel_buttons(uid, event):
    channels = SAVED_CHANNELS.get(str(uid), [])[-7:]  # آخر 7 قنوات
    buttons = []
    for ch in channels:
        title = ch.get("title") or "القناة بدون اسم"
        photo = getattr(ch.get("photo", None), "file_id", None)
        # نستخدم الصورة إذا متوفرة
        text = f"📺 {title}"
        buttons.append([Button.inline(text, f"resume_{ch['id']}")])
    buttons.append([Button.inline("⚠️ إعادة ضبط الروابط", "reset_channels")])
    buttons.append([Button.inline("🔄 تحديث القائمة", "refresh_channels")])
    await event.respond("📢 اختر القناة للاستكمال:", buttons=buttons)

async def send_accounts_buttons(uid, event):
    accounts = await get_accounts()
    buttons = [[Button.inline(f"📸 {name}", key)] for key, name in accounts]
    buttons.append([Button.inline("🔄 تحديث الحسابات", "refresh_accounts")])
    await event.respond("📋 اختر الحساب للعملية:", buttons=buttons)

# ================= القائمة الرئيسية =================
async def main_menu(event):
    uid = event.sender_id
    # رسالة ترحيبية حيوية وعصرية
    await event.respond(
        "اهلا وسهلا في بوتي المتواضع 🥺\n"
        "اختر طريقة الدخول لبدء العمل 👇",
        buttons=[
            [Button.inline("🛡 الحسابات المحمية (Session)", "protected_session")],
            [Button.inline("📲 دخول مؤقت بالرقم والكود", "temporary_login")],
            [Button.inline("🧹 تسجيل خروج جميع الحسابات المؤقتة", "clear_temp_sessions")]
        ]
    )

# ================= START =================
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    uid = event.sender_id
    if uid not in AUTHORIZED_USERS:
        await event.respond("🔐 أرسل رمز الدخول")
        return
    await main_menu(event)
    state[uid] = {"step": "main_menu"}

# ================= CALLBACK =================
@bot.on(events.CallbackQuery)
async def cb(event):
    await event.answer()
    uid = event.sender_id
    s = state.get(uid)
    if not s:
        return
    data = event.data.decode()

    # ==== القائمة الرئيسية ====
    if data == "protected_session":
        await send_accounts_buttons(uid, event)
        s["step"] = "choose_account"
        return

    if data == "temporary_login":
        s["step"] = "temporary_login"
        await event.respond("📲 أرسل رقم الهاتف (مثال: +9647701234567)")
        return

    if data == "clear_temp_sessions":
        for cl in TEMP_SESSIONS.values():
            await cl.log_out()
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم تسجيل خروج جميع الحسابات المؤقتة بنجاح")
        return

    if data == "start_new":
        await start(event)
        return

    # ==== زر اختيار الحسابات ====
    if s.get("step") == "choose_account":
        session_str = os.environ.get(data)
        if not session_str:
            await event.respond("❌ Session غير موجود")
            return
        s["client"] = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await s["client"].start()
        s["step"] = "mode"
        await choose_mode(event)
        return

# ================= FLOW للحسابات المؤقتة =================
@bot.on(events.NewMessage)
async def flow_temp(event):
    uid = event.sender_id
    txt = (event.text or "").strip()
    s = state.get(uid)
    if not s:
        return

    if s.get("step") == "temporary_login":
        phone = txt
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = client
        await client.start(phone=phone)
        s["client"] = client
        s["step"] = "mode"
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
async def run(s):
    c = s["client"]
    uid = str(s.get("uid",0))
    src = await c.get_entity("me") if s["mode"]=="transfer" else await c.get_entity(s["link"])
    dst = await c.get_entity(s["link"]) if s["mode"]=="transfer" else await c.get_entity("me")

    msgs = [m async for m in c.iter_messages(src) if m.video]
    s["total"] = len(msgs)

    batch = []
    for idx, m in enumerate(msgs[s.get("sent",0):], start=s.get("sent",0)):
        if not s["running"]:
            break

        if s["mode"]=="steal" and s.get("send_mode")=="protected":
            path = await c.download_media(m.video)
            batch.append(path)
        else:
            batch.append(m.video)

        if len(batch) == 10:
            await c.send_file(dst, batch)
            if s["mode"]=="steal" and s.get("send_mode")=="protected":
                for f in batch: os.remove(f)
            s["sent"] += len(batch)
            batch.clear()

        if s["mode"]=="transfer" or (s["mode"]=="steal" and s.get("send_mode")!="protected"):
            await c.send_file(dst, m.video, caption=clean_caption(m.text))
            s["sent"] += 1

        await s["status"].edit(
            f"📊 التقدم\n🎞️ {s['sent']} / {s['total']}",
            buttons=[[Button.inline("⏸️ إيقاف مؤقت", b"pause")],
                     [Button.inline("⏹️ إيقاف نهائي", b"stop")]]
        )
        await asyncio.sleep(s.get("delay",10))

    # حفظ القناة المستعملة
    if s["mode"]=="transfer":
        ch_record = {"id": dst.id, "username": getattr(dst,'username',None), "title": getattr(dst,'title',None), "last_index": s["sent"]}
        if uid not in SAVED_CHANNELS:
            SAVED_CHANNELS[uid] = []
        for i, ch in enumerate(SAVED_CHANNELS[uid]):
            if ch["id"]==dst.id:
                SAVED_CHANNELS[uid][i] = ch_record
                break
        else:
            SAVED_CHANNELS[uid].append(ch_record)
        save_channels(SAVED_CHANNELS)

    await s["status"].edit(
        f"✅ تم إنهاء العملية\n📊 إجمالي المقاطع المرسلة: {s['sent']}",
        buttons=[[Button.inline("▶️ بدء جديد / Start", "start_new")]]
    )

bot.run_until_disconnected()