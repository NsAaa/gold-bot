# Gold Copy Trading Bot

Automatically copies Smith™ Gold VIP signals from Telegram and paper-trades them.

## How it works

1. Runs as a Telegram userbot (your account) monitoring the VIP channel
2. Detects new trade signals and opens 4 trades simultaneously (one per TP level)
3. Monitors price and manages trades:
   - TP1 hit → auto-moves SL to entry on remaining 3 trades
   - TP2/TP3 → closes those trades at target
   - TP4 → no fixed target, 0.5% trailing stop captures outlier moves
4. Sends all trade updates to your personal Telegram chat

## Command Bot (optional but recommended)

Create a bot via [@BotFather](https://t.me/BotFather) for `/status` and `/close` commands:

1. Open @BotFather → `/newbot`
2. Give it a name (e.g. `Goldie Monitor`) and username (e.g. `goldiebot_yourname_bot`)
3. Copy the token and add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABCdef...
   ```
4. Restart the bot — it will print the bot username on startup
5. Start a chat with your new bot → `/start`

Available commands:
- `/status` — open positions + live P&L
- `/close` — manually close all open trades

---

## Setup

### 1. Get Telegram API credentials
Go to https://my.telegram.org → "API development tools" → create an app.
You'll get an `api_id` and `api_hash`.

### 2. Find the channel username
Open the Smith™ Gold VIP channel in Telegram Web, the username is in the URL.

### 3. Configure
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Install dependencies
```bash
pip install -r requirements.txt
```

### 5. Run
```bash
python main.py
```
First run will ask for your phone number and a verification code (one-time setup).
After that it saves a session file and runs automatically.

## Lot sizing (Smith's formula)
- 0.01 lots per trade per £500 (~$630) account size
- 4 trades per signal → total exposure = lot_size × 4
- Example: $1000 account → 0.02 lots × 4 = 0.08 lots total

## Signal format recognised
```
XAUUSD Gold Buy 🚨
Entry: (Now) 4518
Stop Loss: 4504
TP1: 4527
TP2: 4533
TP3: 4538
TP4: 4545
```

## Update messages recognised
- "TP1 smashed ✅ move SL to entry" → moves SL to breakeven on trades 2-4
- "TP2 hit 🍾" → informational (trade already closed at TP2)
- "Close trade now" → closes all open trades for that signal
