"""
Trade manager — opens/tracks the 4 trades per signal, handles updates.
"""
import asyncio
import json
import uuid
import time
import logging
from typing import Optional
from dataclasses import dataclass, asdict, field

from config import get_lot_size, TP4_TRAIL_PCT, STATE_FILE
from parser import SignalMessage, UpdateMessage
from broker import Trade, get_broker

logger = logging.getLogger(__name__)


class TradeManager:
    def __init__(self, notify_fn=None):
        self.broker = get_broker()
        self.notify = notify_fn or (lambda msg: None)  # async callback
        self.open_signals: dict[str, list[Trade]] = {}  # signal_id → [trade×4]
        self._monitor_task: Optional[asyncio.Task] = None
        self._load_state()

    # ── Signal handling ────────────────────────────────────────────────────────

    async def on_signal(self, sig: SignalMessage):
        """Open 4 trades from a new signal."""
        signal_id = str(uuid.uuid4())[:8]
        lot = get_lot_size()
        price = await self.broker.get_current_price()

        tps = [sig.tp1, sig.tp2, sig.tp3, sig.tp4]
        trades = []

        for i, tp in enumerate(tps, 1):
            trade = Trade(
                id=f"{signal_id}-tp{i}",
                symbol="XAUUSDT",
                direction=sig.direction,
                lot_size=lot,
                entry_price=price,
                sl=sig.sl,
                tp=tp,
                tp_level=i,
                signal_id=signal_id,
                trail_pct=TP4_TRAIL_PCT if tp is None else None,
            )
            trade = await self.broker.open_trade(trade)
            trades.append(trade)
            logger.info(f"Opened TP{i} trade {trade.id} @ {trade.entry_price} | SL {sig.sl} | TP {tp or 'open'}")

        self.open_signals[signal_id] = trades
        self._save_state()

        await self.notify(
            f"🥇 Gold {sig.direction.upper()} — {len(trades)} trades opened\n"
            f"Entry: ${price:.2f} | SL: ${sig.sl:.2f}\n"
            f"TP1: ${sig.tp1} | TP2: ${sig.tp2 or '-'} | "
            f"TP3: ${sig.tp3 or '-'} | TP4: {'open' if sig.tp4 is None else sig.tp4}\n"
            f"Lot size: {lot} × 4 | Signal ID: {signal_id}"
        )

    async def on_update(self, upd: UpdateMessage):
        """Handle a channel update message."""
        if not self.open_signals:
            logger.debug("Update received but no open signals — ignoring")
            return

        # Apply to the most recent open signal
        signal_id = list(self.open_signals.keys())[-1]
        trades = self.open_signals[signal_id]
        open_trades = [t for t in trades if t.status == "open"]

        if upd.kind == "sl_to_entry":
            await self._move_sl_to_entry(signal_id, open_trades)

        elif upd.kind == "close":
            await self._close_all(signal_id, open_trades, reason="manual")
            await self.notify(f"🔴 Manual close — all {signal_id} trades closed")

        elif upd.kind in ("sl_hit",):
            logger.info(f"SL hit confirmed by channel for {signal_id}")
            # Trades already closed by exchange in live mode; in paper mode
            # the monitor loop handles this. Just log it.

    async def _move_sl_to_entry(self, signal_id: str, trades: list[Trade]):
        for t in trades:
            if t.tp_level > 1 and t.status == "open":
                entry = t.entry_price
                await self.broker.modify_sl(t, entry)
                logger.info(f"  SL moved to entry {entry:.2f} for {t.id}")
        self._save_state()
        await self.notify(
            f"🔒 Breakeven activated — SL moved to entry on remaining trades\n"
            f"Signal: {signal_id}"
        )

    async def _close_all(self, signal_id: str, trades: list[Trade], reason: str):
        for t in trades:
            if t.status == "open":
                t = await self.broker.close_trade(t, reason)
        self.open_signals.pop(signal_id, None)
        self._save_state()

    # ── Monitor loop ───────────────────────────────────────────────────────────

    async def start_monitor(self):
        """Background loop: check SL/TP on all open trades every 10s."""
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        while True:
            try:
                await self._check_all_trades()
            except Exception as e:
                logger.error(f"Monitor error: {e}")
            await asyncio.sleep(10)

    async def _check_all_trades(self):
        dirty = False
        closed_signal_ids = []

        for signal_id, trades in list(self.open_signals.items()):
            open_trades = [t for t in trades if t.status == "open"]
            if not open_trades:
                closed_signal_ids.append(signal_id)
                continue

            tp1_trade = next((t for t in trades if t.tp_level == 1), None)
            tp1_closed = tp1_trade and tp1_trade.status == "closed"

            for trade in open_trades:
                result = await self.broker.check_sl_tp(trade)
                if not result:
                    continue

                price = await self.broker.get_current_price()
                trade = await self.broker.close_trade(trade, result, price)
                dirty = True
                pnl_str = f"+${trade.pnl_usd:.2f}" if trade.pnl_usd and trade.pnl_usd >= 0 else f"${trade.pnl_usd:.2f}"

                if result == "tp":
                    await self.notify(
                        f"✅ TP{trade.tp_level} hit — {trade.symbol}\n"
                        f"Close: ${price:.2f} | P&L: {pnl_str}\n"
                        f"Signal: {signal_id}"
                    )
                    # Auto breakeven on TP1 hit
                    if trade.tp_level == 1 and not tp1_closed:
                        remaining = [t for t in trades if t.status == "open" and t.tp_level > 1]
                        await self._move_sl_to_entry(signal_id, remaining)

                elif result == "sl":
                    await self.notify(
                        f"🔴 SL hit — TP{trade.tp_level} trade\n"
                        f"Close: ${price:.2f} | P&L: {pnl_str}\n"
                        f"Signal: {signal_id}"
                    )

                elif result == "trailing":
                    await self.notify(
                        f"🎯 TP4 trailing stop — {trade.symbol}\n"
                        f"Close: ${price:.2f} | P&L: {pnl_str}\n"
                        f"Signal: {signal_id}"
                    )

            # Clean up fully closed signals
            if all(t.status == "closed" for t in trades):
                closed_signal_ids.append(signal_id)
                total_pnl = sum(t.pnl_usd or 0 for t in trades)
                pnl_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"${total_pnl:.2f}"
                await self.notify(
                    f"📊 Signal complete — {signal_id}\n"
                    f"Total P&L: {pnl_str}"
                )

        for sid in closed_signal_ids:
            self.open_signals.pop(sid, None)
            dirty = True

        if dirty:
            self._save_state()

    # ── State persistence ──────────────────────────────────────────────────────

    def _save_state(self):
        data = {
            "open_signals": {
                sid: [asdict(t) for t in trades]
                for sid, trades in self.open_signals.items()
            }
        }
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def _load_state(self):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            for sid, trade_dicts in data.get("open_signals", {}).items():
                self.open_signals[sid] = [Trade(td) for td in trade_dicts]
            logger.info(f"State loaded — {len(self.open_signals)} open signals")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
