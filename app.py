import os
import requests
from collections import defaultdict, deque
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Recent temporary conversation memory
chat_memory = defaultdict(lambda: deque(maxlen=12))

PRODUCT_LINKS = {
    "website":
        "https://wizefftopup.com/",

    "free_fire_bd":
        "https://wizefftopup.com/product/free-fire-topup-bd",

    "weekly_monthly":
        "https://wizefftopup.com/product/weekly-monthly",
}


SYSTEM_PROMPT = """
You are WizeFFTopUp's AI customer support assistant.

LANGUAGE:
- ALWAYS reply in the same language the customer uses.
- Bengali -> Bengali.
- Banglish -> natural Banglish/Bengali.
- English -> English.
- Hindi -> Hindi.
- For another language, reply in that language when possible.

STYLE:
- Talk naturally, warmly and professionally.
- You can have normal casual conversations.
- Do not sound robotic or repetitive.
- Do not greet again in every message.
- Keep replies reasonably short.
- Never pretend to be a real human.
- If asked, say you are WizeFFTopUp's AI support assistant.

SUPPORT:
Help with:
- WizeFFTopUp services.
- Game top-ups.
- Free Fire top-up support.
- PUBG top-up support.
- Digital products/subscriptions.
- Order questions.
- Payment questions.
- Pending top-ups.
- Top-up not received.
- Balance/payment issues.
- General questions.
- Normal friendly conversation.

PRICE:
- NEVER invent or guess a price.
- Prices may change.
- If asked for a price, provide the verified WizeFFTopUp
  product link supplied with the customer's message.
- Tell the customer to check that page for the current price.
- If no direct product link is available, provide:
  https://wizefftopup.com/
- Never invent a product URL.
- If they still cannot find the product, offer Human Support.

ORDER / TOP-UP PROBLEMS:
If a top-up is pending, failed, delayed or not received:
- Understand the problem using recent conversation context.
- Ask for Order ID/reference when appropriate.
- Ask them to verify their UID/player ID when relevant.
- Processing delays can sometimes happen.
- NEVER invent the cause.
- NEVER say you checked an order unless verified order
  information is actually available.
- NEVER invent order status.
- NEVER promise an exact completion time.
- Escalate unresolved cases to Human Support.

PAYMENT / BALANCE:
If money was deducted but balance/order was not added:
- Ask whether payment shows as completed.
- Ask for a non-sensitive transaction reference or Order ID
  when useful.
- Never claim payment was received unless verified.
- Never invent payment/refund status or technical causes.

NEVER request:
- Passwords.
- OTP codes.
- PINs.
- CVV.
- Full card details.
- API keys.
- Recovery codes.
- Secret credentials.

UC / USDT:
- Answer general questions only using verified information.
- Never invent UC buy/sell rates.
- Never invent minimum USDT amounts.
- Never invent payment methods.
- Never invent limits or exchange rates.
- If exact information is unavailable, use Human Support.

NORMAL CONVERSATION:
- Customers can talk normally.
- Reply naturally in their language.
- Use recent conversation context.
- Understand follow-up messages.
- If they say "thanks", reply naturally instead of restarting
  customer support.

HUMAN SUPPORT:
Official WizeFFTopUp WhatsApp Support:
01326137501

Human Support is needed when:
- Customer asks for a human/admin/agent.
- Manual payment verification is needed.
- An order/top-up problem cannot be resolved.
- Information needed is unavailable.
- Business-specific information would otherwise have to be guessed.
- Customer cannot find a product.

When Human Support is needed:
- Tell the customer in THEIR language that their issue has
  been forwarded to Human Support.
- Give WhatsApp Support: 01326137501.
- Tell them they can message that number on WhatsApp.
- Add this marker at the VERY END:

[HUMAN_SUPPORT]

The marker is internal. Do not explain it.

ACCURACY:
Never invent:
- Prices.
- Order status.
- Payment status.
- Refund status.
- Product availability.
- Business policies.
- Payment methods.
- UC rates.
- USDT minimums.
- Completion times.
- Technical causes.

If uncertain, say so and use Human Support.
"""


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


def get_business_info(connection_id):
    """
    Gets:
    - ID of the Telegram Business account owner
    - user_chat_id: private chat where the bot can contact
      the Business account owner
    - whether bot can reply
    """

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


def get_product_link(message):
    text = message.lower()

    if (
        "weekly" in text
        or "monthly" in text
        or "সাপ্তাহিক" in text
        or "মাসিক" in text
    ):
        return PRODUCT_LINKS["weekly_monthly"]

    if (
        "free fire" in text
        or "freefire" in text
        or "ff diamond" in text
        or "ff topup" in text
        or "ff top up" in text
        or "ফ্রি ফায়ার" in text
        or "ফ্রি ফায়ার" in text
    ):
        return PRODUCT_LINKS["free_fire_bd"]

    return PRODUCT_LINKS["website"]


def build_gemini_contents(chat_id, new_message):
    contents = []

    for item in list(chat_memory[chat_id]):
        contents.append({
            "role": item["role"],
            "parts": [
                {"text": item["text"]}
            ]
        })

    verified_link = get_product_link(
        new_message
    )

    enriched_message = (
        new_message
        + "\n\n"
        + "INTERNAL VERIFIED INFORMATION:\n"
        + "Relevant verified WizeFFTopUp link: "
        + verified_link
        + "\nUse this link when relevant. "
          "Never invent another product URL."
    )

    contents.append({
        "role": "user",
        "parts": [
            {"text": enriched_message}
        ]
    })

    return contents


def ask_gemini(chat_id, message):
    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )

    headers = {
        "x-goog-api-key": GEMINI_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "system_instruction": {
            "parts": [
                {"text": SYSTEM_PROMPT}
            ]
        },

        "contents": build_gemini_contents(
            chat_id,
            message
        ),

        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 700
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


def save_memory(
    chat_id,
    user_message,
    assistant_message
):
    chat_memory[chat_id].append({
        "role": "user",
        "text": user_message
    })

    chat_memory[chat_id].append({
        "role": "model",
        "text": assistant_message
    })


def send_business_reply(
    chat_id,
    connection_id,
    message_id,
    text
):
    tg(
        "sendMessage",
        {
            "business_connection_id":
                connection_id,

            "chat_id":
                chat_id,

            "text":
                text[:4000],

            "reply_parameters": {
                "message_id":
                    message_id
            }
        }
    )


def notify_owner(
    owner_chat_id,
    customer_name,
    customer_username,
    customer_id,
    customer_message
):
    """
    Sends the Human Support alert to the private chat
    associated with the connected Business account.
    """

    if not owner_chat_id:
        return

    username_text = ""

    if customer_username:
        username_text = (
            f"\nUsername: @{customer_username}"
        )

    notification = (
        "🔔 HUMAN SUPPORT NEEDED\n\n"
        f"Customer: {customer_name}"
        f"{username_text}\n"
        f"Telegram ID: {customer_id}\n\n"
        "Customer message:\n"
        f"{customer_message[:2000]}\n\n"
        "Please open the customer conversation "
        "and reply manually.\n\n"
        "WizeFFTopUp WhatsApp: 01326137501"
    )

    # IMPORTANT:
    # No business_connection_id here.
    # This is a normal private notification from the bot
    # to the connected Business account owner.
    tg(
        "sendMessage",
        {
            "chat_id":
                owner_chat_id,

            "text":
                notification
        }
    )


@app.route("/", methods=["GET"])
def home():
    return "WizeFFTopUp AI Support is running!"


@app.route("/webhook", methods=["POST"])
def webhook():
    update = (
        request.get_json(
            silent=True
        )
        or {}
    )

    message = update.get(
        "business_message"
    )

    if not message:
        return jsonify({"ok": True})

    text = message.get("text")

    connection_id = message.get(
        "business_connection_id"
    )

    chat = message.get(
        "chat",
        {}
    )

    sender = message.get(
        "from",
        {}
    )

    chat_id = chat.get("id")
    message_id = message.get("message_id")

    if (
        not text
        or not connection_id
        or not chat_id
        or not message_id
        or chat.get("type") != "private"
    ):
        return jsonify({"ok": True})

    try:
        (
            owner_id,
            owner_chat_id,
            can_reply
        ) = get_business_info(
            connection_id
        )

        # Ignore your own outgoing messages.
        if sender.get("id") == owner_id:
            return jsonify({"ok": True})

        # Ignore bot messages.
        if sender.get("is_bot"):
            return jsonify({"ok": True})

        if not can_reply:
            return jsonify({"ok": True})

        answer = ask_gemini(
            chat_id,
            text
        )

        needs_human = (
            "[HUMAN_SUPPORT]" in answer
        )

        clean_answer = (
            answer.replace(
                "[HUMAN_SUPPORT]",
                ""
            ).strip()
        )

        if clean_answer:
            send_business_reply(
                chat_id,
                connection_id,
                message_id,
                clean_answer
            )

            save_memory(
                chat_id,
                text,
                clean_answer
            )

        if needs_human:
            first_name = sender.get(
                "first_name",
                ""
            )

            last_name = sender.get(
                "last_name",
                ""
            )

            customer_name = (
                f"{first_name} {last_name}"
                .strip()
                or "Unknown"
            )

            notify_owner(
                owner_chat_id,
                customer_name,
                sender.get("username"),
                sender.get("id", "Unknown"),
                text
            )

    except Exception as error:
        print(
            "ERROR:",
            type(error).__name__,
            str(error)[:500]
        )

    return jsonify({"ok": True})


@app.route("/setup", methods=["GET"])
def setup():
    webhook_url = (
        request.url_root.rstrip("/")
        + "/webhook"
    )

    result = tg(
        "setWebhook",
        {
            "url":
                webhook_url,

            "allowed_updates": [
                "business_connection",
                "business_message"
            ]
        }
    )

    return jsonify({
        "ok": True,
        "telegram_result": result,
        "webhook": webhook_url
    })


if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
