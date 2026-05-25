"""
Goldie Command Bot — lightweight HTTP long-polling bot.

Uses the raw Telegram Bot API (no Pyrogram) for reliability.
Handles /start, /status, /close from Conrad's Telegram.
"""
import asyncio
import logging
import aiohttp
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("cmd-bot")

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class CmdBot:
    def __init__(self, token: str, owner_id: int, build_status_fn: Callable[[], Awaitable[str]], manager):
        self.token = token
        self.owner_id = owner_id
        self.build_status = build_status_fn
        self.manager = manager
        self._offset = 0
        self._running = False

    def url(self, method: str) -> str:
        return TELEGRAM_API.format(token=self.token, method=method)

    async def send(self, chat_id: int, text: str):
        async with aiohttp.ClientSession() as sess:
            await sess.post(self.url("sendMessage"), json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })

    async def get_updates(self) -> list:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    self.url("getUpdates"),
                    params={"offset": self._offset, "timeout": 25, "allowed_updates": ["message"]},
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

    async def handle_update(self, update: dict):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        from_id = msg.get("from", {}).get("id")
        text = (msg.get("text") or "").strip()
        chat_id = msg["chat"]["id"]

        # Only respond to owner
        if from_id != self.owner_id:
            return

        logger.info(f"Command: {text!r} from {from_id}")

        if text in ("/start", "/help"):
            await self.send(chat_id,
                "🟢 *Goldie command bot*\n\n"
                "/status — open positions \\+ live P&L\n"
                "/close — manually close all open trades"
            )

        elif text == "/status":
            status = await self.build_status()
            await self.send(chat_id, status)

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

    async def run(self):
        """Long-poll loop — runs until cancelled."""
        self._running = True
        # Drop any pending updates from before we started
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
