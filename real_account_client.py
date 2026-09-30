"""Rahat AI real-account Telegram client for Termux.

Reuses the existing support brain in app.py (Groq + Supabase + business rules)
while Telethon handles transport through the authenticated real account.
Secrets stay in environment variables; the local .session file stays ignored.
"""
import asyncio
import os

from telethon import TelegramClient, events

import app as brain

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.environ.get("TELEGRAM_SESSION", "rahat_ai")
OWNER_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0") or 0)

client = TelegramClient(SESSION, API_ID, API_HASH)


def sender_dict(sender):
    return {
        "id": getattr(sender, "id", 0),
        "first_name": getattr(sender, "first_name", "") or "",
        "last_name": getattr(sender, "last_name", "") or "",
        "username": getattr(sender, "username", "") or "",
        "is_bot": bool(getattr(sender, "bot", False)),
    }


@client.on(events.NewMessage(incoming=True))
async def on_message(event):
    if not event.is_private or not event.raw_text:
        return

    sender = await event.get_sender()
    if not sender or getattr(sender, "bot", False):
        return

    text = event.raw_text.strip()
    if not text:
        return

    sender_data = sender_dict(sender)
    customer_id = sender_data["id"]
    key = brain.scope_key(customer_id, event.chat_id)

    print(f"RAHAT_AI_INCOMING peer={event.chat_id} message_id={event.id}")

    try:
        # Keep the same customer registry, language lock, business knowledge,
        # safety rules and short-term conversation memory used by the old app.
        await asyncio.to_thread(brain.save_customer, sender_data)
        state = await asyncio.to_thread(brain.load_state)
        if not state.get("auto_reply", True):
            return

        answer = await asyncio.to_thread(
            brain.reply_for,
            key,
            text,
            sender_data,
            OWNER_ID or None,
            False,
            "",
        )

        await asyncio.to_thread(brain.save_temp_message, key, "user", text)
        if not answer:
            print(f"RAHAT_AI_SILENT peer={event.chat_id} message_id={event.id}")
            return

        # Real-account transport uses plain text; the old Bot API HTML/custom
        # emoji wrapper is intentionally not reused here.
        answer = brain.clean_ai_text(answer).strip()
        if not answer:
            return

        await event.reply(answer)
        await asyncio.to_thread(brain.save_temp_message, key, "assistant", answer)
        print(f"RAHAT_AI_REPLIED peer={event.chat_id} message_id={event.id}")

    except brain.StorageError:
        print(f"RAHAT_AI_STORAGE_UNAVAILABLE peer={event.chat_id}")
    except Exception as exc:
        # Do not print message text or secret-bearing exception details.
        print(f"RAHAT_AI_ERROR peer={event.chat_id} type={type(exc).__name__}")


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Local Telegram session is not authorized")

    me = await client.get_me()
    if OWNER_ID and me.id != OWNER_ID:
        raise RuntimeError("Authenticated Telegram account does not match OWNER_TELEGRAM_ID")

    print(f"RAHAT_AI_CONNECTED user_id={me.id}")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
