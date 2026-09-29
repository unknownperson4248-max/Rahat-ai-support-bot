import os
import re
import html
import requests
from collections import defaultdict, deque
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WEBSITE = "https://wizefftopup.com/"
TELEGRAM_CHANNEL = "https://t.me/wizefftopup"
WHATSAPP_SUPPORT = "01326137501"

# Group-এ এই username mention করলে offline reply যাবে
GROUP_MENTION = "@rahatwize"


# =========================================================
# CUSTOM EMOJI
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

    # Group offline message
    "ONLINE": "5213147006561692829",
    "SIGNATURE": "5927026418616636353",
}


# =========================================================
# PAYMENT CUSTOM EMOJIS — ALL ON ONE LINE
# =========================================================

PAYMENT_EMOJIS = [
    "6204045134829458891",
    "6206444247726430845",
    "6206238411418768661",
    "6224054386734143462",
    "6224521357053401458",
    "6066835949222894322",
    "6224382307487193805",
]


# =========================================================
# MEMORY
# =========================================================

chat_memory = defaultdict(lambda: deque(maxlen=12))

URL_RE = re.compile(
    r'https?://[^\s<>"\']+',
    re.I
)


# =========================================================
# HELPERS
# =========================================================

def norm(text):
    return re.sub(
        r"\s+",
        " ",
        (text or "").lower()
    ).strip()


def has_any(text, words):
    t = norm(text)
    return any(word in t for word in words)


def tg_emoji(emoji_id, fallback="✨"):
    return (
        f'<tg-emoji emoji-id="{emoji_id}">'
        f'{html.escape(fallback)}'
        f'</tg-emoji>'
    )


def payment_row():
    fallback = [
        "💳",
        "💰",
        "💸",
        "💵",
        "🏦",
        "💲",
        "💎"
    ]

    return " ".join(
        tg_emoji(emoji_id, fb)
        for emoji_id, fb in zip(
            PAYMENT_EMOJIS,
            fallback
        )
    )


# =========================================================
# PAYMENT DETECTION
# =========================================================

def is_payment(text):
    return has_any(text, [
        "payment",
        "pay kor",
        "pay kora",
        "pay korte",
        "bkash",
        "bikash",
        "nagad",
        "rocket",
        "card",
        "পেমেন্ট",
        "বিকাশ",
        "নগদ",
        "রকেট",
    ])


def is_payment_problem(text):
    problem = has_any(text, [
        "pending",
        "money deducted",
        "taka kete",
        "taka katse",
        "টাকা কেটে",
        "failed",
        "paid but",
        "balance add",
        "balance ashe nai",
        "topup pai nai",
        "top up pai nai",
        "order pending",
        "পেন্ডিং",
    ])

    return problem and is_payment(
        text + " payment"
    )


# =========================================================
# LINK DETECTION
# =========================================================

def wants_updates(text):
    return has_any(text, [
        "update",
        "updates",
        "news",
        "announcement",
        "channel",
        "telegram channel",
        "আপডেট",
        "চ্যানেল",
    ])


def wants_link(text):
    t = norm(text)

    explicit = [
        "link dao",
        "link den",
        "link din",
        "give link",
        "send link",
        "website dao",
        "website den",
        "website link",
        "site link",
        "page dao",
        "page den",
        "product link",
        "direct link",
        "লিংক দাও",
        "লিংক দেন",
        "লিংক দিন",
        "ওয়েবসাইট দাও",
        "ওয়েবসাইট দাও",
        "ওয়েবসাইট লিংক",
        "ওয়েবসাইট লিংক",
        "পেজ দাও",
        "পেজ দেন",
    ]

    price = [
        "price",
        "price koto",
        "dam koto",
        "দাম কত",
        "কত টাকা",
        "rate koto",
    ]

    find = [
        "kothay pabo",
        "kothai pabo",
        "where can i buy",
        "where to buy",
        "where can i find",
        "কোথায় পাব",
        "কোথায় পাব",
        "কোথা থেকে কিনব",
    ]

    return any(
        x in t
        for x in explicit + price + find
    )


# =========================================================
# CONVERSATION RESET
# =========================================================

def strong_reset(text):
    t = norm(text)

    patterns = [
        r"^(hi+|hello|hey|yo)[.!? ]*$",
        r"^(salam|assalamualaikum|assalamu alaikum)[.!? ]*$",
        r"^(হাই|হ্যালো|সালাম|আসসালামু আলাইকুম)[।!? ]*$",
        r"^(kmn acho|kemon acho|kemon aso|kmn aso|how are you|how r u)[?!. ]*$",
        r"^(কেমন আছ|কেমন আছেন|কেমন আছো)[?।! ]*$",
    ]

    return any(
        re.match(pattern, t)
        for pattern in patterns
    )


# =========================================================
# HUMAN-SENSE EMOJI SELECTION
# =========================================================

def choose_emoji(user_text, answer=""):
    t = norm(user_text)
    both = t + " " + norm(answer)

    if has_any(t, [
        "trusted",
        "trust",
        "safe",
        "reliable",
        "ভরসা",
        "বিশ্বাস",
        "ট্রাস্টেড",
    ]):
        return "TRUSTED"

    if has_any(t, [
        "kmn acho",
        "kemon acho",
        "how are you",
        "how r u",
        "কেমন আছ",
    ]):
        return "HAPPY"

    if (
        t in {
            "hi",
            "hii",
            "hiii",
            "hello",
            "hey",
            "হাই",
            "হ্যালো",
        }
        or has_any(t, [
            "assalam",
            "salam",
        ])
    ):
        return "HELLO"

    if has_any(t, [
        "thanks",
        "thank you",
        "tnx",
        "thx",
        "ধন্যবাদ",
    ]):
        return "THANKS"

    if has_any(t, [
        "haha",
        "hehe",
        "lol",
        "😂",
        "🤣",
    ]):
        return "FUNNY"

    if has_any(t, [
        "sorry",
        "sry",
        "সরি",
        "দুঃখিত",
    ]):
        return "SORRY"

    if has_any(t, [
        "help",
        "support",
        "হেল্প",
        "সাহায্য",
    ]):
        return "HELP"

    if has_any(t, [
        "price",
        "dam",
        "দাম",
        "rate",
        "কত টাকা",
    ]):
        return "PRICE"

    if wants_updates(t):
        return "UPDATE"

    if wants_link(t):
        return "LINK"

    if has_any(t, [
        "find",
        "looking for",
        "kothay pabo",
        "kothai pabo",
        "কোথায় পাব",
        "কোথায় পাব",
    ]):
        return "LOOKING"

    if has_any(t, [
        "coming soon",
        "kokhon asbe",
        "কবে আসবে",
        "কখন আসবে",
    ]):
        return "COMING"

    if has_any(t, [
        "pending",
        "wait",
        "waiting",
        "পেন্ডিং",
        "অপেক্ষা",
    ]):
        return "THINKING"

    if has_any(t, [
        "warning",
        "careful",
        "সতর্ক",
        "সাবধান",
    ]):
        return "WARNING"

    if has_any(t, [
        "spam",
        "spamming",
    ]):
        return "SPAM"

    if t in {
        "ok",
        "okay",
        "okk",
        "acha",
        "accha",
        "ওকে",
        "আচ্ছা",
        "ঠিক আছে",
    }:
        return "OKAY"

    if has_any(both, [
        "done",
        "solved",
        "success",
        "successful",
        "হয়ে গেছে",
        "হয়ে গেছে",
        "সমাধান",
    ]):
        return "POSITIVE"

    if has_any(t, [
        "wow",
        "great",
        "awesome",
        "দারুণ",
        "ওয়াও",
        "ওয়াও",
    ]):
        return "EXCITED"

    if (
        len(t.split()) <= 10
        and not is_payment(t)
    ):
        return "LOVE"

    return "HELP"


# =========================================================
# GEMINI SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = f"""
You are Rahat Wize AI Support for WizeFF TopUp.

LANGUAGE AND HUMAN SENSE:
- Reply in the customer's language.
- Understand Bangla, Banglish, English, and mixed casual conversation.
- Sound natural, friendly, concise and context-aware.
- Do not drag an old product/topic into a new casual conversation.
- Never claim to be human.

KNOWN OFFICIAL INFO:
Website: {WEBSITE}
Telegram updates: {TELEGRAM_CHANNEL}
Human support WhatsApp: {WHATSAPP_SUPPORT}

STRICT ACCURACY:
- Never invent prices, order/payment status, processing times, reviews, guarantees, product URLs, or payment methods.
- Payment custom emojis are decorative only.
- They DO NOT prove that a particular payment method is available.
- If asked what payment methods are available, say the available options are shown at the payment/checkout step.
- Do not name payment methods unless the customer already supplied the name and is asking about it.
- Never ask for password, OTP, PIN, CVV, recovery code, API key, or full card details.
- For payment/order problems requiring verification, ask for a safe order/reference ID if useful and append exactly [HUMAN_SUPPORT].

STRICT LINKS:
- Do not output any URL unless CURRENT RULES explicitly allow it.
- A payment/payment-method question alone NEVER needs a website link.
- Never invent a direct product URL.
- For a price request, never invent a price.
- When CURRENT RULES allow the official site, direct the customer there.
- For updates/news/channel requests, use only the official Telegram updates link when CURRENT RULES allow it.

STYLE:
- Return clean plain text only.
- No Markdown stars, # headings, HTML, or code blocks.
- The server applies Telegram custom emoji, bold/italic and blockquote styling.
- Short casual replies should stay short.
- Detailed support replies may use short paragraphs.
"""


# =========================================================
# GEMINI REQUEST
# =========================================================

def ask_gemini(
    chat_id,
    user_text,
    allow_site=False,
    allow_updates=False
):
    if not GEMINI_KEY:
        return (
            "AI service configuration missing. "
            "Please contact human support."
        )

    if strong_reset(user_text):
        chat_memory[chat_id].clear()

    contents = []

    for item in chat_memory[chat_id]:
        contents.append({
            "role": item["role"],
            "parts": [{
                "text": item["text"]
            }]
        })

    rules = [
        "CURRENT RULES:"
    ]

    if allow_updates:
        rules.append(
            "- Official Telegram updates link "
            f"is allowed: {TELEGRAM_CHANNEL}"
        )

    elif allow_site:
        rules.append(
            "- Official website is allowed "
            f"if useful: {WEBSITE}"
        )

    else:
        rules.append(
            "- No URL is allowed in this reply."
        )

    if is_payment(user_text):
        rules.append(
            "- This is payment-related. "
            "Do not name unverified payment methods "
            "and do not add a website link "
            "unless explicitly allowed."
        )

    if is_payment_problem(user_text):
        rules.append(
            "- If manual verification is needed, "
            "append [HUMAN_SUPPORT]."
        )

    contents.append({
        "role": "user",
        "parts": [{
            "text": (
                user_text
                + "\n\n"
                + "\n".join(rules)
            )
        }]
    })

    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
        f"?key={GEMINI_KEY}"
    )

    payload = {
        "system_instruction": {
            "parts": [{
                "text": SYSTEM_PROMPT
            }]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.
