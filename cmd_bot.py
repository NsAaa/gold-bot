"""
Goldie Command Bot — inline menu + long-polling.

Commands:
  /start /menu  — main menu with inline buttons
  /status       — open positions + live P&L
  /history      — last 10 closed signals
  /performance  — VIP vs FREE win-rate + P&L stats
  /config       — current settings
  /close        — close all open trades (with confirm)
"""
import asyncio
import json
import logging
import time
from typing import Callable, Awaitable, Optional

import aiohttp

from config import HISTORY_FILE, ACCOUNT_SIZE_USD, BROKER, get_lot_size

logger = logging.getLogger("cmd-bot")
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


# ── Inline keyboards ──────────────────────────────────────────────────────────

def _main_menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "📊 Status",      "callback_data": "status"},
         {"text": "💼 Positions",   "callback_data": "positions"}],
        [{"text": "📈 History",     "callback_data": "history"},
         {"text": "🏆 Performance", "callback_data": "performance"}],
        [{"text": "⚙️ Config",      "callback_data": "config"}],
        [{"text": "🔴 Close All",   "callback_data": "closeall_confirm"}],
    ]}

def _confirm_keyboard():
    return {"inline_keyboard": [[
        {"text": "✅ Yes, close all", "callback_data": "closeall_yes"},
        {"text": "❌ Cancel",         "callback_data": "closeall_cancel"},
    ]]}

def _back_keyboard():
    return {"inline_keyboard": [[
        {"text": "⬅️ Menu", "callback_data": "menu"},
    ]]}


# ── History helpers ───────────────────────────────────────────────────────────

def _load_history() -> list:
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception:
        return []


# ── View builders ─────────────────────────────────────────────────────────────

def _build_history_text(limit: int = 10) -> str:
    history = _load_history()
    if not history:
        return "📭 No closed signals yet."

    # Sort chronologically so injected/backfilled signals appear in correct order
    history = sorted(history, key=lambda s: s.get("open_time", 0))
    lines = [f"📈 *Last {min(limit, len(history))} signals*\n"]
    for sig in reversed(history[-limit:]):
        src   = sig.get("source", "VIP")
        sid   = sig.get("signal_id", "?")
        dirn  = sig.get("direction", "?").upper()
        entry = sig.get("entry_price", 0)
        pnl   = sig.get("total_pnl", 0)
        ts    = sig.get("open_time", 0)
        date  = time.strftime("%d %b %H:%M", time.localtime(ts)) if ts else "?"
        trades = sig.get("trades", [])
        closed = [t for t in trades if t.get("status") == "closed"]
        reasons = [t.get("close_reason", "?") for t in closed]
        tp_hits = reasons.count("tp")
        sl_hits = reasons.count("sl")
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        lines.append(
            f"[{src}] `{sid}` {dirn} @ {entry:.0f} | {date}\n"
            f"  TP: {tp_hits}/4  SL: {sl_hits}  P&L: {pnl_str}"
        )
    return "\n".join(lines)


def _build_performance_text() -> str:
    history = _load_history()
    if not history:
        return "📭 No closed signals yet — nothing to analyse."

    def stats(signals):
        if not signals:
            return None
        total_pnl  = sum(s.get("total_pnl", 0) for s in signals)
        all_trades = [t for s in signals for t in s.get("trades", [])]
        tp_hits    = sum(1 for t in all_trades if t.get("close_reason") == "tp")
        sl_hits    = sum(1 for t in all_trades if t.get("close_reason") == "sl")
        total_cl   = tp_hits + sl_hits
        win_rate   = (tp_hits / total_cl * 100) if total_cl else 0
        # A "win" signal = more TPs hit than SLs
        win_sigs   = sum(
            1 for s in signals
            if sum(1 for t in s.get("trades", []) if t.get("close_reason") == "tp") >
               sum(1 for t in s.get("trades", []) if t.get("close_reason") == "sl")
        )
        return {
            "signals": len(signals),
            "win_sigs": win_sigs,
            "total_pnl": total_pnl,
            "tp_hits": tp_hits,
            "sl_hits": sl_hits,
            "win_rate": win_rate,
        }

    vip  = stats([s for s in history if s.get("source") == "VIP"])
    free = stats([s for s in history if s.get("source") == "FREE"])
    both = stats(history)

    def fmt(label, s):
        if not s:
            return f"*{label}:* no data"
        pnl_str = f"+${s['total_pnl']:.2f}" if s['total_pnl'] >= 0 else f"-${abs(s['total_pnl']):.2f}"
        return (
            f"*{label}* ({s['signals']} signals, {s['win_sigs']} wins)\n"
            f"  Trade win rate: {s['win_rate']:.0f}%  (TP {s['tp_hits']} / SL {s['sl_hits']})\n"
            f"  Total P&L: {pnl_str}"
        )

    lines = ["🏆 *Performance*\n", fmt("VIP", vip), "", fmt("FREE", free), ""]
    if both and both["signals"] > 0:
        pnl_str = f"+${both['total_pnl']:.2f}" if both['total_pnl'] >= 0 else f"-${abs(both['total_pnl']):.2f}"
        lines.append(f"*Combined:* {both['signals']} signals | P&L: {pnl_str}")
    return "\n".join(lines)


def _build_config_text(manager=None) -> str:
    balance = manager.get_running_balance() if manager else ACCOUNT_SIZE_USD
    lot     = get_lot_size(balance)
    realised = balance - ACCOUNT_SIZE_USD
    realised_str = f"${realised:+.2f}" if realised != 0 else "$0.00"
    return (
        f"⚙️ *Goldie Config*\n\n"
        f"Mode: 🧪 {BROKER.upper()}\n"
        f"Starting balance: ${ACCOUNT_SIZE_USD:,.0f}\n"
        f"Running balance: ${balance:,.2f} ({realised_str} realised)\n"
        f"Lot size: {lot} per trade × 4 TPs\n"
        f"Pip value: ${lot * 10:.2f}/pip\n"
        f"Sources: VIP + FREE signals"
    )


# ── Main bot class ────────────────────────────────────────────────────────────

class CmdBot:
    def __init__(self, token: str, owner_id: int,
                 build_status_fn: Callable[[], Awaitable[str]],
                 build_positions_fn: Callable[[], Awaitable[str]],
                 manager):
        self.token      = token
        self.owner_id   = owner_id
        self.build_status    = build_status_fn
        self.build_positions = build_positions_fn
        self.manager    = manager
        self._offset    = 0
        self._running   = False

    def url(self, method: str) -> str:
        return TELEGRAM_API.format(token=self.token, method=method)

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    async def _post(self, method: str, payload: dict):
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(self.url(method), json=payload,
                                     timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return await resp.json()
        except Exception as e:
            logger.warning(f"API {method} error: {e}")
            return {}

    async def send(self, chat_id: int, text: str, keyboard=None):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if keyboard:
            payload["reply_markup"] = keyboard
        await self._post("sendMessage", payload)

    async def edit(self, chat_id: int, msg_id: int, text: str, keyboard=None):
        payload = {"chat_id": chat_id, "message_id": msg_id,
                   "text": text, "parse_mode": "Markdown"}
        if keyboard:
            payload["reply_markup"] = keyboard
        await self._post("editMessageText", payload)

    async def answer_callback(self, cb_id: str, text: str = ""):
        await self._post("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

    async def get_updates(self) -> list:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    self.url("getUpdates"),
                    params={"offset": self._offset, "timeout": 25,
                            "allowed_updates": ["message", "callback_query"]},
                    timeout=aiohttp.ClientTimeout(total=35),
                ) as resp:
                    data = await resp.json()
                    return data.get("result", [])
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"getUpdates error: {e}")
            await asyncio.sleep(5)
            return []

    # ── Menu / view dispatch ──────────────────────────────────────────────────

    async def _show_menu(self, chat_id: int, msg_id: Optional[int] = None, cb_id: Optional[str] = None):
        open_count = sum(
            1 for trades in self.manager.open_signals.values()
            for t in trades if t.status == "open"
        )
        text = (
            f"🥇 *Goldie — Gold Copy Bot*\n"
            f"Mode: 🧪 Paper | Signals: VIP + FREE\n"
            f"Open trades: {open_count}"
        )
        if cb_id:
            await self.answer_callback(cb_id)
            await self.edit(chat_id, msg_id, text, _main_menu_keyboard())
        else:
            await self.send(chat_id, text, _main_menu_keyboard())

    async def _handle_callback(self, cb: dict):
        cb_id   = cb["id"]
        data    = cb.get("data", "")
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]
        from_id = cb.get("from", {}).get("id")

        if from_id != self.owner_id:
            await self.answer_callback(cb_id, "⛔ Not authorised")
            return

        await self.answer_callback(cb_id)

        if data == "menu":
            await self._show_menu(chat_id, msg_id, cb_id=None)
            return

        if data == "status":
            text = await self.build_status()
            await self.edit(chat_id, msg_id, text, _back_keyboard())

        elif data == "positions":
            text = await self.build_positions()
            await self.edit(chat_id, msg_id, text, _back_keyboard())

        elif data == "history":
            text = _build_history_text()
            await self.edit(chat_id, msg_id, text, _back_keyboard())

        elif data == "performance":
            text = _build_performance_text()
            await self.edit(chat_id, msg_id, text, _back_keyboard())

        elif data == "config":
            text = _build_config_text(self.manager)
            await self.edit(chat_id, msg_id, text, _back_keyboard())

        elif data == "closeall_confirm":
            if not self.manager.open_signals:
                await self.edit(chat_id, msg_id, "📭 No open trades to close.", _back_keyboard())
            else:
                count = sum(
                    1 for trades in self.manager.open_signals.values()
                    for t in trades if t.status == "open"
                )
                await self.edit(chat_id, msg_id,
                    f"⚠️ Close all {count} open trades?\nThis cannot be undone.",
                    _confirm_keyboard())

        elif data == "closeall_yes":
            count = 0
            for sid in list(self.manager.open_signals.keys()):
                trades = self.manager.open_signals[sid]
                open_trades = [t for t in trades if t.status == "open"]
                count += len(open_trades)
                await self.manager._close_all(sid, open_trades, reason="manual")
            await self.edit(chat_id, msg_id, f"🔴 Closed {count} trades.", _back_keyboard())

        elif data == "closeall_cancel":
            await self._show_menu(chat_id, msg_id)

    # ── Command handler ───────────────────────────────────────────────────────

    async def handle_update(self, update: dict):
        # Callback from inline button
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
            return

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        from_id = msg.get("from", {}).get("id")
        text    = (msg.get("text") or "").strip()
        chat_id = msg["chat"]["id"]

        if from_id != self.owner_id:
            return

        logger.info(f"Command: {text!r} from {from_id}")

        if text in ("/start", "/help", "/menu"):
            await self._show_menu(chat_id)

        elif text == "/status":
            status = await self.build_status()
            await self.send(chat_id, status, _back_keyboard())

        elif text == "/positions":
            pos = await self.build_positions()
            await self.send(chat_id, pos, _back_keyboard())

        elif text == "/history":
            await self.send(chat_id, _build_history_text(), _back_keyboard())

        elif text == "/performance":
            await self.send(chat_id, _build_performance_text(), _back_keyboard())

        elif text == "/config":
            await self.send(chat_id, _build_config_text(self.manager), _back_keyboard())

        elif text == "/close":
            if not self.manager.open_signals:
                await self.send(chat_id, "📭 No open positions to close.")
                return
            count = sum(
                1 for trades in self.manager.open_signals.values()
                for t in trades if t.status == "open"
            )
            for sid in list(self.manager.open_signals.keys()):
                trades = self.manager.open_signals[sid]
                open_trades = [t for t in trades if t.status == "open"]
                await self.manager._close_all(sid, open_trades, reason="manual")
            await self.send(chat_id, f"🔴 Closed {count} trades manually.")

    # ── Poll loop ─────────────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        updates = await self.get_updates()
        if updates:
            self._offset = updates[-1]["update_id"] + 1

        logger.info("Command bot polling for updates...")
        while self._running:
            updates = await self.get_updates()
            for update in updates:
                self._offset = update["update_id"] + 1
                try:
                    await self.handle_update(update)
                except Exception as e:
                    logger.error(f"Handle update error: {e}")

    def stop(self):
        self._running = False
