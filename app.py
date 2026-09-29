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
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

WHATSAPP_SUPPORT = "01326137501"

WEBSITE = "https://wizefftopup.com/"
TELEGRAM_CHANNEL = "https://t.me/wizefftopup"


# =========================================================
# TEMPORARY CONVERSATION MEMORY
# =========================================================

# Last 16 user/model messages per customer.
# Render restart/sleep can clear this memory.
chat_memory = defaultdict(
    lambda: deque(maxlen=16)
)


# =========================================================
# VERIFIED PRODUCT LINKS
# =========================================================

PRODUCT_LINKS = {
    "free_fire_bd":
        "https://wizefftopup.com/product/free-fire-topup-bd",

    "weekly_monthly":
        "https://wizefftopup.com/product/weekly-monthly",
}


# =========================================================
# CUSTOM TELEGRAM EMOJIS
# =========================================================

CUSTOM_EMOJIS = {
    # Natural conversation
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

    # Payment emojis
    "PAY1": "6204045134829458891",
    "PAY2": "6206444247726430845",
    "PAY3": "6206238411418768661",
    "PAY4": "6224054386734143462",
    "PAY5": "6224521357053401458",
    "PAY6": "6066835949222894322",
    "PAY7": "6224382307487193805",
}


# Fallback emoji displayed if custom emoji cannot animate/render.
EMOJI_FALLBACK = {
    "HELLO": "👋",
    "HAPPY": "😊",
    "THANKS": "🙏",
    "FUNNY": "😂",
    "THINKING": "🤔",
    "OKAY": "👌",
    "SORRY": "😔",
    "EXCITED": "✨",
    "HELP": "🛟",
    "TRUSTED": "🛡️",

    "POSITIVE": "✨",
    "PRICE": "💰",
    "LINK": "🔗",
    "WARNING": "⚠️",
    "SPAM": "🚫",
    "UPDATE": "📢",
    "LOOKING": "🔎",
    "COMING": "⏳",
    "IMPORTANT": "📌",
    "LOVE": "💙",
    "GUILD": "🎮",

    "PAY1": "💳",
    "PAY2": "💵",
    "PAY3": "💰",
    "PAY4": "💳",
    "PAY5": "💸",
    "PAY6": "🏦",
    "PAY7": "✅",
}


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are WizeFFTopUp's AI customer support assistant.

==================================================
LANGUAGE
==================================================

Always reply in the same language/style the customer uses.

Examples:
- Bengali -> Bengali
- Banglish -> natural Banglish/Bengali
- English -> English
- Hindi -> Hindi
- Other language -> same language when possible

If the customer changes language, naturally follow them.

==================================================
PERSONALITY
==================================================

Talk naturally, warmly and professionally.

You can have normal casual conversations.

Do not sound robotic.
Do not repeat the same greeting.
Do not start every reply with "Hello".
Do not give unnecessarily long answers.

Normal conversation should also look clean and pleasant.

Never pretend to be a real human.

If directly asked whether you are human, explain naturally that
you are WizeFFTopUp's AI support assistant.

==================================================
CUSTOM EMOJI MARKERS
==================================================

You may use ONLY these markers:

[[HELLO]]
[[HAPPY]]
[[THANKS]]
[[FUNNY]]
[[THINKING]]
[[OKAY]]
[[SORRY]]
[[EXCITED]]
[[HELP]]
[[TRUSTED]]

[[POSITIVE]]
[[PRICE]]
[[LINK]]
[[WARNING]]
[[SPAM]]
[[UPDATE]]
[[LOOKING]]
[[COMING]]
[[IMPORTANT]]
[[LOVE]]
[[GUILD]]

[[PAYMENT_ROW]]

The server converts these markers into Telegram custom emojis.

IMPORTANT:
- Do not print custom emoji numeric IDs.
- Do not invent new markers.
- Do not use an emoji in every reply.
- Usually use 0-2 markers per message.
- Keep emojis natural and non-spammy.
- Use [[POSITIVE]] naturally after something successful/positive.
- Use [[LOVE]] for friendly/caring positive conversation.
- Use [[PRICE]] for price-related replies.
- Use [[LINK]] immediately before an actual requested link.
- Use [[WARNING]] only for a genuine warning.
- Use [[SPAM]] only when excessive spam is actually relevant.
- Use [[LOOKING]] when helping locate/find something.
- Use [[COMING]] for verified coming-soon context only.
- Use [[IMPORTANT]] for genuinely important information.
- Use [[HELP]] when support/help is relevant.
- Use [[THANKS]] when naturally responding to thanks.
- Use [[HELLO]] for a natural greeting when appropriate.
- Use [[TRUSTED]] when a customer specifically asks whether
  WizeFFTopUp/website is trusted or asks for trust/reliability.
- Never use [[TRUSTED]] to make an unverified 100% guarantee.

PAYMENT:
- If a payment-system emoji line is genuinely useful,
  use [[PAYMENT_ROW]].
- [[PAYMENT_ROW]] becomes all configured payment custom emojis
  on ONE LINE.
- Do not repeatedly spam the payment row.

==================================================
SUPPORT
==================================================

Help with:
- WizeFFTopUp services
- Game top-ups
- Free Fire
- PUBG
- Digital products/subscriptions
- Orders
- Payments
- Pending top-ups
- Top-up not received
- Balance/payment issues
- General questions
- Normal conversation

==================================================
PRICE AND LINKS
==================================================

NEVER invent or guess prices.

IMPORTANT LINK RULE:

Do NOT automatically give a website/product link in normal replies.

Only provide a link when the customer:
- asks for a price/current price,
- explicitly asks for a link,
- asks where to find/buy/view a product,
- asks for the website/page,
- or clearly needs a page to complete their request.

When a verified link is supplied in INTERNAL INFORMATION,
you may use that exact link.

Never invent URLs.

For price questions:
- Do not invent the price.
- Explain that current prices can change.
- Give the verified product/page link when available.
- Put [[PRICE]] naturally in the reply.
- Put [[LINK]] immediately before the URL.

If only the main website is available, use it only when the
customer actually requested a link/price/page.

==================================================
WEBSITE UPDATES
==================================================

If the customer asks about:
- website updates,
- new updates,
- announcements,
- website news,
- official Telegram group/channel,

give the verified official Telegram link supplied internally.

Use [[UPDATE]] or [[IMPORTANT]] naturally.

Do not give the Telegram channel in unrelated conversations.

==================================================
TRUST QUESTIONS
==================================================

If the customer asks:
- "website trusted?"
- "WizeFFTopUp trusted?"
- "is it safe?"
- similar trust/reliability questions,

use [[TRUSTED]] naturally.

Do NOT invent guarantees, fake reviews, fake statistics,
fake certifications or claims you cannot verify.

You can point them to the official website/support channels
and explain that they should use official WizeFFTopUp contacts.

==================================================
TOP-UP / ORDER PROBLEMS
==================================================

If top-up is:
- pending,
- failed,
- delayed,
- not received,
- missing,

understand the problem from conversation context.

Ask for Order ID/reference when appropriate.

Ask the customer to verify the correct UID/player ID when relevant.

Processing delays can sometimes happen, but NEVER invent the cause.

NEVER claim:
- you checked an order when you did not,
- an order is completed when unverified,
- an order is pending when unverified,
- an order was cancelled when unverified,
- a refund happened when unverified.

Never promise an exact completion time unless verified.

If manual checking is needed, escalate to Human Support.

==================================================
PAYMENT / BALANCE
==================================================

If the customer says:
- money was deducted,
- payment completed but balance was not added,
- payment succeeded but order did not arrive,
- balance is missing,

ask whether payment shows completed.

Ask for a non-sensitive Order ID or transaction reference
when useful.

Never invent payment status.
Never invent refund status.
Never invent technical causes.

Never request:
- passwords
- OTP
- PIN
- CVV
- full card details
- API keys
- recovery codes
- secret credentials

If manual verification is needed, escalate to Human Support.

==================================================
UC / USDT
==================================================

Answer general questions only using verified information.

Never invent:
- UC buy/sell rates
- USDT minimum
- payment methods
- transaction limits
- exchange rates

If exact information is unavailable, use Human Support.

==================================================
NORMAL CONVERSATION
==================================================

Customers may chat normally.

Respond naturally and remember recent conversation context.

Examples:
- greetings
- thanks
- jokes
- casual questions
- follow-up questions

Do not turn every normal conversation into a sales message.

Do not add website links unless requested/relevant under the
LINK RULE.

Use custom emoji markers naturally and sparingly.

==================================================
HUMAN SUPPORT
==================================================

Official WizeFFTopUp WhatsApp Support:
01326137501

Human Support is needed when:
- customer asks for human/admin/agent,
- payment needs manual verification,
- top-up/order issue cannot be resolved,
- required business-specific information is unavailable,
- answering would require guessing,
- customer needs manual account/order checking.

When escalation is required:

1. Reply in the customer's language.
2. Explain that the issue needs/has been forwarded to Human Support.
3. Give WhatsApp Support: 01326137501
4. Do not ask for passwords/OTP/secrets.
5. Add this exact marker at the VERY END:

[HUMAN_SUPPORT]

Do not explain this marker.

==================================================
ACCURACY
==================================================

Never invent:
- prices
- product availability
- order status
- payment status
- refund status
- business policies
- payment methods
- UC rates
- USDT minimums
- completion times
- technical causes
- trust statistics
- reviews

When uncertain, be transparent and use Human Support if needed.
"""


# =========================================================
# TELEGRAM API
# =========================================================

def tg(method, payload=None):
    response = requests.post(
        f"{TG_API}/{method}",
        json=payload or {},
        timeout=30
    )

    response.raise_for_status()
    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(str(data))

    return data.get("result")


# =========================================================
# BUSINESS CONNECTION INFO
# =========================================================

def get_business_info(connection_id):
    result = tg(
        "getBusinessConnection",
        {
            "business_connection_id":
                connection_id
        }
    )

    owner_id = result["user"]["id"]

    owner_chat_id = result.get(
        "user_chat_id"
    )

    can_reply = result.get(
        "can_reply",
        True
    )

    return owner_id, owner_chat_id, can_reply


# =========================================================
# DETECT WHEN CUSTOMER ACTUALLY WANTS A LINK
# =========================================================

def wants_link(text):
    t = text.lower()

    keywords = [
        "link",
        "লিংক",
        "লিঙ্ক",
        "website",
        "ওয়েবসাইট",
        "ওয়েবসাইট",
        "site",
        "page",
        "পেজ",
        "price",
        "দাম",
        "কত টাকা",
        "koto",
        "koto taka",
        "price koto",
        "where can i buy",
        "where to buy",
        "where can i find",
        "where to find",
        "কোথায় পাব",
        "কোথায় পাব",
        "কোথা থেকে কিনব",
        "khujte",
        "kothay pabo",
        "koi pabo",
    ]

    return any(
        keyword in t
        for keyword in keywords
    )


# =========================================================
# WEBSITE UPDATE DETECTION
# =========================================================

def wants_update_channel(text):
    t = text.lower()

    keywords = [
        "website update",
        "site update",
        "new update",
        "updates",
        "announcement",
        "announcements",
        "telegram group",
        "telegram channel",
        "official telegram",
        "আপডেট",
        "টেলিগ্রাম গ্রুপ",
        "টেলিগ্রাম চ্যানেল",
        "update group",
    ]

    return any(
        keyword in t
        for keyword in keywords
    )


# =========================================================
# VERIFIED LINK SELECTION
# =========================================================

def get_verified_link(text):
    t = text.lower()

    if (
        "weekly" in t
        or "monthly" in t
        or "সাপ্তাহিক" in t
        or "মাসিক" in t
    ):
        return PRODUCT_LINKS[
            "weekly_monthly"
        ]

    if (
        "free fire" in t
        or "freefire" in t
        or "ff diamond" in t
        or "ff topup" in t
        or "ff top up" in t
        or "ফ্রি ফায়ার" in t
        or "ফ্রি ফায়ার" in t
    ):
        return PRODUCT_LINKS[
            "free_fire_bd"
        ]

    # Unknown product:
    # never invent a direct URL.
    return WEBSITE


# =========================================================
# INTERNAL INFORMATION
# =========================================================

def build_internal_info(message):
    info = []

    if wants_link(message):
        verified_link = get_verified_link(
            message
        )

        info.append(
            "Customer appears to be requesting a price/link/page."
        )

        info.append(
            "VERIFIED LINK YOU MAY PROVIDE: "
            + verified_link
        )

        info.append(
            "Do not invent any other URL."
        )

    else:
        info.append(
            "Customer did NOT clearly request a link. "
            "Do NOT include website/product URLs unless "
            "the reply genuinely requires one under the link rules."
        )

    if wants_update_channel(message):
        info.append(
            "VERIFIED OFFICIAL WIZEFFTOPUP TELEGRAM LINK: "
            + TELEGRAM_CHANNEL
        )

    return "\n".join(info)


# =========================================================
# BUILD GEMINI CONVERSATION
# =========================================================

def build_gemini_contents(
    chat_id,
    new_message
):
    contents = []

    for item in list(
        chat_memory[chat_id]
    ):
        contents.append({
            "role": item["role"],
            "parts": [
                {
                    "text": item["text"]
                }
            ]
        })

    internal_info = build_internal_info(
        new_message
    )

    enriched_message = (
        new_message
        + "\n\n"
        + "=== INTERNAL SERVER INFORMATION ===\n"
        + internal_info
        + "\n=== END INTERNAL INFORMATION ==="
    )

    contents.append({
        "role": "user",
        "parts": [
            {
                "text": enriched_message
            }
        ]
    })

    return contents


# =========================================================
# GEMINI
# =========================================================

def ask_gemini(
    chat_id,
    message
):
    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )

    headers = {
        "x-goog-api-key":
            GEMINI_KEY,

        "Content-Type":
            "application/json"
    }

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text":
                        SYSTEM_PROMPT
                }
            ]
        },

        "contents":
            build_gemini_contents(
                chat_id,
                message
            ),

        "generationConfig": {
            "temperature": 0.75,
            "maxOutputTokens": 800
        }
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=45
    )

    response.raise_for_status()
    data = response.json()

    candidates = data.get(
        "candidates",
        []
    )

    if not candidates:
        raise RuntimeError(
            "Gemini returned no response"
        )

    parts = (
        candidates[0]
        .get("content", {})
        .get("parts", [])
    )

    answer = "".join(
        part.get("text", "")
        for part in parts
    ).strip()

    if not answer:
        raise RuntimeError(
            "Gemini returned empty text"
        )

    return answer


# =========================================================
# CUSTOM EMOJI CONVERSION
# =========================================================

def custom_emoji_html(name):
    emoji_id = CUSTOM_EMOJIS.get(name)

    fallback = EMOJI_FALLBACK.get(
        name,
        "✨"
    )

    if not emoji_id:
        return fallback

    return (
        f'<tg-emoji emoji-id="{emoji_id}">'
        f'{fallback}'
        f'</tg-emoji>'
    )


def payment_row_html():
    payment_names = [
        "PAY1",
        "PAY2",
        "PAY3",
        "PAY4",
        "PAY5",
        "PAY6",
        "PAY7",
    ]

    return " ".join(
        custom_emoji_html(name)
        for name in payment_names
    )


def format_for_telegram(text):
    """
    Escapes Gemini text first, then replaces only our
    approved markers with Telegram custom emoji HTML.
    """

    safe_text = html.escape(
        text,
        quote=False
    )

    safe_text = safe_text.replace(
        "[[PAYMENT_ROW]]",
        payment_row_html()
    )

    for name in CUSTOM_EMOJIS:
        # Payment emojis are handled only
        # through PAYMENT_ROW.
        if name.startswith("PAY"):
            continue

        marker = f"[[{name}]]"

        safe_text = safe_text.replace(
            marker,
            custom_emoji_html(name)
        )

    # Remove any unknown marker Gemini might invent.
    safe_text = re.sub(
        r"\[\[[A-Z0-9_]+\]\]",
        "",
        safe_text
    )

    return safe_text.strip()


# =========================================================
# MEMORY
# =========================================================

def save_memory(
    chat_id,
    user_message,
    assistant_message
):
    # Store clean text without internal HUMAN marker.
    # Emoji markers may remain in memory, which helps Gemini
    # under
