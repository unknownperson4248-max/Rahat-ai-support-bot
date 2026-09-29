import os
import re
import html
import requests
from collections import defaultdict, deque
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini").strip()

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WEBSITE = "https://wizefftopup.com/"
TELEGRAM_CHANNEL = "https://t.me/wizefftopup"
WHATSAPP_SUPPORT = "01326137501"

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

# Render restart/sleep clears this temporary memory.
chat_memory = defaultdict(lambda: deque(maxlen=12))

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
- Reply in the customer's language.
- Understand Bangla, Banglish, English, and mixed casual conversation.
- Sound natural, friendly, concise, and context-aware.
- Do not drag an old product/topic into a new casual conversation.
- Never claim to be human.

KNOWN OFFICIAL INFO:
Website: {WEBSITE}
Telegram updates: {TELEGRAM_CHANNEL}
Human support WhatsApp: {WHATSAPP_SUPPORT}

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


def ask_openai(chat_id, user_text, allow_site=False, allow_updates=False):
    if not OPENAI_API_KEY:
        return f"AI service configuration missing. Human Support: {WHATSAPP_SUPPORT}"

    if strong_reset(user_text):
        chat_memory[chat_id].clear()

    rules = ["CURRENT RULES:"]
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
        "model": OPENAI_MODEL,
        "instructions": SYSTEM_PROMPT,
        "input": input_items,
        "max_output_tokens": 600,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload,
            timeout=45,
        )
        if response.status_code != 200:
            print("OpenAI error:", response.status_code, response.text[:1000])
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
        print("OpenAI exception:", repr(exc))
        return f"এই মুহূর্তে AI service-এ সমস্যা হচ্ছে। Human Support: {WHATSAPP_SUPPORT}"


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


def notify_owner(owner_chat_id, sender, user_text):
    if not owner_chat_id:
        return

    name = sender.get("first_name") or sender.get("username") or "Customer"
    username = sender.get("username")

    customer = html.escape(name)
    if username:
        customer += " (@" + html.escape(username) + ")"

    text = (
        f'{custom("HELP")} <b>Human Support Needed</b>\n\n'
        f'<blockquote>'
        f'<b>Customer:</b> {customer}\n'
        f'<b>Message:</b> {html.escape(user_text)}'
        f'</blockquote>\n\n'
        f'{custom("IMPORTANT")} <i>Please check this conversation manually.</i>'
    )

    send_message(owner_chat_id, text)


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

def handle_business_message(message):
    chat = message.get("chat") or {}

    if chat.get("type") != "private":
        return

    user_text = message.get("text")
    if not user_text:
        return

    sender = message.get("from") or {}
    if sender.get("is_bot"):
        return

    connection_id = message.get("business_connection_id")
    if not connection_id:
        return

    info = get_business_info(connection_id)
    if not info or not info.get("can_reply"):
        return

    # Never auto-answer the account owner's own outgoing messages.
    if sender.get("id") == info.get("owner_id"):
        return

    chat_id = chat.get("id")

    allow_updates = wants_updates(user_text)
    allow_site = wants_link(user_text) and not allow_updates

    # Payment question alone must NEVER trigger website link.
    if is_payment(user_text) and not wants_link(user_text):
        allow_site = False

    answer = ask_openai(
        chat_id=chat_id,
        user_text=user_text,
        allow_site=allow_site,
        allow_updates=allow_updates,
    )

    answer = enforce_links(
        answer,
        allow_site=allow_site,
        allow_updates=allow_updates,
    )

    human_needed = needs_human(answer, user_text)
    answer = strip_human_marker(answer)

    # Python, not Gemini, decides when an official link is appended.
    if allow_updates:
        if TELEGRAM_CHANNEL not in answer:
            answer += "\n\nOfficial Telegram Updates:\n" + TELEGRAM_CHANNEL
    elif allow_site:
        if WEBSITE not in answer and WEBSITE.rstrip("/") not in answer:
            answer += "\n\nOfficial Website:\n" + WEBSITE

    formatted = pretty_private_reply(user_text, answer)

    send_message(
        chat_id=chat_id,
        text=formatted,
        reply_to=message.get("message_id"),
        business_connection_id=connection_id,
    )

    chat_memory[chat_id].append({
        "role": "user",
        "text": user_text,
    })
    chat_memory[chat_id].append({
        "role": "model",
        "text": answer,
    })

    if human_needed:
        notify_owner(
            info.get("user_chat_id"),
            sender,
            user_text,
        )


# =========================================================
# ROUTES
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}

    # Normal bot group update.
    if update.get("message"):
        handle_group_message(update["message"])

    # Telegram Business private customer update.
    if update.get("business_message"):
        handle_business_message(update["business_message"])

    return jsonify({"ok": True})


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "bot": "Rahat Wize AI Support",
        "openai_model": OPENAI_MODEL,
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
