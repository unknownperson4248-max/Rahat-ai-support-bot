import os
import re
import html
import requests
from collections import defaultdict, deque
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================================================
# ENVIRONMENT
# =========================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WEBSITE = "https://wizefftopup.com/"
TELEGRAM_CHANNEL = "https://t.me/wizefftopup"
WHATSAPP_SUPPORT = "01326137501"


# =========================================================
# CUSTOM TELEGRAM EMOJIS
# =========================================================

EMOJI = {
    # Normal / human conversation
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

    # Special
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


# =========================================================
# MEMORY
# =========================================================

chat_memory = defaultdict(lambda: deque(maxlen=14))


# =========================================================
# TEXT DETECTION
# =========================================================

def normalize(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def contains_any(text, words):
    t = normalize(text)
    return any(word in t for word in words)


def is_payment_related(text):
    return contains_any(text, [
        "payment",
        "pay ",
        "pay?",
        "payment method",
        "pay korbo",
        "pay kora",
        "pay korte",
        "bkash",
        "bikash",
        "nagad",
        "rocket",
        "bank",
        "card",
        "টাকা",
        "পেমেন্ট",
        "বিকাশ",
        "নগদ",
        "রকেট",
        "পেমেন্ট মেথড",
    ])


def is_payment_problem(text):
    return contains_any(text, [
        "payment pending",
        "pending payment",
        "money deducted",
        "money cut",
        "taka kete",
        "taka katse",
        "টাকা কেটে",
        "পেমেন্ট পেন্ডিং",
        "payment failed",
        "paid but",
        "payment complete but",
        "balance add",
        "balance ashe nai",
        "topup pai nai",
        "top up pai nai",
        "order pending",
        "pending order",
    ])


def wants_link(text):
    """
    STRICT:
    Payment/payment method alone NEVER counts as link request.
    """

    t = normalize(text)

    explicit_link_words = [
        "link dao",
        "link den",
        "link din",
        "link please",
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
    ]

    price_words = [
        "price",
        "dam koto",
        "দাম কত",
        "price koto",
        "কত টাকা",
        "rate koto",
    ]

    find_words = [
        "kothay pabo",
        "kothai pabo",
        "where can i buy",
        "where to buy",
        "where can i find",
        "কোথায় পাব",
        "কোথায় পাব",
        "কোথা থেকে কিনব",
    ]

    return (
        any(x in t for x in explicit_link_words)
        or any(x in t for x in price_words)
        or any(x in t for x in find_words)
    )


def wants_updates(text):
    return contains_any(text, [
        "update",
        "updates",
        "news",
        "announcement",
        "channel",
        "telegram channel",
        "website update",
        "নতুন আপডেট",
        "আপডেট",
        "চ্যানেল",
    ])


def is_strong_conversation_reset(text):
    """
    Strong casual messages start a fresh conversational context,
    so old TikTok/FF/product topics do not randomly come back.
    """
    t = normalize(text)

    patterns = [
        r"^(hi|hii+|hello|hey|yo)[.!? ]*$",
        r"^(salam|assalamualaikum|assalamu alaikum)[.!? ]*$",
        r"^(হাই|হ্যালো|সালাম|আসসালামু আলাইকুম)[।!? ]*$",
        r"^(kmn acho|kemon acho|kemon aso|kmn aso)[?!. ]*$",
        r"^(how are you|how r u)[?!. ]*$",
        r"^(কেমন আছ|কেমন আছেন|কেমন আছো)[?।! ]*$",
    ]

    return any(re.match(p, t) for p in patterns)


# =========================================================
# HUMAN-SENSE EMOJI SELECTION
# =========================================================

def choose_context_emoji(user_text, answer=""):
    t = normalize(user_text)
    a = normalize(answer)

    # Trust / safety question
    if contains_any(t, [
        "trusted", "trust", "safe", "reliable",
        "বিশ্বাস", "ভরসা", "ট্রাস্টেড",
        "website trusted", "site trusted"
    ]):
        return "TRUSTED"

    # Greeting
    if contains_any(t, [
        "hello", "hii", "hi ", "hey", "salam",
        "assalam", "হাই", "হ্যালো", "সালাম"
    ]) or t in ["hi", "hii", "hello", "hey"]:
        return "HELLO"

    # How are you
    if contains_any(t, [
        "kmn acho", "kemon acho", "how are you",
        "how r u", "কেমন আছ", "কেমন আছেন"
    ]):
        return "HAPPY"

    # Thanks
    if contains_any(t, [
        "thanks", "thank you", "tnx", "thx",
        "ধন্যবাদ", "শুকরিয়া"
    ]):
        return "THANKS"

    # Funny
    if contains_any(t, [
        "haha", "hehe", "lol", "lmao", "😂", "🤣"
    ]):
        return "FUNNY"

    # Sorry
    if contains_any(t, [
        "sorry", "sry", "দুঃখিত", "সরি"
    ]):
        return "SORRY"

    # Help
    if contains_any(t, [
        "help", "support", "সাহায্য", "হেল্প"
    ]):
        return "HELP"

    # Price
    if contains_any(t, [
        "price", "dam", "দাম", "rate", "কত টাকা"
    ]):
        return "PRICE"

    # Explicit link
    if wants_link(t):
        return "LINK"

    # Updates
    if wants_updates(t):
        return "UPDATE"

    # Looking / finding
    if contains_any(t, [
        "find", "looking for", "kothay pabo",
        "kothai pabo", "খুঁজছি", "কোথায় পাব", "কোথায় পাব"
    ]):
        return "LOOKING"

    # Coming soon
    if contains_any(t, [
        "coming soon", "kokhon asbe", "কবে আসবে",
        "কখন আসবে"
    ]):
        return "COMING"

    # Waiting / pending
    if contains_any(t, [
        "pending", "wait", "waiting",
        "অপেক্ষা", "পেন্ডিং"
    ]):
        return "THINKING"

    # Warning
    if contains_any(t, [
        "warning", "careful", "সতর্ক", "সাবধান"
    ]):
        return "WARNING"

    # Spam
    if contains_any(t, [
        "spam", "spamming", "বার বার মেসেজ"
    ]):
        return "SPAM"

    # Okay / confirmation
    if t in [
        "ok", "okay", "okk", "acha", "accha",
        "ঠিক আছে", "আচ্ছা", "ওকে"
    ]:
        return "OKAY"

    # Positive result
    if contains_any(t + " " + a, [
        "done", "solved", "success", "successful",
        "complete", "হয়ে গেছে", "হয়ে গেছে",
        "সমাধান হয়েছে", "সমাধান হয়েছে"
    ]):
        return "POSITIVE"

    # Excited mood
    if contains_any(t, [
        "wow", "great", "awesome", "nicee",
        "দারুণ", "ওয়াও", "ওয়াও"
    ]):
        return "EXCITED"

    # Friendly default for casual conversation
    if len(t.split()) <= 8 and not is_payment_related(t):
        return "LOVE"

    return None


# =========================================================
# GEMINI SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = f"""
You are the AI customer-support and conversational assistant for WizeFF TopUp.

Your personality:
- Friendly, calm, intelligent and natural.
- Talk like a helpful human assistant, not a robotic FAQ.
- Understand Bangla, Banglish, English and other languages.
- Always reply in the customer's language.
- Banglish can be answered naturally in Bangla or Banglish depending on context.
- Keep simple questions concise.
- For support questions, use clear structured sections when useful.
- Do not repeat the same sentence again and again.
- Do not drag an old product/topic into a new casual conversation.
- If the customer changes topic, follow the new topic naturally.
- Never claim you are a human.

IMPORTANT FACTS:
Website: {WEBSITE}
Official Telegram updates: {TELEGRAM_CHANNEL}
Human support WhatsApp: {WHATSAPP_SUPPORT}

STRICT LINK RULE:
- DO NOT put any website/product/channel link in ordinary replies.
- DO NOT give the website just because the customer asks about payment.
- "Payment method ki?" does NOT require a website link.
- "How can I pay?" does NOT require a website link.
- Only include a URL when the application explicitly tells you that links are allowed.
- Never invent product URLs.
- Never invent pages or paths on the website.

PRICE RULE:
- Never invent or guess a product price.
- Prices may change.
- If the application says a link is allowed for a price request, direct the customer to the provided official website.
- Do not make up a price.

PAYMENT RULE:
- Do not invent payment methods that are not known from the conversation.
- If asked generally about payment methods and exact methods are not known, explain briefly that available payment options are shown during the payment/checkout process.
- DO NOT add the website URL unless links are explicitly allowed.
- For payment/order problems, do not invent payment status, transaction status, cause, or completion time.
- Ask for an order/reference ID when manual verification is needed.
- Never ask for password, OTP, PIN, CVV, API key, recovery code, or full card details.
- If manual verification is needed, add exactly:
[HUMAN_SUPPORT]

TRUST RULE:
- If asked whether the website is trusted/safe, answer carefully.
- Do not invent reviews, certifications, guarantees or statistics.
- Do not promise "100% safe".
- Explain only what is known.

FORMATTING:
- Write clean Telegram-friendly text.
- For a detailed support reply, use a short heading and small sections.
- Do not make every casual reply into a huge card.
- Do not use Markdown formatting such as ** or ##.
- The server will apply Telegram styling and custom emoji itself.

NORMAL CONVERSATION:
- You may have normal friendly conversations.
- If someone asks "Kmn acho?", simply answer that naturally.
- Do not suddenly mention TikTok, Free Fire, payment, or another old topic unless the customer refers to it.
"""


# =========================================================
# GEMINI
# =========================================================

def ask_gemini(chat_id, user_text, allow_link=False, update_link=False):
    if not GEMINI_KEY:
        return "AI service configuration missing."

    # Strong topic reset removes stale context
    if is_strong_conversation_reset(user_text):
        chat_memory[chat_id].clear()

    contents = []

    for item in chat_memory[chat_id]:
        contents.append({
            "role": item["role"],
            "parts": [{"text": item["text"]}]
        })

    extra_instruction = "\n\nCURRENT REQUEST RULES:\n"

    if allow_link:
        extra_instruction += (
            f"- A link is allowed for THIS request.\n"
            f"- Use only this official website if needed: {WEBSITE}\n"
            "- Do not invent a deeper product URL.\n"
        )
    else:
        extra_instruction += (
            "- NO website or product URL is allowed in this reply.\n"
            "- Do not output any URL.\n"
        )

    if update_link:
        extra_instruction += (
            f"- The customer is asking for updates/news/channel.\n"
            f"- You may use this official Telegram link: {TELEGRAM_CHANNEL}\n"
        )

    if is_payment_related(user_text):
        extra_instruction += (
            "- This is payment-related.\n"
            "- Do NOT automatically provide the website.\n"
            "- Do not invent payment methods.\n"
            "- Answer the actual payment question directly.\n"
        )

    contents.append({
        "role": "user",
        "parts": [{
            "text": user_text + extra_instruction
        }]
    })

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
    )

    payload = {
        "system_instruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.65,
            "topP": 0.9,
            "maxOutputTokens": 700
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=35)

        if response.status_code != 200:
            print("Gemini error:", response.status_code, response.text)
            return (
                "দুঃখিত, এই মুহূর্তে AI response দিতে একটু সমস্যা হচ্ছে। "
                f"প্রয়োজনে WhatsApp Support: {WHATSAPP_SUPPORT}"
            )

        data = response.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return (
                "দুঃখিত, এই মুহূর্তে উত্তর তৈরি করা যাচ্ছে না। "
                f"প্রয়োজনে WhatsApp Support: {WHATSAPP_SUPPORT}"
            )

        parts = candidates[0].get("content", {}).get("parts", [])

        answer = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict)
        ).strip()

        if not answer:
            return (
                "দুঃখিত, এই মুহূর্তে উত্তর তৈরি করা যাচ্ছে না। "
                f"প্রয়োজনে WhatsApp Support: {WHATSAPP_SUPPORT}"
            )

        return answer

    except Exception as e:
        print("Gemini request exception:", e)

        return (
            "দুঃখিত, এই মুহূর্তে AI service-এ সমস্যা হচ্ছে। "
            f"প্রয়োজনে WhatsApp Support: {WHATSAPP_SUPPORT}"
        )


# =========================================================
# URL GUARDRAIL
# =========================================================

URL_RE = re.compile(
    r'https?://[^\s<>"\']+',
    flags=re.IGNORECASE
)


def enforce_link_rules(answer, allow_link, update_link):
    """
    Even if Gemini ignores instructions, Python enforces link rules.
    """

    if allow_link or update_link:
        return answer

    # Remove every accidental URL
    answer = URL_RE.sub("", answer)

    # Clean spaces left behind
    answer = re.sub(r"[ \t]+\n", "\n", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)

    return answer.strip()


# =========================================================
# HUMAN SUPPORT
# =========================================================

def needs_human_support(answer, user_text):
    if "[HUMAN_SUPPORT]" in answer:
        return True

    if is_payment_problem(user_text):
        return True

    return False


def remove_human_marker(answer):
    return answer.replace("[HUMAN_SUPPORT]", "").strip()


# =========================================================
# TELEGRAM CUSTOM EMOJI
# =========================================================

def tg_emoji(emoji_id, fallback):
    return (
        f'<tg-emoji emoji-id="{emoji_id}">'
        f'{html.escape(fallback)}'
        f'</tg-emoji>'
    )


def payment_row():
    fallbacks = ["💳", "💰", "💸", "💵", "🏦", "💲", "💎"]

    result = []

    for emoji_id, fallback in zip(PAYMENT_EMOJIS, fallbacks):
        result.append(tg_emoji(emoji_id, fallback))

    # ALL 7 PAYMENT EMOJIS ON ONE LINE
    return " ".join(result)


# =========================================================
# BEAUTIFUL TELEGRAM TEXT STYLE
# =========================================================

def clean_ai_formatting(text):
    # Gemini sometimes outputs Markdown despite instruction.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def split_into_sections(text):
    """
    Preserve paragraphs generated by Gemini.
    """
    text = clean_ai_formatting(text)

    paragraphs = [
        p.strip()
        for p in re.split(r"\n\s*\n", text)
        if p.strip()
    ]

    return paragraphs


def build_pretty_reply(user_text, answer):
    """
    Produces:
    custom emoji + bold first section
    blockquote-style support sections
    payment custom emoji row
    """

    answer = clean_ai_formatting(answer)

    marker = choose_context_emoji(user_text, answer)

    emoji_html = ""

    fallback_map = {
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
    }

    if marker and marker in EMOJI:
        emoji_html = tg_emoji(
            EMOJI[marker],
            fallback_map.get(marker, "✨")
        )

    safe_answer = html.escape(answer)

    paragraphs = [
        p.strip()
        for p in re.split(r"\n\s*\n", safe_answer)
        if p.strip()
    ]

    # --------------------------------------------
    # NORMAL SHORT CONVERSATION
    # --------------------------------------------

    if (
        len(answer) <= 220
        and not is_payment_related(user_text)
        and not is_payment_problem(user_text)
    ):
        if not paragraphs:
            return emoji_html

        first = paragraphs[0]

        result = ""

        if emoji_html:
            result += emoji_html + " "

        result += f"<b>{first}</b>"

        if len(paragraphs) > 1:
            for p in paragraphs[1:]:
                result += f"\n\n{p}"

        return result.strip()

    # --------------------------------------------
    # PAYMENT / SUPPORT CARD STYLE
    # --------------------------------------------

    result_parts = []

    if is_payment_related(user_text):
        header = (
            f'{tg_emoji(EMOJI["IMPORTANT"], "📌")} '
            f'<b>Payment Support</b>'
        )

        result_parts.append(header)

        # User explicitly requested all 7 in ONE LINE
        result_parts.append(payment_row())

    elif emoji_html:
        result_parts.append(
            f"{emoji_html} <b>WizeFF Support</b>"
        )

    # First paragraph
    if paragraphs:
        first = paragraphs[0]

        result_parts.append(
            f"<blockquote>{first}</blockquote>"
        )

        # Remaining paragraphs become clean sections
        for paragraph in paragraphs[1:]:
            result_parts.append(
                f"<blockquote>{paragraph}</blockquote>"
            )

    return "\n\n".join(result_parts).strip()


# =========================================================
# TELEGRAM SEND
# =========================================================

def telegram_post(method, payload):
    try:
        response = requests.post(
            f"{TG_API}/{method}",
            json=payload,
 
