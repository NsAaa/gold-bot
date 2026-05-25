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
        await app.send_message(NOTIFY_CHAT_ID, msg)
    except Exception as e:
        logger.error(f"Notify failed: {e}")


@app.on_message(filters.me & filters.private)
async def on_saved_command(client: Client, message: Message):
    """Handle commands sent to Saved Messages (Conrad's own chat)."""
    text = (message.text or "").strip().lower()
    if text not in ("!status", "/status"):
        return

    if not manager.open_signals:
        await message.reply("📭 No open positions.")
        return

    try:
        price = await manager.broker.get_current_price()
    except Exception:
        price = None

    lines = [f"📊 *Goldie — Open Positions*"]
    if price:
        lines.append(f"Live price: ${price:.2f}\n")

    for sid, trades in manager.open_signals.items():
        open_trades = [t for t in trades if t.status == "open"]
        closed_count = len(trades) - len(open_trades)
        lines.append(f"Signal `{sid}` — {len(open_trades)} open, {closed_count} closed")
        for t in open_trades:
            if price:
                d = -1 if t.direction == "sell" else 1
                unreal = (price - t.entry_price) * d * 10 * t.lot_size
                unreal_str = f" | P&L: ${unreal:+.2f}"
            else:
                unreal_str = ""
            lines.append(
                f"  TP{t.tp_level}: {t.direction.upper()} @ {t.entry_price:.0f} "
                f"| SL {t.sl:.0f} | TP {t.tp:.0f}"
                + unreal_str
            )

    await message.reply("\n".join(lines))


@app.on_message(filters.chat(SIGNAL_CHANNEL))
async def on_channel_message(client: Client, message: Message):
    # Ignore messages forwarded from other channels (e.g. free channel reposts)
    if message.forward_from_chat:
        logger.debug(f"Skipping forwarded message from {message.forward_from_chat.title or message.forward_from_chat.id}")
        return

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
        await watchdog()  # keeps running; exits on dead connection so PM2 restarts


WATCHDOG_INTERVAL = 300  # seconds between health checks
WATCHDOG_TIMEOUT  = 30   # seconds to wait for ping response


async def watchdog():
    """Periodically ping Telegram to verify the connection is alive.
    Exits (non-zero) on failure so PM2 restarts the process.
    """
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL)
        try:
            await asyncio.wait_for(app.get_me(), timeout=WATCHDOG_TIMEOUT)
            logger.debug("Watchdog: connection OK")
        except asyncio.TimeoutError:
            logger.error("Watchdog: ping timed out — restarting")
            raise SystemExit(1)
        except Exception as e:
            logger.error(f"Watchdog: connection check failed ({e}) — restarting")
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
