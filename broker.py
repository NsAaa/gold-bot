"""
Broker interface — paper trading mode (live Binance/Bitget stubs ready).

Paper mode simulates Gold (XAUUSD) trades:
  - P&L calculated in USD using lot size
  - 1 pip = $0.1 per 0.01 lot (standard Gold contract sizing)
  - Tracks open trades and simulates fills
"""
import asyncio
import aiohttp
import time
from dataclasses import dataclass, field
from typing import Optional
from config import SYMBOL, BROKER, BINANCE_API_KEY, BINANCE_API_SECRET


@dataclass
class Trade:
    id: str
    symbol: str
    direction: str          # "buy" | "sell"
    lot_size: float
    entry_price: float
    sl: float
    tp: Optional[float]     # None = open-ended (TP4)
    tp_level: int           # 1-4
    signal_id: str          # links all 4 trades from one signal
    open_time: float = field(default_factory=time.time)
    close_price: Optional[float] = None
    close_time: Optional[float] = None
    close_reason: Optional[str] = None  # "tp" | "sl" | "manual" | "trailing"
    pnl_usd: Optional[float] = None
    status: str = "open"    # "open" | "closed"
    # TP4 trailing stop
    peak_price: Optional[float] = None
    trail_pct: Optional[float] = None


class PaperBroker:
    """
    Simulated broker. Fetches real Gold price from Binance public API
    to calculate realistic fills and P&L.
    """

    PIP_VALUE_PER_LOT = 10  # $10 per pip per full lot (Gold standard)
                             # → $0.1 per pip per 0.01 lot

    def __init__(self):
        self._price_cache: Optional[float] = None
        self._price_ts: float = 0

    async def get_current_price(self) -> float:
        """Fetch live Gold price from Binance public API (no auth needed)."""
        now = time.time()
        if self._price_cache and (now - self._price_ts) < 5:
            return self._price_cache
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    "https://fapi.binance.com/fapi/v1/ticker/price",
                    params={"symbol": "XAUUSDT"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json()
                    price = float(data["price"])
                    self._price_cache = price
                    self._price_ts = now
                    return price
        except Exception:
            # Fallback: return last cached price or raise
            if self._price_cache:
                return self._price_cache
            raise

    async def open_trade(self, trade: Trade) -> Trade:
        """Simulate trade open — fills at current market price."""
        price = await self.get_current_price()
        trade.entry_price = price
        trade.peak_price = price
        trade.status = "open"
        return trade

    async def close_trade(self, trade: Trade, reason: str, price: Optional[float] = None) -> Trade:
        """Close a trade and calculate P&L."""
        if trade.status == "closed":
            return trade
        close_price = price or await self.get_current_price()
        direction_mult = 1 if trade.direction == "buy" else -1
        pips = (close_price - trade.entry_price) * direction_mult
        # P&L: pips × $10/pip/lot × lot_size
        pnl = pips * self.PIP_VALUE_PER_LOT * trade.lot_size
        trade.close_price = close_price
        trade.close_time = time.time()
        trade.close_reason = reason
        trade.pnl_usd = round(pnl, 2)
        trade.status = "closed"
        return trade

    async def modify_sl(self, trade: Trade, new_sl: float) -> Trade:
        """Move stop loss (paper: just update the object)."""
        trade.sl = new_sl
        return trade

    async def check_sl_tp(self, trade: Trade) -> Optional[str]:
        """
        Check if current price has hit SL or TP.
        Returns "sl", "tp", "trailing", or None.
        """
        if trade.status == "closed":
            return None
        price = await self.get_current_price()

        if trade.direction == "buy":
            # Update peak for trailing (TP4)
            if trade.peak_price is None or price > trade.peak_price:
                trade.peak_price = price
            # SL hit
            if price <= trade.sl:
                return "sl"
            # TP hit
            if trade.tp and price >= trade.tp:
                return "tp"
            # TP4 trailing stop
            if not trade.tp and trade.trail_pct and trade.peak_price:
                drop = (trade.peak_price - price) / trade.peak_price
                if drop >= trade.trail_pct:
                    return "trailing"
        else:  # sell
            if trade.peak_price is None or price < trade.peak_price:
                trade.peak_price = price
            if price >= trade.sl:
                return "sl"
            if trade.tp and price <= trade.tp:
                return "tp"
            if not trade.tp and trade.trail_pct and trade.peak_price:
                rise = (price - trade.peak_price) / trade.peak_price
                if rise >= trade.trail_pct:
                    return "trailing"
        return None


def get_broker() -> PaperBroker:
    """Factory — returns PaperBroker for now; live brokers when ready."""
    if BROKER == "paper":
        return PaperBroker()
    # TODO: LiveBinanceBroker(), LiveBitgetBroker()
    raise ValueError(f"Unknown broker: {BROKER}")
