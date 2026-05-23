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

# ── Account / Risk ────────────────────────────────────────────────────────────
# Simulated account size in USD (for lot sizing)
# Smith's rule: 0.01 lots per TP per £500 (~$630)
# Account size in GBP (Smith's formula is GBP-denominated)
# £1000 → 0.02 lots per trade (0.01 per £500)
ACCOUNT_SIZE_GBP = float(os.getenv("ACCOUNT_SIZE_GBP", "1000"))

# Kept for reference / notifications
ACCOUNT_SIZE_USD = ACCOUNT_SIZE_GBP * 1.27  # approximate

# Lot size per trade = 0.01 × (account_gbp / 500)
LOT_SIZE_PER_500 = 0.01

def get_lot_size() -> float:
    """Return lot size per individual trade based on GBP account size."""
    return round(LOT_SIZE_PER_500 * (ACCOUNT_SIZE_GBP / 500), 2)

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

# ── State ─────────────────────────────────────────────────────────────────────
STATE_FILE = "state.json"
