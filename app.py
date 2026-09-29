import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """
You are a helpful Telegram customer support assistant.

Rules:
- Reply politely and clearly.
- Reply in the same language the customer uses.
- If the customer writes Bangla/Banglish, reply naturally in Bangla/Banglish.
- Keep answers concise unless more detail is needed.
- Never invent prices, order status, delivery status, policies, or business information.
- If you do not know something specific about the business, say that a human support agent needs to confirm it.
- Never claim that an order/payment/refund has been completed unless that information was actually provided.
"""

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
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": message}]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def send_business_reply(chat_id, business_connection_id, text):
    payload = {
        "chat_id": chat_id,
        "business_connection_id": business_connection_id,
        "text": text[:4096]
    }

    response = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json=payload,
        timeout=30
    )
    response.raise_for_status()


@app.route("/", methods=["GET"])
def home():
    return "Rahat AI Support Bot is running!"


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}

    message = update.get("business_message")

    if not message:
        return jsonify({"ok": True})

    # Ignore messages sent by the business account/bot itself.
    sender = message.get("from", {})
    if sender.get("is_bot"):
        return jsonify({"ok": True})

    text = message.get("text")
    business_connection_id = message.get("business_connection_id")
    chat_id = message.get("chat", {}).get("id")

    if not text or not business_connection_id or not chat_id:
        return jsonify({"ok": True})

    try:
        answer = ask_gemini(text)
        send_business_reply(
            chat_id,
            business_connection_id,
            answer
        )
    except Exception as e:
        print("ERROR:", str(e))

    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
