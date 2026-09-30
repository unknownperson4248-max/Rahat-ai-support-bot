"""Rahat AI real-account Telegram client (Termux connection test).

Uses the already-authenticated local Telethon session file. API credentials
must be supplied through environment variables and must never be committed.
"""
import asyncio
import os
from telethon import TelegramClient, events

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.environ.get("TELEGRAM_SESSION", "rahat_ai")
OWNER_ID = int(os.environ.get("OWNER_TELEGRAM_ID", "0") or 0)

client = TelegramClient(SESSION, API_ID, API_HASH)


@client.on(events.NewMessage(incoming=True))
async def on_message(event):
    if not event.is_private:
        return
    sender = await event.get_sender()
    if not sender or getattr(sender, "bot", False):
        return
    print(f"RAHAT_AI_INCOMING peer={event.chat_id} message_id={event.id}")


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
