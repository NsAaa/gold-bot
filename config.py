"""
Gold Copy Trading Bot — Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram Userbot ──────────────────────────────────────────────────────────
# Get from https://my.telegram.org → API development tools
TELEGRAM_API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE    = os.getenv("TELEGRAM_PHONE", "")        # e.g. +46701234567

# Channel to monitor (username or numeric ID)
# Set to the username of the Smith™ Gold VIP channel
SIGNAL_CHANNEL = os.getenv("SIGNAL_CHANNEL", "")           # e.g. "SmithGoldVIP"

# Where to send trade notifications (your personal chat)
NOTIFY_CHAT_ID = int(os.getenv("NOTIFY_CHAT_ID", "693111427"))

# Optional: Telegram bot token for command interface (from @BotFather)
# Leave blank to disable the command bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── Account / Risk ────────────────────────────────────────────────────────────
# Simulated account size in USD (for lot sizing)
# Starting paper account balance in USD.
# Smith's formula adapted: 0.01 lots per $500 of balance.
# $1270 starting (~£1000) → 0.02 lots per trade.
ACCOUNT_SIZE_USD = float(os.getenv("ACCOUNT_SIZE_USD", "1270"))

def get_lot_size(balance_usd: float = None) -> float:
    """Return lot size per trade: 0.01 per $500 of balance (Smith's formula)."""
    bal  = balance_usd if balance_usd is not None else ACCOUNT_SIZE_USD
    lots = max(1, int(bal / 500)) * 0.01
    return round(lots, 2)

# ── Broker ────────────────────────────────────────────────────────────────────
# "paper" = simulated | "binance" | "bitget"
BROKER = os.getenv("BROKER", "paper")

# Binance Futures API (used when BROKER=binance)
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET    = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

# Bitget API (used when BROKER=bitget)
BITGET_API_KEY     = os.getenv("BITGET_API_KEY", "")
BITGET_API_SECRET  = os.getenv("BITGET_API_SECRET", "")
BITGET_PASSPHRASE  = os.getenv("BITGET_PASSPHRASE", "")

# ── Trading ───────────────────────────────────────────────────────────────────
SYMBOL        = "XAUUSDT"       # Gold perpetual futures symbol
TP4_TRAIL_PCT = 0.005           # 0.5% trailing stop for TP4 (open-ended trade)

# When True, bot automatically moves SL to entry after TP1 hits.
# When False, bot waits for Smith's explicit "move SL to entry" channel message.
# Set to False to follow Smith's timing rather than moving SL immediately.
AUTO_BREAKEVEN = os.getenv("AUTO_BREAKEVEN", "false").lower() == "true"

# Bid/ask spread simulation (in USD, full spread split equally each side).
# Typical gold retail broker spread: 0.3–1.0 USD.
# e.g. SPREAD_USD=0.5 → BID = mid - 0.25, ASK = mid + 0.25
# Buys  → entry at ASK, TP/SL monitored against BID
# Sells → entry at BID, TP/SL monitored against ASK
SPREAD_USD = float(os.getenv("SPREAD_USD", "0.5"))

# ── State ─────────────────────────────────────────────────────────────────────
STATE_FILE   = "state.json"
HISTORY_FILE = "history.json"
