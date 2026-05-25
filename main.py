"""
Gold Copy Trading Bot — Main entry point.

Monitors Smith™ Gold VIP Telegram channel via userbot,
parses signals, and paper-trades them automatically.

Optionally runs a command bot (set TELEGRAM_BOT_TOKEN in .env) that
responds to /status and /close commands from Conrad's Telegram.
"""
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE,
    SIGNAL_CHANNEL, NOTIFY_CHAT_ID, BROKER, ACCOUNT_SIZE_USD, get_lot_size,
    TELEGRAM_BOT_TOKEN,
)
from parser import parse_message, SignalMessage, UpdateMessage
from trade_manager import TradeManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gold-bot")

# ── Userbot client (Conrad's account — monitors signal channel) ───────────────
app = Client(
    "gold_bot_session",
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    phone_number=TELEGRAM_PHONE,
)

# ── Command bot client (optional — BotFather token for /status etc.) ──────────
cmd_bot: Client = None
if TELEGRAM_BOT_TOKEN:
    cmd_bot = Client(
        "gold_cmd_bot",
        api_id=TELEGRAM_API_ID,
        api_hash=TELEGRAM_API_HASH,
        bot_token=TELEGRAM_BOT_TOKEN,
    )

manager: TradeManager = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def send_notify(msg: str):
    """Send notification to Conrad's Saved Messages."""
    try:
        await app.send_message(NOTIFY_CHAT_ID, msg)
    except Exception as e:
        logger.error(f"Notify failed: {e}")


async def build_status_text() -> str:
    """Build a position summary string."""
    if not manager.open_signals:
        return "📭 No open positions."

    try:
        price = await manager.broker.get_current_price()
    except Exception:
        price = None

    lines = ["📊 *Goldie — Open Positions*"]
    if price:
        lines.append(f"Live price: ${price:.2f}\n")

    total_pnl = 0.0
    for sid, trades in manager.open_signals.items():
        open_trades  = [t for t in trades if t.status == "open"]
        closed_count = len(trades) - len(open_trades)
        lines.append(f"Signal `{sid}` — {len(open_trades)} open, {closed_count} closed")
        for t in open_trades:
            if price:
                d = -1 if t.direction == "sell" else 1
                unreal = (price - t.entry_price) * d * 10 * t.lot_size
                total_pnl += unreal
                unreal_str = f" | P&L: ${unreal:+.2f}"
            else:
                unreal_str = ""
            lines.append(
                f"  TP{t.tp_level}: {t.direction.upper()} @ {t.entry_price:.0f}"
                f" | SL {t.sl:.0f} | TP {t.tp:.0f}" + unreal_str
            )

    if price:
        lines.append(f"\nTotal unrealised: ${total_pnl:+.2f}")

    return "\n".join(lines)


# ── Userbot: signal channel handler ──────────────────────────────────────────

@app.on_message(filters.chat(SIGNAL_CHANNEL))
async def on_channel_message(client: Client, message: Message):
    # Ignore forwarded reposts from the free channel
    if message.forward_from_chat:
        logger.debug(f"Skipping forward from {message.forward_from_chat.title or message.forward_from_chat.id}")
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


# ── Command bot: /status, /close ──────────────────────────────────────────────

if cmd_bot:

    # Only allow Conrad's own chat ID to use commands
    owner_filter = filters.user(NOTIFY_CHAT_ID) & filters.private

    @cmd_bot.on_message(owner_filter & filters.command("start"))
    async def cmd_start(client: Client, message: Message):
        await message.reply(
            "🟢 *Goldie command bot*\n\n"
            "/status — open positions + live P&L\n"
            "/close — manually close all open trades\n"
        )

    @cmd_bot.on_message(owner_filter & filters.command("status"))
    async def cmd_status(client: Client, message: Message):
        text = await build_status_text()
        await message.reply(text)

    @cmd_bot.on_message(owner_filter & filters.command("close"))
    async def cmd_close(client: Client, message: Message):
        if not manager.open_signals:
            await message.reply("📭 No open positions to close.")
            return
        count = sum(
            1 for trades in manager.open_signals.values()
            for t in trades if t.status == "open"
        )
        # Close all via the update handler
        for sid in list(manager.open_signals.keys()):
            trades = manager.open_signals[sid]
            open_trades = [t for t in trades if t.status == "open"]
            await manager._close_all(sid, open_trades, reason="manual")
        await message.reply(f"🔴 Closed {count} trades manually.")

    logger.info("Command bot configured — /status and /close available")


# ── Main ──────────────────────────────────────────────────────────────────────

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

    # Start command bot if configured
    if cmd_bot:
        await cmd_bot.start()
        me = await cmd_bot.get_me()
        logger.info(f"Command bot online: @{me.username}")

    async with app:
        await send_notify(
            f"🟢 *Gold Bot started*\n"
            f"Mode: {'Paper trade 🧪' if BROKER == 'paper' else 'LIVE 🔴'}\n"
            f"Account: ${ACCOUNT_SIZE_USD:.0f} | Lot size: {get_lot_size()} per trade\n"
            f"Monitoring: {SIGNAL_CHANNEL}"
            + (f"\nCommands: @{(await cmd_bot.get_me()).username}" if cmd_bot else "")
        )
        logger.info("Listening for signals...")
        if manager.open_signals:
            await send_notify(await build_status_text())
        await watchdog()

    # Clean up command bot
    if cmd_bot:
        await cmd_bot.stop()


async def _send_position_summary():
    await send_notify(await build_status_text())


# ── Watchdog ──────────────────────────────────────────────────────────────────

WATCHDOG_INTERVAL = 300  # seconds between health checks
WATCHDOG_TIMEOUT  = 30   # seconds to wait for ping response


async def watchdog():
    """Ping Telegram every 5 min; exit on failure so PM2 restarts."""
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
