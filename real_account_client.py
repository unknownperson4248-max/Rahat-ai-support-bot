"""Rahat AI real-account Telegram client.

Runs as an MTProto client using Telethon. Secrets and the generated session
must stay outside Git. First login should be done in a private terminal.
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

    # Phase 1: prove the real account connection without auto-replying.
    # AI/Supabase/image/voice routing is added after the authenticated session
    # is confirmed healthy, so a bad first deploy cannot spam customers.
    print(f"RAHAT_AI_INCOMING peer={event.chat_id} message_id={event.id}")


async def main():
    me = await client.get_me()
    if OWNER_ID and me.id != OWNER_ID:
        raise RuntimeError("Authenticated Telegram account does not match OWNER_TELEGRAM_ID")
    print(f"RAHAT_AI_CONNECTED user_id={me.id}")
    await client.run_until_disconnected()


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
