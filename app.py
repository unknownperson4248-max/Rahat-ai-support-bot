import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

SYSTEM_PROMPT = """
You are a helpful Telegram customer support assistant.

Rules:
- Reply politely and clearly.
- Reply in the same language the customer uses.
- If the customer writes Bangla/Banglish, reply naturally in Bangla/Banglish.
- Keep answers concise unless more detail is needed.
- Never invent prices, order status, delivery status, policies, or business information.
- If you do not know something specific about the business, say that a human support agent needs to confirm it.
- Never claim that an order, payment, or refund has been completed unless that information was actually provided.
"""


def telegram_api(method, payload=None):
    response = requests.post(
        f"{TELEGRAM_API}/{method}",
        json=payload or {},
        timeout=30
    )
    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(data)

    return data.get("result")


def get_business_owner(business_connection_id):
    result = telegram_api(
        "getBusinessConnection",
        {
            "business_connection_id": business_connection_id
        }
    )

    owner_id = result["user"]["id"]
    can_reply = result.get("can_reply", True)

    return owner_id, can_reply


def ask_gemini(message):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent"
    )

    headers = {
        "x-goog-api-key": GEMINI_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": SYSTEM_PROMPT
                }
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": message
                    }
                ]
            }
        ]
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=45
    )

    response.raise_for_status()
    data = response.json()

    parts = data["candidates"][0]["content"]["parts"]

    answer = "".join(
        part.get("text", "")
        for part in parts
    ).strip()

    return answer


def send_business_reply(
    chat_id,
    business_connection_id,
    message_id,
    text
):
    payload = {
        "business_connection_id": business_connection_id,
        "chat_id": chat_id,
        "text": text[:4000],
        "reply_parameters": {
            "message_id": message_id
        }
    }

    telegram_api("sendMessage", payload)


@app.route("/", methods=["GET"])
def home():
    return "Rahat AI Support Bot is running!"


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}

    message = update.get("business_message")

    if not message:
        return jsonify({"ok": True})

    text = message.get("text")
    connection_id = message.get("business_connection_id")
    chat = message.get("chat", {})
    sender = message.get("from", {})

    chat_id = chat.get("id")
    message_id = message.get("message_id")

    # Only answer private text messages.
    if (
        not text
        or not connection_id
        or not chat_id
        or not message_id
        or chat.get("type") != "private"
    ):
        return jsonify({"ok": True})

    try:
        owner_id, can_reply = get_business_owner(connection_id)

        # Do not answer messages sent by your own
        # Telegram business account.
        if sender.get("id") == owner_id:
            return jsonify({"ok": True})

        # Do not answer bot messages.
        if sender.get("is_bot"):
            return jsonify({"ok": True})

        if not can_reply:
            return jsonify({"ok": True})

        answer = ask_gemini(text)

        if answer:
            send_business_reply(
                chat_id,
                connection_id,
                message_id,
                answer
            )

    except Exception as error:
        print(
            "ERROR:",
            type(error).__name__,
            str(error)[:300]
        )

    return jsonify({"ok": True})


@app.route("/setup", methods=["GET"])
def setup_webhook():
    webhook_url = request.url_root.rstrip("/") + "/webhook"

    result = telegram_api(
        "setWebhook",
        {
            "url": webhook_url,
            "allowed_updates": [
                "business_connection",
                "business_message"
            ]
        }
    )

    return jsonify(
        {
            "ok": True,
            "webhook": webhook_url,
            "telegram_result": result
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
