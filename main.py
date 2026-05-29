"""
Gold Copy Trading Bot — Main entry point.

Monitors Smith™ Gold VIP Telegram channel by POLLING for new messages
every 30 seconds. Push-based handlers (on_message) are unreliable for
userbots on channels — Telegram only pushes to "active" clients.

Optionally runs a command bot (set TELEGRAM_BOT_TOKEN in .env) that
responds to /status and /close commands from Conrad's Telegram.
"""
import asyncio
import logging
from pyrogram import Client
from pyrogram.types import Message

from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE,
    SIGNAL_CHANNEL, NOTIFY_CHAT_ID, BROKER, ACCOUNT_SIZE_USD, get_lot_size,
    TELEGRAM_BOT_TOKEN,
)
from cmd_bot import CmdBot
from parser import parse_message, SignalMessage, UpdateMessage
from trade_manager import TradeManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gold-bot")

# ── Userbot client (Conrad's account — monitors signal channel) ───────────────
_channel_id = int(SIGNAL_CHANNEL) if SIGNAL_CHANNEL.lstrip('-').isdigit() else SIGNAL_CHANNEL

app = Client(
    "gold_bot_session",
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    phone_number=TELEGRAM_PHONE,
)

# ── Command bot (optional — BotFather token for /status etc.) ────────────────
cmd_bot: CmdBot = None  # initialised in main() after manager is ready

manager: TradeManager = None

# Track the last message ID we've processed so we don't reprocess on restart
_last_seen_msg_id: int = 0

# Poll interval in seconds
POLL_INTERVAL = 30


# ── Helpers ───────────────────────────────────────────────────────────────────

async def send_notify(msg: str):
    """Send notification — via command bot if available, else directly."""
    try:
        if cmd_bot:
            await cmd_bot.send(NOTIFY_CHAT_ID, msg)
        else:
            await app.send_message(NOTIFY_CHAT_ID, msg)
    except Exception as e:
        logger.error(f"Notify failed: {e}")


async def build_status_text() -> str:
    """Concise status — open count + unrealised P&L."""
    try:
        price = await manager.broker.get_current_price()
    except Exception:
        price = None

    open_count = sum(
        1 for trades in manager.open_signals.values()
        for t in trades if t.status == "open"
    )

    balance = manager.get_running_balance()
    lot     = get_lot_size(balance)

    lines = ["📊 *Goldie — Status*", ""]
    lines.append(f"Mode: 🧪 Paper | Sources: VIP + FREE")
    lines.append(f"Balance: ${balance:,.2f} | Lot: {lot}/trade")
    lines.append(f"Open trades: {open_count}")
    if price:
        lines.append(f"Gold price: ${price:.2f}")

    if not manager.open_signals:
        lines.append("\n📭 No open positions.")
        return "\n".join(lines)

    total_pnl = 0.0
    lines.append("")
    for sid, trades in manager.open_signals.items():
        open_trades  = [t for t in trades if t.status == "open"]
        closed_count = len(trades) - len(open_trades)
        src = open_trades[0].source if open_trades else "?"
        lines.append(f"[{src}] `{sid}` — {len(open_trades)} open, {closed_count} closed")
        if price:
            for t in open_trades:
                d = 1 if t.direction == "buy" else -1
                unreal = (price - t.entry_price) * d * 10 * t.lot_size
                total_pnl += unreal

    if price:
        pnl_str = f"${total_pnl:+.2f}"
        lines.append(f"\nUnrealised P&L: {pnl_str}")

    return "\n".join(lines)


async def build_positions_text() -> str:
    """Detailed per-trade positions view."""
    if not manager.open_signals:
        return "📭 No open positions."

    try:
        price = await manager.broker.get_current_price()
    except Exception:
        price = None

    lines = ["💼 *Open Positions*"]
    if price:
        lines.append(f"Gold: ${price:.2f}")
    lines.append("")

    total_pnl = 0.0
    for sid, trades in manager.open_signals.items():
        open_trades  = [t for t in trades if t.status == "open"]
        closed_count = len(trades) - len(open_trades)
        src = open_trades[0].source if open_trades else "?"
        entry = open_trades[0].entry_price if open_trades else 0
        dirn  = open_trades[0].direction.upper() if open_trades else "?"
        lines.append(f"*[{src}] `{sid}`* — {dirn} @ {entry:.0f} | {len(open_trades)} open, {closed_count} closed")
        for t in open_trades:
            if price:
                d = 1 if t.direction == "buy" else -1
                unreal = (price - t.entry_price) * d * 10 * t.lot_size
                total_pnl += unreal
                unreal_str = f" | {unreal:+.2f}"
            else:
                unreal_str = ""
            tp_str = f"{t.tp:.0f}" if t.tp else "open"
            lines.append(f"  TP{t.tp_level}: SL {t.sl:.0f} → TP {tp_str}{unreal_str}")
        lines.append("")

    if price:
        lines.append(f"Total unrealised: ${total_pnl:+.2f}")

    return "\n".join(lines)


# ── Channel polling ───────────────────────────────────────────────────────────

async def process_message(message: Message):
    """Process a single channel message — parse and act on signals."""
    # Detect forwarded messages and tag source (FREE vs VIP)
    if message.forward_from_chat:
        fwd_title = message.forward_from_chat.title or ""
        if "smith" in fwd_title.lower() and "gold" in fwd_title.lower():
            source = "FREE"
            logger.debug(f"Forwarded from Smith free channel: {fwd_title!r}")
        else:
            logger.debug(f"Skipping forward from unrecognised channel: {fwd_title!r}")
            return
    else:
        source = "VIP"

    text = message.text or message.caption or ""
    if not text.strip():
        return

    logger.info(f"Channel message [{source}]: {text[:80]!r}")
    parsed = parse_message(text)

    if isinstance(parsed, SignalMessage):
        parsed.source = source
        logger.info(f"New signal [{source}]: {parsed.direction.upper()} | SL {parsed.sl} | TPs {parsed.tp1}/{parsed.tp2}/{parsed.tp3}/{parsed.tp4}")
        await manager.on_signal(parsed)

    elif isinstance(parsed, UpdateMessage):
        logger.info(f"Update [{source}]: {parsed.kind}")
        await manager.on_update(parsed)

    else:
        logger.debug("Message not recognised as signal or update — ignoring")


async def poll_channel():
    """
    Poll Smith's channel every POLL_INTERVAL seconds for new messages.
    On startup, initialise _last_seen_msg_id to the current latest message
    so we don't replay old signals, then process only newer messages.
    """
    global _last_seen_msg_id

    # Initialise: fetch the single latest message to anchor our position
    try:
        async for msg in app.get_chat_history(_channel_id, limit=1):
            _last_seen_msg_id = msg.id
        logger.info(f"Channel poll initialised — last msg ID: {_last_seen_msg_id}")
    except Exception as e:
        logger.warning(f"Could not initialise channel poll: {e}")

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            new_messages = []
            async for msg in app.get_chat_history(_channel_id, limit=20):
                if msg.id <= _last_seen_msg_id:
                    break
                new_messages.append(msg)

            if new_messages:
                logger.info(f"Poll: {len(new_messages)} new message(s) in channel")
                # Process oldest first
                for msg in reversed(new_messages):
                    await process_message(msg)
                _last_seen_msg_id = new_messages[0].id  # most recent
            else:
                logger.debug(f"Poll: no new messages (last ID: {_last_seen_msg_id})")

        except Exception as e:
            logger.error(f"Poll error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_userbot():
    """Run the userbot: polls signal channel, sends notifications."""
    async with app:
        bot_tag = "\nCommands: /status /close via bot" if TELEGRAM_BOT_TOKEN else ""
        running_balance = manager.get_running_balance()
        running_lot = get_lot_size(running_balance)
        realised = running_balance - ACCOUNT_SIZE_USD
        realised_str = f"+${realised:.2f}" if realised >= 0 else f"-${abs(realised):.2f}"
        await send_notify(
            f"🟢 *Gold Bot started*\n"
            f"Mode: {'Paper trade 🧪' if BROKER == 'paper' else 'LIVE 🔴'}\n"
            f"Balance: ${running_balance:,.2f} ({realised_str} realised) | Lot: {running_lot}/trade\n"
            f"Monitoring: {SIGNAL_CHANNEL} (polling every {POLL_INTERVAL}s)" + bot_tag
        )

        try:
            chat = await app.get_chat(_channel_id)
            logger.info(f"Monitoring channel: {chat.title} ({chat.id})")
        except Exception as e:
            logger.warning(f"Could not fetch channel info: {e}")

        if manager.open_signals:
            await send_notify(await build_status_text())

        logger.info(f"Polling {SIGNAL_CHANNEL} every {POLL_INTERVAL}s for signals...")
        await asyncio.gather(poll_channel(), watchdog())


async def run_cmdbot():
    """Run the command bot: handles /status, /close from Conrad."""
    await cmd_bot.run()


async def main():
    global manager
    manager = TradeManager(notify_fn=send_notify)

    logger.info("=" * 55)
    logger.info("  Gold Copy Trading Bot")
    logger.info(f"  Mode: {'🧪 PAPER TRADE' if BROKER == 'paper' else '🔴 LIVE'}")
    running_balance = manager.get_running_balance() if manager else ACCOUNT_SIZE_USD
    running_lot = get_lot_size(running_balance)
    realised = running_balance - ACCOUNT_SIZE_USD
    logger.info(f"  Balance: ${running_balance:,.2f} (base ${ACCOUNT_SIZE_USD:.0f} + ${realised:.2f} P&L) | Lot: {running_lot}/trade")
    logger.info(f"  Monitoring: {SIGNAL_CHANNEL} (poll mode)")
    logger.info("=" * 55)

    await manager.start_monitor()

    global cmd_bot
    if TELEGRAM_BOT_TOKEN:
        cmd_bot = CmdBot(
            token=TELEGRAM_BOT_TOKEN,
            owner_id=NOTIFY_CHAT_ID,
            build_status_fn=build_status_text,
            build_positions_fn=build_positions_text,
            manager=manager,
        )
        logger.info("Command bot configured — /status and /close available")
        await asyncio.gather(run_userbot(), run_cmdbot())
    else:
        await run_userbot()


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
