"""
Broker interface — paper trading mode (live Binance/Bitget stubs ready).

Paper mode simulates Gold (XAUUSD) trades:
  - P&L calculated in USD using lot size
  - 1 pip = $0.1 per 0.01 lot (standard Gold contract sizing)
  - Tracks open trades and simulates fills

Price source: Stooq (stooq.com) — free real-time spot XAUUSD, no auth required.
Fallback: Yahoo Finance GC=F (futures) minus a fixed offset (~27 pips).
Yahoo Finance XAUUSD=X is unavailable; Stooq gives true spot that matches
Smith's broker and TradingView prices.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
import requests
import yfinance as yf
from config import SYMBOL, BROKER, BINANCE_API_KEY, BINANCE_API_SECRET, SPREAD_USD


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
    source: str = "VIP"     # "VIP" or "FREE"


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

    # Fallback offset if Stooq is unavailable: GC=F futures → approximate spot.
    FUTURES_SPOT_OFFSET = 27.0  # pips (USD)

    def _fetch_price_stooq(self) -> float:
        """Fetch real spot XAUUSD from Stooq (free, no auth). Returns mid price."""
        url = "https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        # CSV: Symbol,Date,Time,Open,High,Low,Close,Volume
        lines = r.text.strip().splitlines()
        if len(lines) < 2:
            raise ValueError("Stooq returned no data")
        parts = lines[1].split(",")
        price = float(parts[6])  # Close
        if not price:
            raise ValueError("Stooq returned zero price")
        return price

    def _fetch_price_gcf_fallback(self) -> float:
        """Fallback: GC=F futures via yfinance, minus fixed spot offset."""
        hist = yf.download("GC=F", period="1d", interval="1m", progress=False, auto_adjust=True)
        if hist.empty:
            raise ValueError("yfinance returned no data for GC=F")
        val = hist["Close"].iloc[-1]
        price = float(val.iloc[0]) if hasattr(val, "iloc") else float(val)
        if not price:
            raise ValueError("yfinance returned zero price for GC=F")
        return price - self.FUTURES_SPOT_OFFSET

    def _fetch_price_sync(self) -> float:
        """Fetch spot XAUUSD — Stooq primary, GC=F fallback."""
        try:
            return self._fetch_price_stooq()
        except Exception as e:
            import logging
            logging.getLogger("broker").warning(f"Stooq price fetch failed ({e}), falling back to GC=F")
            return self._fetch_price_gcf_fallback()

    def _bid(self, mid: float) -> float:
        """BID = mid − half spread. Used for BUY SL/TP checks and SELL fills."""
        return mid - SPREAD_USD / 2

    def _ask(self, mid: float) -> float:
        """ASK = mid + half spread. Used for SELL SL/TP checks and BUY fills."""
        return mid + SPREAD_USD / 2

    async def get_current_price(self) -> float:
        """Fetch live spot Gold price from Stooq (XAUUSD), with GC=F fallback."""
        now = time.time()
        if self._price_cache and (now - self._price_ts) < 5:
            return self._price_cache
        loop = asyncio.get_event_loop()
        try:
            price = await loop.run_in_executor(None, self._fetch_price_sync)
            self._price_cache = price
            self._price_ts = now
            return price
        except Exception:
            # Fallback: return last cached price or raise
            if self._price_cache:
                return self._price_cache
            raise

    async def open_trade(self, trade: Trade, fill_price: Optional[float] = None) -> Trade:
        """
        Simulate trade open with spread.
        BUY fills at ASK (mid + half spread); SELL fills at BID (mid - half spread).
        """
        mid = fill_price if fill_price is not None else await self.get_current_price()
        if trade.direction == "buy":
            fill = self._ask(mid)   # pay the spread on buy entry
        else:
            fill = self._bid(mid)   # lose the spread on sell entry
        trade.entry_price = fill
        trade.peak_price = fill
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

    async def check_sl_tp(self, trade: Trade) -> tuple[Optional[str], Optional[float]]:
        """
        Check if current price has hit SL or TP.
        Returns (reason, fill_price) where reason is "sl", "tp", "trailing", or None.
        fill_price is the exact SL/TP level (not the live market price) for accurate P&L.
        """
        if trade.status == "closed":
            return None, None
        price = await self.get_current_price()

        if trade.direction == "buy":
            # BUY: monitor against BID (mid - half spread)
            bid = self._bid(price)
            if trade.peak_price is None or bid > trade.peak_price:
                trade.peak_price = bid
            # SL hit
            if bid <= trade.sl:
                return "sl", trade.sl
            # TP hit
            if trade.tp and bid >= trade.tp:
                return "tp", trade.tp
            # TP4 trailing stop
            if not trade.tp and trade.trail_pct and trade.peak_price:
                drop = (trade.peak_price - bid) / trade.peak_price
                if drop >= trade.trail_pct:
                    return "trailing", bid
        else:  # sell
            # SELL: monitor against ASK (mid + half spread)
            ask = self._ask(price)
            if trade.peak_price is None or ask < trade.peak_price:
                trade.peak_price = ask
            # SL hit
            if ask >= trade.sl:
                return "sl", trade.sl
            # TP hit
            if trade.tp and ask <= trade.tp:
                return "tp", trade.tp
            # TP4 trailing stop
            if not trade.tp and trade.trail_pct and trade.peak_price:
                rise = (ask - trade.peak_price) / trade.peak_price
                if rise >= trade.trail_pct:
                    return "trailing", ask
        return None, None


def get_broker() -> PaperBroker:
    """Factory — returns PaperBroker for now; live brokers when ready."""
    if BROKER == "paper":
        return PaperBroker()
    # TODO: LiveBinanceBroker(), LiveBitgetBroker()
    raise ValueError(f"Unknown broker: {BROKER}")
