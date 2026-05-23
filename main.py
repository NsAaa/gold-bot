"""
Gold Copy Trading Bot — Main entry point.

Monitors Smith™ Gold VIP Telegram channel via userbot,
parses signals, and paper-trades them automatically.
"""
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE,
    SIGNAL_CHANNEL, NOTIFY_CHAT_ID, BROKER, ACCOUNT_SIZE_USD, get_lot_size
)
from parser import parse_message, SignalMessage, UpdateMessage
from trade_manager import TradeManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gold-bot")

# ── Telegram client (userbot — runs as Conrad's account) ──────────────────────
app = Client(
    "gold_bot_session",
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    phone_number=TELEGRAM_PHONE,
)

manager: TradeManager = None


async def send_notify(msg: str):
    """Send notification to Conrad's personal chat."""
    try:
        await app.send_message(NOTIFY_CHAT_ID, msg, parse_mode="markdown")
    except Exception as e:
        logger.error(f"Notify failed: {e}")


@app.on_message(filters.chat(SIGNAL_CHANNEL))
async def on_channel_message(client: Client, message: Message):
    text = message.text or message.caption or ""
    if not text.strip():
        return

    logger.info(f"Channel message: {text[:80]!r}")
    parsed = parse_message(text)

    if isinstance(parsed, SignalMessage):
        logger.info(f"New signal: {parsed.direction.upper()} | SL {parsed.sl} | TPs {parsed.tp1}/{parsed.tp2}/{parsed.tp3}/{parsed.tp4}")
        await manager.on_signal(parsed)

    elif isinstance(parsed, UpdateMessage):
        logger.info(f"Update: {parsed.kind}")
        await manager.on_update(parsed)

    else:
        logger.debug("Message not recognised as signal or update — ignoring")


async def main():
    global manager
    manager = TradeManager(notify_fn=send_notify)

    logger.info("=" * 55)
    logger.info("  Gold Copy Trading Bot")
    logger.info(f"  Mode: {'🧪 PAPER TRADE' if BROKER == 'paper' else '🔴 LIVE'}")
    logger.info(f"  Account size: ${ACCOUNT_SIZE_USD:.0f} | Lot per trade: {get_lot_size()}")
    logger.info(f"  Monitoring: {SIGNAL_CHANNEL}")
    logger.info("=" * 55)

    await manager.start_monitor()

    async with app:
        await send_notify(
            f"🟢 *Gold Bot started*\n"
            f"Mode: {'Paper trade 🧪' if BROKER == 'paper' else 'LIVE 🔴'}\n"
            f"Account: ${ACCOUNT_SIZE_USD:.0f} | Lot size: {get_lot_size()} per trade\n"
            f"Monitoring: {SIGNAL_CHANNEL}"
        )
        logger.info("Listening for signals...")
        await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
