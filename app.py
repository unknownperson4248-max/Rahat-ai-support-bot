import os
import re
import html
import requests
import json
import urllib.parse
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict, deque
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WEBSITE = "https://wizefftopup.com/"
TELEGRAM_CHANNEL = "https://t.me/wizefftopup"
WHATSAPP_SUPPORT = "01326137501"

# Your Telegram numeric user ID. Put this in Render Environment.
# Only this account can teach / manage the bot knowledge.
OWNER_TELEGRAM_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0") or 0)

# Persistent knowledge file. On Render Free, local files can reset after deploy/restart,
# so you can optionally attach a persistent disk and set KNOWLEDGE_FILE to its path.
KNOWLEDGE_FILE = os.environ.get("KNOWLEDGE_FILE", "rahat_knowledge.json").strip()
STATE_FILE = os.environ.get("STATE_FILE", "rahat_state.json").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "").strip()

# Group trigger requested by you.
GROUP_MENTION = "@rahatwize"

# =========================================================
# CUSTOM EMOJI IDS
# =========================================================

EMOJI = {
    "HELLO": "5208944462666937898",
    "HAPPY": "5240111691714301066",
    "THANKS": "5213309687037964344",
    "FUNNY": "5276337181055533947",
    "THINKING": "5314627136621922948",
    "OKAY": "5458485283790004353",
    "SORRY": "6093376514944929700",
    "EXCITED": "5362034620562940839",
    "HELP": "5372882114519772804",
    "TRUSTED": "6206053951163340256",

    "POSITIVE": "5215538285438311443",
    "PRICE": "6267068789146260253",
    "LINK": "6267115986541877538",
    "WARNING": "6267039884016358504",
    "SPAM": "6267262260243076354",
    "UPDATE": "6267119710278522544",
    "LOOKING": "6267186570034419608",
    "COMING": "6266866272848321043",
    "IMPORTANT": "6267172559851099903",
    "LOVE": "6267140231632262769",
    "GUILD": "5404881132703489171",

    # Exact group-offline custom emoji IDs supplied by you
    "ONLINE": "5213147006561692829",
    "SIGNATURE": "5927026418616636353",
}

PAYMENT_EMOJIS = [
    "6204045134829458891",
    "6206444247726430845",
    "6206238411418768661",
    "6224054386734143462",
    "6224521357053401458",
    "6066835949222894322",
    "6224382307487193805",
]

FALLBACK = {
    "HELLO": "👋",
    "HAPPY": "😊",
    "THANKS": "🙏",
    "FUNNY": "😂",
    "THINKING": "🤔",
    "OKAY": "👌",
    "SORRY": "😔",
    "EXCITED": "🤩",
    "HELP": "🛟",
    "TRUSTED": "🛡️",
    "POSITIVE": "✅",
    "PRICE": "💰",
    "LINK": "🔗",
    "WARNING": "⚠️",
    "SPAM": "🚫",
    "UPDATE": "📢",
    "LOOKING": "🔎",
    "COMING": "⏳",
    "IMPORTANT": "📌",
    "LOVE": "💜",
    "GUILD": "🤖",
    "ONLINE": "🟢",
    "SIGNATURE": "🤖",
}

# Customer conversation memory is intentionally short.
chat_memory = defaultdict(lambda: deque(maxlen=12))

# Owner training-chat memory, separate from customer chats.
owner_training_memory = defaultdict(lambda: deque(maxlen=20))


def supabase_headers(prefer=None):
    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_ready():
    return bool(SUPABASE_URL and SUPABASE_SECRET_KEY)


def db_rows(params=None):
    if not supabase_ready():
        return []
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/bot_memory",
            headers=supabase_headers(), params=params or {}, timeout=20,
        )
        if r.status_code == 200:
            return r.json()
        print("Supabase read error:", r.status_code, r.text[:500])
    except Exception as exc:
        print("Supabase read exception:", repr(exc))
    return []


def db_upsert(memory_type, memory_key, content):
    if not supabase_ready():
        return False
    try:
        payload = {"memory_type": memory_type, "memory_key": memory_key, "content": content}
        # First update an existing keyed row. This works even without a unique DB constraint.
        if memory_key:
            r = requests.patch(
                f"{SUPABASE_URL}/rest/v1/bot_memory",
                headers=supabase_headers("return=minimal"),
                params={"memory_type": f"eq.{memory_type}", "memory_key": f"eq.{memory_key}"},
                json={"content": content, "updated_at": "now()"}, timeout=20,
            )
            # PostgREST does not evaluate now() as SQL in JSON, retry without timestamp.
            if r.status_code >= 300:
                r = requests.patch(
                    f"{SUPABASE_URL}/rest/v1/bot_memory",
                    headers=supabase_headers("return=representation"),
                    params={"memory_type": f"eq.{memory_type}", "memory_key": f"eq.{memory_key}"},
                    json={"content": content}, timeout=20,
                )
            elif r.status_code in (200,204):
                # Need to know whether a row existed; fetch it.
                rows = db_rows({"select":"id", "memory_type":f"eq.{memory_type}", "memory_key":f"eq.{memory_key}", "limit":"1"})
                if rows:
                    return True
            if r.status_code in (200,204):
                rows = db_rows({"select":"id", "memory_type":f"eq.{memory_type}", "memory_key":f"eq.{memory_key}", "limit":"1"})
                if rows:
                    return True
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_memory",
            headers=supabase_headers("return=minimal"), json=payload, timeout=20,
        )
        if r.status_code in (200,201,204):
            return True
        print("Supabase write error:", r.status_code, r.text[:500])
    except Exception as exc:
        print("Supabase write exception:", repr(exc))
    return False


def db_add_knowledge(content):
    if not supabase_ready():
        return False
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_memory",
            headers=supabase_headers("return=minimal"),
            json={"memory_type":"knowledge", "memory_key":None, "content":content}, timeout=20,
        )
        return r.status_code in (200,201,204)
    except Exception as exc:
        print("Supabase knowledge write exception:", repr(exc))
        return False


def db_delete_id(row_id):
    if not supabase_ready(): return False
    try:
        r=requests.delete(f"{SUPABASE_URL}/rest/v1/bot_memory", headers=supabase_headers("return=minimal"), params={"id":f"eq.{row_id}"}, timeout=20)
        return r.status_code in (200,204)
    except Exception as exc:
        print("Supabase delete exception:", repr(exc)); return False


def load_knowledge():
    rows=db_rows({"select":"id,content,created_at", "memory_type":"eq.knowledge", "order":"id.asc", "limit":"100"})
    return [{"id":r.get("id"), "text":r.get("content","")} for r in rows]


def load_state():
    state={"auto_reply": True, "global_service_status":"available", "service_status":{}}
    for r in db_rows({"select":"memory_key,content", "memory_type":"eq.state"}):
        k=r.get("memory_key"); v=r.get("content","")
        if k=="auto_reply": state["auto_reply"] = v.lower()=="true"
        elif k=="global_service_status": state["global_service_status"] = v or "available"
    for r in db_rows({"select":"memory_key,content", "memory_type":"eq.service_status"}):
        if r.get("memory_key"): state["service_status"][r["memory_key"]]=r.get("content","")
    return state


def save_state_key(key, value):
    return db_upsert("state", key, str(value).lower() if isinstance(value,bool) else str(value))


def set_service_status(service, status):
    key=norm(service)
    if not key: return False
    bot_state.setdefault("service_status", {})[key]=status
    return db_upsert("service_status", key, status)


def set_global_service_status(status):
    bot_state["global_service_status"]=status
    return save_state_key("global_service_status", status)


knowledge_base = load_knowledge()
bot_state = load_state()


def knowledge_text():
    if not knowledge_base:
        return "(No owner-taught knowledge yet.)"
    return "\n".join(f"{i+1}. {x.get('text','').strip()}" for i,x in enumerate(knowledge_base[-80:]) if x.get('text'))


def service_status_text():
    default=bot_state.get("global_service_status","available")
    lines=[f"DEFAULT STATUS FOR ALL SERVICES: {default}"]
    exceptions=bot_state.get("service_status",{})
    if exceptions:
        lines.append("SPECIFIC SERVICE EXCEPTIONS (these override the default):")
        lines += [f"- {k}: {v}" for k,v in exceptions.items()]
    else:
        lines.append("No specific service exceptions.")
    return "\n".join(lines)



# =========================================================
# PERSISTENT CUSTOMER REGISTRY + SHORT-TERM MEMORY
# =========================================================

_last_cleanup_at = 0.0


def db_insert(memory_type, memory_key, content):
    if not supabase_ready():
        return False
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_memory",
            headers=supabase_headers("return=minimal"),
            json={"memory_type": memory_type, "memory_key": memory_key, "content": content},
            timeout=20,
        )
        return r.status_code in (200, 201, 204)
    except Exception as exc:
        print("Supabase insert exception:", repr(exc))
        return False


def save_customer(sender):
    """Permanent registry. Temporary chat cleanup never removes this row."""
    cid = sender.get("id")
    if not cid:
        return False
    rows = db_rows({"select":"content", "memory_type":"eq.customer", "memory_key":f"eq.{cid}", "limit":"1"})
    old = {}
    if rows:
        try: old = json.loads(rows[0].get("content") or "{}")
        except Exception: old = {}
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "id": cid,
        "first_name": sender.get("first_name") or old.get("first_name") or "",
        "last_name": sender.get("last_name") or old.get("last_name") or "",
        "username": sender.get("username") or "",
        "first_seen": old.get("first_seen") or now,
        "last_seen": now,
    }
    return db_upsert("customer", str(cid), json.dumps(data, ensure_ascii=False))


def list_customers():
    rows = db_rows({"select":"memory_key,content", "memory_type":"eq.customer", "order":"id.asc", "limit":"1000"})
    out=[]
    for r in rows:
        try:
            d=json.loads(r.get("content") or "{}")
        except Exception:
            d={}
        d["id"] = d.get("id") or r.get("memory_key")
        out.append(d)
    out.sort(key=lambda x: x.get("first_seen") or "")
    return out


def save_temp_message(customer_id, role, text):
    if not customer_id or not text:
        return
    payload={"role":role, "text":text[:4000], "ts":datetime.now(timezone.utc).isoformat()}
    db_insert("conversation", str(customer_id), json.dumps(payload, ensure_ascii=False))


def load_recent_messages(customer_id, limit=12):
    rows=db_rows({
        "select":"content,created_at", "memory_type":"eq.conversation",
        "memory_key":f"eq.{customer_id}", "order":"id.desc", "limit":str(limit)
    })
    items=[]
    for r in reversed(rows):
        try: d=json.loads(r.get("content") or "{}")
        except Exception: continue
        if d.get("text"):
            items.append(d)
    return items


def cleanup_old_conversations():
    """Delete only temporary conversation rows older than 4 days."""
    global _last_cleanup_at
    now=time.time()
    if now - _last_cleanup_at < 21600:  # at most once every 6 hours per process
        return
    _last_cleanup_at=now
    if not supabase_ready(): return
    cutoff=(datetime.now(timezone.utc)-timedelta(days=4)).isoformat()
    try:
        requests.delete(
            f"{SUPABASE_URL}/rest/v1/bot_memory",
            headers=supabase_headers("return=minimal"),
            params={"memory_type":"eq.conversation", "created_at":f"lt.{cutoff}"}, timeout=20,
        )
    except Exception as exc:
        print("Conversation cleanup exception:", repr(exc))


def detect_language(text, customer_id=None):
    t=(text or "").strip()
    # Numbers/order IDs do not reset language.
    if not re.search(r"[A-Za-z\u0980-\u09FF]", t):
        rows=db_rows({"select":"content", "memory_type":"eq.customer_language", "memory_key":f"eq.{customer_id}", "limit":"1"}) if customer_id else []
        return (rows[0].get("content") if rows else "") or "Banglish"
    if re.search(r"[\u0980-\u09FF]", t): lang="Bangla"
    else:
        low=norm(t)
        banglish_words=["ami","apni","tumi","vai","vaiya","ache","nai","koro","korbo","lagbe","diben","den","ki","koto","hobe","pabo","hoise","ase"]
        lang="Banglish" if sum(1 for w in banglish_words if re.search(rf"\b{re.escape(w)}\b", low))>=1 else "English"
    if customer_id:
        db_upsert("customer_language", str(customer_id), lang)
    return lang


def save_support_case(customer_id, reason, context):
    data={"reason":reason, "context":context[-3500:], "updated_at":datetime.now(timezone.utc).isoformat(), "status":"open"}
    return db_upsert("support_case", str(customer_id), json.dumps(data, ensure_ascii=False))


def support_case_recently_alerted(customer_id, seconds=1800):
    rows=db_rows({"select":"content", "memory_type":"eq.support_case", "memory_key":f"eq.{customer_id}", "limit":"1"})
    if not rows: return False
    try:
        d=json.loads(rows[0].get("content") or "{}")
        ts=datetime.fromisoformat(d.get("alerted_at", "").replace("Z","+00:00"))
        return (datetime.now(timezone.utc)-ts).total_seconds() < seconds
    except Exception:
        return False


def mark_support_alerted(customer_id, reason, context):
    data={"reason":reason, "context":context[-3500:], "updated_at":datetime.now(timezone.utc).isoformat(), "alerted_at":datetime.now(timezone.utc).isoformat(), "status":"open"}
    db_upsert("support_case", str(customer_id), json.dumps(data, ensure_ascii=False))

URL_RE = re.compile(r'https?://[^\s<>"\']+', re.I)

# =========================================================
# BASIC HELPERS
# =========================================================

def norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def has_any(text, words):
    t = norm(text)
    return any(word in t for word in words)


def tg_emoji(emoji_id, fallback="✨"):
    return (
        f'<tg-emoji emoji-id="{emoji_id}">'
        f'{html.escape(fallback)}'
        f'</tg-emoji>'
    )


def custom(name):
    return tg_emoji(EMOJI[name], FALLBACK.get(name, "✨"))


def payment_row():
    fallbacks = ["💳", "💰", "💸", "💵", "🏦", "💲", "💎"]
    return " ".join(
        tg_emoji(emoji_id, fallback)
        for emoji_id, fallback in zip(PAYMENT_EMOJIS, fallbacks)
    )


# =========================================================
# INTENT DETECTION
# =========================================================

def is_payment(text):
    return has_any(text, [
        "payment", "pay kor", "pay kora", "pay korte",
        "bkash", "bikash", "nagad", "rocket", "card",
        "পেমেন্ট", "বিকাশ", "নগদ", "রকেট",
    ])


def is_payment_problem(text):
    return has_any(text, [
        "payment pending", "pending payment", "money deducted",
        "taka kete", "taka katse", "টাকা কেটে",
        "payment failed", "paid but", "payment complete but",
        "balance add", "balance ashe nai", "topup pai nai",
        "top up pai nai", "order pending", "pending order",
        "পেমেন্ট পেন্ডিং",
    ])


def wants_updates(text):
    return has_any(text, [
        "website update", "update", "updates", "news",
        "announcement", "telegram channel", "channel",
        "আপডেট", "চ্যানেল",
    ])


def wants_link(text):
    t = norm(text)

    explicit = [
        "link dao", "link den", "link din", "link please",
        "give link", "send link", "website dao", "website den",
        "website link", "site link", "page dao", "page den",
        "product link", "direct link",
        "লিংক দাও", "লিংক দেন", "লিংক দিন",
        "ওয়েবসাইট দাও", "ওয়েবসাইট দাও",
        "ওয়েবসাইট লিংক", "ওয়েবসাইট লিংক",
        "পেজ দাও", "পেজ দেন",
    ]

    price = [
        "price", "price koto", "dam koto", "দাম কত",
        "কত টাকা", "rate koto",
    ]

    find = [
        "kothay pabo", "kothai pabo",
        "where can i buy", "where to buy", "where can i find",
        "কোথায় পাব", "কোথায় পাব", "কোথা থেকে কিনব",
    ]

    return any(x in t for x in explicit + price + find)


def strong_reset(text):
    t = norm(text)
    patterns = [
        r"^(hi+|hello|hey|yo)[.!? ]*$",
        r"^(salam|assalamualaikum|assalamu alaikum)[.!? ]*$",
        r"^(হাই|হ্যালো|সালাম|আসসালামু আলাইকুম)[।!? ]*$",
        r"^(kmn acho|kemon acho|kemon aso|kmn aso|how are you|how r u)[?!. ]*$",
        r"^(কেমন আছ|কেমন আছেন|কেমন আছো)[?।! ]*$",
    ]
    return any(re.match(pattern, t) for pattern in patterns)


# =========================================================
# HUMAN-SENSE CUSTOM EMOJI SELECTION
# =========================================================

def choose_emoji(user_text, answer=""):
    t = norm(user_text)
    both = t + " " + norm(answer)

    if has_any(t, ["trusted", "trust", "safe", "reliable", "ভরসা", "বিশ্বাস", "ট্রাস্টেড"]):
        return "TRUSTED"

    if has_any(t, ["kmn acho", "kemon acho", "how are you", "how r u", "কেমন আছ"]):
        return "HAPPY"

    if t in {"hi", "hii", "hiii", "hello", "hey", "হাই", "হ্যালো"} or has_any(t, ["assalam", "salam"]):
        return "HELLO"

    if has_any(t, ["thanks", "thank you", "tnx", "thx", "ধন্যবাদ"]):
        return "THANKS"

    if has_any(t, ["haha", "hehe", "lol", "😂", "🤣"]):
        return "FUNNY"

    if has_any(t, ["sorry", "sry", "সরি", "দুঃখিত"]):
        return "SORRY"

    if has_any(t, ["help", "support", "হেল্প", "সাহায্য"]):
        return "HELP"

    if has_any(t, ["price", "dam", "দাম", "rate", "কত টাকা"]):
        return "PRICE"

    if wants_updates(t):
        return "UPDATE"

    if wants_link(t):
        return "LINK"

    if has_any(t, ["find", "looking for", "kothay pabo", "kothai pabo", "কোথায় পাব", "কোথায় পাব"]):
        return "LOOKING"

    if has_any(t, ["coming soon", "kokhon asbe", "কবে আসবে", "কখন আসবে"]):
        return "COMING"

    if has_any(t, ["pending", "wait", "waiting", "পেন্ডিং", "অপেক্ষা"]):
        return "THINKING"

    if has_any(t, ["warning", "careful", "সতর্ক", "সাবধান"]):
        return "WARNING"

    if has_any(t, ["spam", "spamming"]):
        return "SPAM"

    if t in {"ok", "okay", "okk", "acha", "accha", "ওকে", "আচ্ছা", "ঠিক আছে"}:
        return "OKAY"

    if has_any(both, ["done", "solved", "success", "successful", "হয়ে গেছে", "হয়ে গেছে", "সমাধান"]):
        return "POSITIVE"

    if has_any(t, ["wow", "great", "awesome", "দারুণ", "ওয়াও", "ওয়াও"]):
        return "EXCITED"

    if len(t.split()) <= 10 and not is_payment(t):
        return "LOVE"

    return "HELP"


# =========================================================
# GEMINI
# =========================================================

SYSTEM_PROMPT = f"""
You are Rahat Wize AI Support for WizeFF TopUp.

LANGUAGE AND HUMAN SENSE:
- Match both language and writing style: English -> English, Bangla script -> Bangla script, Banglish (Bangla written in Latin letters) -> Banglish.
- If a Banglish sentence is too unclear to understand safely, do not guess; reply in clear Bangla and ask the customer to explain it again.
- Sound natural, friendly, concise, and context-aware.
- A plain Hi/Hello should get a simple greeting such as "Hi! How can I help you?" Do not force WizeFF, recharge, topup, links, or a service list into a simple greeting.
- If the customer asks whether Rahat/owner/vaiya is available, explain naturally that Rahat Wize is not on the line right now, they can tell you what help they need, and you are the WizeFF TopUp AI Assistant.
- Only bring up WizeFF products/services when the customer actually asks about a relevant service, order, payment, product, website, or support matter.
- Do not drag an old product/topic into a new casual conversation.
- Never claim to be human.

KNOWN OFFICIAL INFO:
Website: {WEBSITE}
Telegram updates: {TELEGRAM_CHANNEL}
Human support WhatsApp: {WHATSAPP_SUPPORT}

KNOWLEDGE PRIORITY:
- The owner can teach you business-specific facts, tone, examples, and reply preferences.
- Treat OWNER-TAUGHT KNOWLEDGE as the preferred source for business-specific guidance.
- For changing facts such as current price, availability, product list, or exact website content, do not guess. If current website data was not supplied to you, direct the customer to the official website when the current rules allow it.
- For ordinary greetings, casual chat, explanations, and general customer conversation, answer naturally using your own reasoning.
- Owner examples are guidance, not scripts that must be repeated word-for-word. Adapt them naturally to the customer's language and situation.
- Never let an old customer topic contaminate an unrelated new topic.

STRICT ACCURACY:
- Never invent prices, order/payment status, processing times, reviews, guarantees, product URLs, or payment methods.
- Payment custom emojis are decorative only. They do not prove a payment method is available.
- If asked what payment methods are available, say available options are shown at the payment/checkout step.
- Do not name payment methods unless the customer already supplied that method and asks about it.
- Never ask for password, OTP, PIN, CVV, recovery code, API key, or full card details.
- For payment/order problems requiring manual verification, ask for an order/reference ID when useful and append exactly [HUMAN_SUPPORT].

STRICT LINKS:
- Do not output a URL unless CURRENT RULES explicitly allow it.
- A payment/payment-method question alone never needs a website link.
- Never invent a direct product URL.
- Never invent a price.
- For updates/news/channel requests, use only the official Telegram updates link when allowed.

STYLE:
- Return clean plain text only.
- Do not use Markdown stars, # headings, HTML, or code blocks.
- The server applies Telegram custom emoji and styled formatting.
- Short casual replies should stay short.
- Detailed support replies may use short paragraphs.
"""


def ask_groq(chat_id, user_text, allow_site=False, allow_updates=False, extra_context=""):
    if not GROQ_API_KEY:
        return f"AI service configuration missing. Human Support: {WHATSAPP_SUPPORT}"

    if strong_reset(user_text):
        chat_memory[chat_id].clear()

    rules = ["CURRENT RULES:"]
    rules.append(
        "OWNER-TAUGHT KNOWLEDGE:\n" + knowledge_text()
    )
    rules.append("CURRENT SERVICE AVAILABILITY (owner supplied; use this when a customer asks availability):\n" + service_status_text())
    if extra_context:
        rules.append("CURRENT WEBSITE CONTEXT (use only if relevant; do not invent beyond it):\n" + extra_context[:8000])
    if allow_updates:
        rules.append(f"- Official Telegram updates link is allowed: {TELEGRAM_CHANNEL}")
    elif allow_site:
        rules.append(f"- Official website is allowed if useful: {WEBSITE}")
    else:
        rules.append("- No URL is allowed in this reply.")

    if is_payment(user_text):
        rules.append(
            "- This is payment-related. Do not name unverified payment methods. "
            "Do not add a website link unless explicitly allowed."
        )
    if is_payment_problem(user_text):
        rules.append("- If manual verification is needed, append [HUMAN_SUPPORT].")

    input_items = []
    for item in chat_memory[chat_id]:
        role = "assistant" if item["role"] == "model" else "user"
        input_items.append({"role": role, "content": item["text"]})

    input_items.append({
        "role": "user",
        "content": user_text + "\n\n" + "\n".join(rules),
    })

    payload = {
        "model": GROQ_MODEL,
        "instructions": SYSTEM_PROMPT,
        "input": input_items,
        "max_output_tokens": 600,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/responses",
            headers=headers,
            json=payload,
            timeout=45,
        )
        if response.status_code != 200:
            print("Groq error:", response.status_code, response.text[:1000])
            return f"এই মুহূর্তে AI response দিতে সমস্যা হচ্ছে। Human Support: {WHATSAPP_SUPPORT}"

        data = response.json()
        texts = []
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for part in item.get("content", []):
                if part.get("type") == "output_text" and part.get("text"):
                    texts.append(part["text"])
        answer = "".join(texts).strip()
        return answer or f"এই মুহূর্তে উত্তর তৈরি করা যাচ্ছে না। Human Support: {WHATSAPP_SUPPORT}"

    except Exception as exc:
        print("Groq exception:", repr(exc))
        return f"এই মুহূর্তে AI service-এ সমস্যা হচ্ছে। Human Support: {WHATSAPP_SUPPORT}"



# =========================================================
# WEBSITE CONTEXT
# =========================================================

def should_check_website(text):
    return has_any(text, [
        "service", "services", "product", "products", "available", "stock",
        "capcut", "chatgpt", "canva", "vpn", "guild", "topup", "uc", "diamond",
        "price", "package", "subscription", "website", "site",
        "সার্ভিস", "প্রোডাক্ট", "আছে", "স্টক", "দাম", "প্যাকেজ"
    ])

def fetch_website_context():
    try:
        r = requests.get(WEBSITE, timeout=12, headers={"User-Agent": "Mozilla/5.0 RahatWizeSupportBot/1.0"})
        if r.status_code != 200:
            return ""
        text = re.sub(r"(?is)<script.*?>.*?</script>|<style.*?>.*?</style>", " ", r.text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()[:12000]
    except Exception as exc:
        print("Website fetch error:", repr(exc))
        return ""

# =========================================================
# OWNER TRAINING CHAT
# =========================================================

TRAINING_SYSTEM = """
You are the private training assistant for Rahat Wize AI Support.
The owner is teaching you how the customer-support bot should think and reply.

Your job:
- Talk naturally with the owner.
- When the owner gives a durable business fact, reply preference, example, policy, or instruction,
  extract a short reusable lesson from it.
- Do not turn casual owner chat into a permanent rule.
- Do not invent business facts.
- If the owner states a CURRENT availability/status update, extract it separately. This works for ANY app/service/product, not only examples.
- If owner says ALL services/apps are available/unavailable, use service="__ALL__" and the status. A later specific service status overrides this global default.
- Return JSON only in this exact shape:
  {"reply":"natural reply to owner","remember":true_or_false,"memory":"short reusable lesson or empty string","service":"service name or empty string","status":"current status or empty string"}
- "memory" should preserve the owner's meaning, not copy unnecessary wording.
- If the owner corrects an earlier idea, the new lesson should clearly state the correction.
"""


def ask_training_groq(owner_id, text):
    if not GROQ_API_KEY:
        return "Groq API key missing.", False, ""

    history = list(owner_training_memory[owner_id])
    messages = [{"role": "system", "content": TRAINING_SYSTEM}]
    messages.append({
        "role": "system",
        "content": "Existing owner-taught knowledge:\\n" + knowledge_text(),
    })
    messages.extend(history)
    messages.append({"role": "user", "content": text})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.35,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=45,
        )
        if r.status_code != 200:
            print("Groq training error:", r.status_code, r.text[:1000])
            return "Training AI response দিতে সমস্যা হচ্ছে।", False, ""

        raw = r.json()["choices"][0]["message"]["content"]
        data = json.loads(raw)
        reply = str(data.get("reply") or "বুঝেছি।").strip()
        remember = bool(data.get("remember"))
        memory = str(data.get("memory") or "").strip()
        service = str(data.get("service") or "").strip()
        status = str(data.get("status") or "").strip()
        if service and status:
            if service == "__ALL__":
                set_global_service_status(status)
            else:
                set_service_status(service, status)

        owner_training_memory[owner_id].append({"role": "user", "content": text})
        owner_training_memory[owner_id].append({"role": "assistant", "content": reply})

        return reply, remember, memory
    except Exception as exc:
        print("Training exception:", repr(exc))
        return "Training AI response দিতে সমস্যা হচ্ছে।", False, ""


def add_owner_knowledge(memory):
    memory=(memory or "").strip()
    if not memory: return False
    for item in knowledge_base:
        if norm(item.get("text")) == norm(memory): return True
    if db_add_knowledge(memory):
        knowledge_base.append({"id":None,"text":memory})
        del knowledge_base[:-100]
        return True
    return False


def send_chunks(chat_id, text, reply_to=None, business_connection_id=None):
    chunks=[]
    current=""
    for line in text.splitlines(True):
        if len(current)+len(line)>3500 and current:
            chunks.append(current); current=""
        current+=line
    if current: chunks.append(current)
    for i, chunk in enumerate(chunks or [text]):
        send_message(chat_id, chunk, reply_to=reply_to if i==0 else None, business_connection_id=business_connection_id)


def help_text():
    return (
        f'{custom("HELP")} <b>Rahat AI Bot Help</b>\n\n'
        f'<b>👑 Admin Commands</b>\n'
        f'/on — Auto reply ON\n'
        f'/off — Auto reply OFF\n'
        f'/ai &lt;instruction&gt; — Groq AI use করুন\n'
        f'/customer — Customer list দেখুন\n'
        f'/help — Commands দেখুন\n\n'
        f'<b>👤 User Commands</b>\n'
        f'/ai &lt;question&gt; — AI-কে প্রশ্ন করুন\n'
        f'/help — Help দেখুন\n\n'
        f'{custom("IMPORTANT")} <i>Auto Reply ON থাকলে customer-এর normal message-এর উত্তর AI নিজে দেবে।</i>'
    )


def owner_training_reply(message):
    sender = message.get("from") or {}
    if not OWNER_TELEGRAM_ID or sender.get("id") != OWNER_TELEGRAM_ID:
        return False
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return False
    text = (message.get("text") or "").strip()
    if not text: return True
    cmd=norm(text).split()[0] if text else ""

    if cmd in {"/on","/online"}:
        bot_state["auto_reply"]=True; save_state_key("auto_reply", True)
        send_message(chat.get("id"), custom("POSITIVE")+' <b>Auto Reply ON</b> — customer message-e AI reply dibe.', reply_to=message.get("message_id")); return True
    if cmd in {"/off","/offline"}:
        bot_state["auto_reply"]=False; save_state_key("auto_reply", False)
        send_message(chat.get("id"), custom("WARNING")+' <b>Auto Reply OFF</b> — customer normal message-e AI silent thakbe.', reply_to=message.get("message_id")); return True
    if cmd=="/help":
        send_message(chat.get("id"), help_text(), reply_to=message.get("message_id")); return True
    if cmd=="/customer":
        customers=list_customers()
        if not customers:
            out=custom("LOOKING")+' <b>Customers</b>\n\nEkhono kono customer save hoyni.'
        else:
            lines=[f'{custom("LOOKING")} <b>WizeFF Customers — {len(customers)}</b>','']
            for i,c in enumerate(customers,1):
                name=((c.get("first_name") or "")+' '+(c.get("last_name") or "")).strip() or "Unknown"
                username='@'+c.get("username") if c.get("username") else 'No username'
                lines.append(f'{i}. <b>{html.escape(name)}</b> — {html.escape(username)}')
            lines += ['', f'<b>Total Customers:</b> {len(customers)}']
            out='\n'.join(lines)
        send_chunks(chat.get("id"), out, reply_to=message.get("message_id")); return True
    if cmd=="/knowledge":
        if not knowledge_base: out="এখনও কোনো permanent training knowledge save করা হয়নি।"
        else: out="Saved knowledge:\n\n"+"\n".join(f"{i+1}. {html.escape(x.get('text',''))}" for i,x in enumerate(knowledge_base[-30:]))
        send_chunks(chat.get("id"), out, reply_to=message.get("message_id")); return True
    if cmd=="/forgetlast":
        if knowledge_base and knowledge_base[-1].get("id"):
            removed=knowledge_base.pop(); db_delete_id(removed["id"]); out="শেষ training memory বাদ দিয়েছি:\n"+removed.get("text","")
        else: out="বাদ দেওয়ার মতো saved knowledge নেই।"
        send_message(chat.get("id"), html.escape(out), reply_to=message.get("message_id")); return True

    # /ai is optional in owner private chat; normal text also goes to the same Groq training brain.
    prompt=text[3:].strip() if cmd=="/ai" else text
    if not prompt: prompt="Amake help koro."
    reply, remember, memory = ask_training_groq(sender.get("id"), prompt)
    if remember and memory:
        if add_owner_knowledge(memory): reply += "\n\n🧠 Eta business memory-te save korlam."
        else: reply += "\n\n⚠️ Bujhechi, kintu Supabase-e save hoyni."
    formatted=f'{custom("THINKING")} <b>Rahat AI</b>\n\n<blockquote>{html.escape(reply)}</blockquote>'
    send_message(chat.get("id"), formatted, reply_to=message.get("message_id"))
    return True


# =========================================================
# OUTPUT CLEANING + STRICT LINK CONTROL
# =========================================================

def clean_ai_text(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "• ", text)
    return text.strip()


def enforce_links(answer, allow_site=False, allow_updates=False):
    answer = clean_ai_text(answer)

    if not allow_site and not allow_updates:
        answer = URL_RE.sub("", answer)

    elif allow_updates:
        def keep_update(match):
            found = match.group(0)
            clean = found.rstrip(".,)")
            return found if clean == TELEGRAM_CHANNEL else ""
        answer = URL_RE.sub(keep_update, answer)

    elif allow_site:
        def keep_site(match):
            found = match.group(0)
            clean = found.rstrip(".,)")
            return found if clean in {WEBSITE, WEBSITE.rstrip("/")} else ""
        answer = URL_RE.sub(keep_site, answer)

    answer = re.sub(r"[ \t]+\n", "\n", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    return answer.strip()


def needs_human(answer, user_text):
    return "[HUMAN_SUPPORT]" in answer or is_payment_problem(user_text)


def strip_human_marker(answer):
    return answer.replace("[HUMAN_SUPPORT]", "").strip()


# =========================================================
# TELEGRAM PRETTY FORMATTING
# =========================================================

def pretty_private_reply(user_text, answer):
    answer = clean_ai_text(answer)
    paragraphs = [
        p.strip()
        for p in re.split(r"\n\s*\n", answer)
        if p.strip()
    ]

    selected = choose_emoji(user_text, answer)
    icon = custom(selected)

    # Payment: exact seven payment emojis on ONE line.
    if is_payment(user_text):
        body = "\n\n".join(
            f"<blockquote>{html.escape(p)}</blockquote>"
            for p in paragraphs
        )
        return (
            f'{custom("IMPORTANT")} <b>Payment Info</b> {custom("POSITIVE")}\n'
            f'{payment_row()}\n\n'
            f'{body}'
        ).strip()

    # Short natural conversation: compact, styled, not a huge card.
    if len(answer) <= 240 and len(paragraphs) <= 2:
        if not paragraphs:
            return icon

        first = f"{icon} <b>{html.escape(paragraphs[0])}</b>"

        if len(paragraphs) == 2:
            return first + "\n\n" + f"<i>{html.escape(paragraphs[1])}</i>"

        return first

    # Detailed support: Telegram quote-box style.
    body = "\n\n".join(
        f"<blockquote>{html.escape(p)}</blockquote>"
        for p in paragraphs
    )

    return (
        f'{icon} <b>Rahat Wize AI Support</b>\n\n'
        f'{body}'
    ).strip()


def group_offline_reply(original_text):
    # Customer text first as requested.
    quoted = html.escape(original_text.strip())

    return (
        f"<blockquote>{quoted}</blockquote>\n\n"
        f'{custom("IMPORTANT")} <b>Rahat Wize বর্তমানে Offline</b> {custom("POSITIVE")}\n\n'
        f'{custom("LOVE")} <i>Personal message দিয়ে আপনার message রেখে দিন।</i>\n\n'
        f'{custom("ONLINE")} <u>Online-এ আসলে আপনার message-এর reply দেওয়া হবে।</u>\n\n'
        f'{custom("SIGNATURE")} <b><i>Message from Rahat Wize AI Support</i></b>'
    )


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_post(method, payload):
    try:
        response = requests.post(
            f"{TG_API}/{method}",
            json=payload,
            timeout=25,
        )
        data = response.json()

        if not data.get("ok"):
            print("Telegram error:", data)

        return data

    except Exception as exc:
        print("Telegram exception:", repr(exc))
        return {"ok": False}


def html_to_plain(text):
    text = re.sub(
        r'<tg-emoji[^>]*>(.*?)</tg-emoji>',
        r'\1',
        text,
        flags=re.S,
    )
    text = re.sub(r"</?(?:b|i|u|blockquote)>", "", text)
    return html.unescape(text)


def send_message(chat_id, text, reply_to=None, business_connection_id=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    if reply_to:
        payload["reply_parameters"] = {"message_id": reply_to}

    if business_connection_id:
        payload["business_connection_id"] = business_connection_id

    result = telegram_post("sendMessage", payload)

    if result.get("ok"):
        return result

    # Readable fallback if Telegram rejects a custom emoji/entity.
    fallback = {
        "chat_id": chat_id,
        "text": html_to_plain(text),
    }

    if reply_to:
        fallback["reply_parameters"] = {"message_id": reply_to}

    if business_connection_id:
        fallback["business_connection_id"] = business_connection_id

    return telegram_post("sendMessage", fallback)


def get_business_info(connection_id):
    try:
        response = requests.get(
            f"{TG_API}/getBusinessConnection",
            params={"business_connection_id": connection_id},
            timeout=20,
        )
        data = response.json()

        if not data.get("ok"):
            print("Business connection error:", data)
            return None

        result = data.get("result", {})
        user = result.get("user") or {}
        rights = result.get("rights") or {}

        return {
            "owner_id": user.get("id"),
            "user_chat_id": result.get("user_chat_id"),
            "can_reply": rights.get("can_reply", True),
        }

    except Exception as exc:
        print("getBusinessConnection exception:", repr(exc))
        return None


def notify_owner(owner_chat_id, sender, user_text, reason="Manual verification needed", context=""):
    if not owner_chat_id: return
    cid=sender.get("id")
    if support_case_recently_alerted(cid):
        save_support_case(cid, reason, context or user_text)
        return
    name=((sender.get("first_name") or "")+" "+(sender.get("last_name") or "")).strip() or sender.get("username") or "Customer"
    username=sender.get("username")
    recent=context or user_text
    text=(
        f'{custom("HELP")} <b>Human Support Needed</b>\n\n'
        f'<blockquote><b>Customer:</b> {html.escape(name)}\n'
        f'<b>Username:</b> {"@"+html.escape(username) if username else "Not available"}\n'
        f'<b>Customer ID:</b> {cid or "Not available"}\n'
        f'<b>Reason:</b> {html.escape(reason)}\n\n'
        f'<b>Relevant context:</b>\n{html.escape(recent[-2500:])}</blockquote>\n\n'
        f'{custom("IMPORTANT")} <i>Please check this conversation manually.</i>'
    )
    send_message(owner_chat_id, text)
    mark_support_alerted(cid, reason, recent)


# =========================================================
# GROUP HANDLER
# =========================================================

def handle_group_message(message):
    chat = message.get("chat") or {}

    if chat.get("type") not in {"group", "supergroup"}:
        return False

    sender = message.get("from") or {}
    if sender.get("is_bot"):
        return True

    text = message.get("text") or message.get("caption") or ""

    # Ignore every normal group message.
    # Reply only when the requested @Rahatwize mention is present.
    if GROUP_MENTION not in norm(text):
        return True

    send_message(
        chat_id=chat.get("id"),
        text=group_offline_reply(text),
        reply_to=message.get("message_id"),
    )
    return True


# =========================================================
# TELEGRAM BUSINESS PRIVATE HANDLER
# =========================================================

def run_ai_for_business(chat_id, connection_id, message, prompt, customer_id, reply_to=None, context_text=""):
    lang=detect_language(context_text or prompt, customer_id)
    recent=load_recent_messages(customer_id, 10)
    history="\n".join(f"{x.get('role')}: {x.get('text')}" for x in recent[-10:])
    extra=(f"CUSTOMER LANGUAGE LOCK: {lang}. Keep replying in this language/style, including after numeric-only messages.\n"
           f"RECENT CUSTOMER CONTEXT:\n{history}")
    if should_check_website(prompt):
        extra += "\nCURRENT WEBSITE TEXT:\n" + fetch_website_context()
    answer=ask_groq(f"customer:{customer_id}", prompt, allow_site=wants_link(prompt), allow_updates=wants_updates(prompt), extra_context=extra)
    answer=enforce_links(answer, allow_site=wants_link(prompt), allow_updates=wants_updates(prompt))
    human=needs_human(answer, prompt)
    answer=strip_human_marker(answer)
    send_message(chat_id, pretty_private_reply(context_text or prompt, answer), reply_to=reply_to, business_connection_id=connection_id)
    return answer, human


def handle_owner_business_command(message, info):
    sender=message.get("from") or {}
    if sender.get("id") != info.get("owner_id"): return False
    text=(message.get("text") or "").strip(); chat=message.get("chat") or {}; connection_id=message.get("business_connection_id")
    low=norm(text); cmd=low.split()[0] if low else ""
    if cmd in {"/on","/online"}:
        bot_state["auto_reply"]=True; save_state_key("auto_reply", True)
        send_message(chat.get("id"), custom("POSITIVE")+' <b>Auto Reply ON</b>', business_connection_id=connection_id); return True
    if cmd in {"/off","/offline"}:
        bot_state["auto_reply"]=False; save_state_key("auto_reply", False)
        send_message(chat.get("id"), custom("WARNING")+' <b>Auto Reply OFF</b>', business_connection_id=connection_id); return True
    if cmd=="/help":
        send_message(chat.get("id"), help_text(), business_connection_id=connection_id); return True
    if cmd=="/ai":
        replied=message.get("reply_to_message") or {}
        target=(replied.get("text") or replied.get("caption") or "").strip()
        instruction=text[3:].strip()
        if not instruction and target: instruction="Ei message-er jonno suitable response dao."
        if not instruction: instruction="Amake help koro."
        customer_id=chat.get("id")
        combined=(f"Customer message: {target}\nOwner instruction: {instruction}" if target else f"Owner instruction: {instruction}")
        run_ai_for_business(chat.get("id"), connection_id, message, combined, customer_id, reply_to=replied.get("message_id") if target else message.get("message_id"), context_text=target or instruction)
        return True
    # Owner normal/manual messages in customer chat MUST stay silent.
    return False


def handle_business_message(message):
    chat=message.get("chat") or {}
    if chat.get("type")!="private": return
    user_text=(message.get("text") or "").strip()
    if not user_text: return
    sender=message.get("from") or {}
    if sender.get("is_bot"): return
    connection_id=message.get("business_connection_id")
    if not connection_id: return
    info=get_business_info(connection_id)
    if not info or not info.get("can_reply"): return

    owner_id=info.get("owner_id") or OWNER_TELEGRAM_ID
    if sender.get("id")==owner_id:
        handle_owner_business_command(message, {**info, "owner_id":owner_id})
        return

    # Every genuine customer who messages is permanently registered.
    save_customer(sender)
    customer_id=sender.get("id") or chat.get("id")
    detect_language(user_text, customer_id)
    save_temp_message(customer_id, "user", user_text)

    cmd=norm(user_text).split()[0] if user_text else ""
    if cmd=="/help":
        send_message(chat.get("id"), help_text(), reply_to=message.get("message_id"), business_connection_id=connection_id); return

    # Customer /ai works even when normal auto reply is OFF.
    if cmd=="/ai":
        prompt=user_text[3:].strip() or "Amake help koro."
    else:
        if not bot_state.get("auto_reply", True): return
        prompt=user_text

    answer,human=run_ai_for_business(chat.get("id"), connection_id, message, prompt, customer_id, reply_to=message.get("message_id"), context_text=user_text)
    save_temp_message(customer_id, "assistant", answer)

    if human:
        recent=load_recent_messages(customer_id, 8)
        context="\n".join(f"{x.get('role')}: {x.get('text')}" for x in recent)
        reason="Order/payment issue needs manual verification" if is_payment_problem(user_text) else "AI requested human support"
        notify_owner(info.get("user_chat_id") or OWNER_TELEGRAM_ID, sender, user_text, reason=reason, context=context)


# =========================================================
# ROUTES
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    cleanup_old_conversations()
    update = request.get_json(silent=True) or {}

    # Normal bot private/group update.
    if update.get("message"):
        message = update["message"]
        # Your private chat with the bot becomes the training room.
        if not owner_training_reply(message):
            handle_group_message(message)

    # Telegram Business private customer update.
    if update.get("business_message"):
        handle_business_message(update["business_message"])
    if update.get("edited_business_message"):
        handle_business_message(update["edited_business_message"])

    return jsonify({"ok": True})


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "bot": "Rahat Wize AI Support",
        "groq_model": GROQ_MODEL,
    })


@app.route("/setup", methods=["GET"])
def setup():
    webhook_url = request.host_url.rstrip("/") + "/webhook"

    result = telegram_post(
        "setWebhook",
        {
            "url": webhook_url,
            "allowed_updates": [
                "message",
                "business_connection",
                "business_message",
                "edited_business_message",
            ],
        },
    )

    return jsonify({
        "ok": result.get("ok", False),
        "telegram_result": result,
        "webhook": webhook_url,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
