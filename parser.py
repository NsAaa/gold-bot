"""
Signal parser for Smith™ Gold VIP channel messages.

Handles two message types:
  1. New trade signal  → returns SignalMessage
  2. Update message    → returns UpdateMessage (TP hit, SL move, close)
"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SignalMessage:
    direction: str          # "buy" or "sell"
    symbol: str             # "XAUUSD"
    entry: Optional[float]  # None = market order
    sl: float
    tp1: float
    tp2: Optional[float]
    tp3: Optional[float]
    tp4: Optional[float]    # None = open-ended
    raw: str


@dataclass
class UpdateMessage:
    kind: str               # "tp1_hit" | "tp2_hit" | "tp3_hit" | "sl_to_entry" | "close"
    tp_level: Optional[int] # 1-4 if kind is tp*_hit
    raw: str


def parse_signal(text: str) -> Optional[SignalMessage]:
    """
    Parse a new trade signal message.
    Example:
        XAUUSD Gold Buy 🚨
        Entry: (Now) 4518
        Stop Loss: 4504
        TP1: 4527
        TP2: 4533
        TP3: 4538
        TP4: 4545
    """
    t = text.strip()

    # Direction
    direction_match = re.search(r'\b(buy|sell)\b', t, re.IGNORECASE)
    if not direction_match:
        return None
    direction = direction_match.group(1).lower()

    # Must mention Gold/XAUUSD
    if not re.search(r'(XAUUSD|Gold)', t, re.IGNORECASE):
        return None

    # Entry — "(Now)" or a numeric price
    entry: Optional[float] = None
    entry_match = re.search(r'entry\s*:\s*(?:\(now\)\s*)?([\d.]+)', t, re.IGNORECASE)
    if entry_match:
        entry = float(entry_match.group(1))
    elif re.search(r'entry\s*:\s*\(now\)', t, re.IGNORECASE):
        entry = None  # market order

    # SL
    sl_match = re.search(r'stop\s*loss\s*:\s*([\d.]+)', t, re.IGNORECASE)
    if not sl_match:
        return None
    sl = float(sl_match.group(1))

    # TPs
    def find_tp(n: int) -> Optional[float]:
        m = re.search(rf'TP{n}\s*:\s*([\d.]+)', t, re.IGNORECASE)
        return float(m.group(1)) if m else None

    tp1 = find_tp(1)
    if tp1 is None:
        return None  # TP1 is required

    return SignalMessage(
        direction=direction,
        symbol="XAUUSD",
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=find_tp(2),
        tp3=find_tp(3),
        tp4=find_tp(4),
        raw=text,
    )


def parse_update(text: str) -> Optional[UpdateMessage]:
    """
    Parse an update message from the channel.
    Examples:
        "TP1 smashed +90 pips ✅ move SL to entry"
        "TP2 hit 🍾 +140 pips 🔥"
        "TP3 ✅"
        "Close trade now ❌"
        "SL hit 🔴"
    """
    t = text.strip().lower()

    # TP hit messages
    tp_hit = re.search(r'tp(\d)\s*(smashed|hit|✅|closed|done)', t, re.IGNORECASE)
    if tp_hit:
        level = int(tp_hit.group(1))
        # Also check if it contains "move SL to entry" / "breakeven"
        if re.search(r'(move\s*sl\s*to\s*(entry|breakeven)|sl\s*to\s*entry)', t, re.IGNORECASE):
            return UpdateMessage(kind="sl_to_entry", tp_level=level, raw=text)
        return UpdateMessage(kind=f"tp{level}_hit", tp_level=level, raw=text)

    # Explicit SL to entry instruction (sometimes sent separately)
    if re.search(r'(move\s*sl\s*to\s*(entry|breakeven)|sl\s*to\s*entry)', t, re.IGNORECASE):
        return UpdateMessage(kind="sl_to_entry", tp_level=None, raw=text)

    # Close signal
    if re.search(r'(close\s*(trade|now|all|position)|exit\s*(now|all)|manual\s*close)', t, re.IGNORECASE):
        return UpdateMessage(kind="close", tp_level=None, raw=text)

    # SL hit (informational — trades already closed by exchange)
    if re.search(r'sl\s*hit|stop\s*loss\s*hit|stopped\s*out', t, re.IGNORECASE):
        return UpdateMessage(kind="sl_hit", tp_level=None, raw=text)

    return None


def parse_message(text: str) -> Optional[SignalMessage | UpdateMessage]:
    """Try signal first, then update."""
    sig = parse_signal(text)
    if sig:
        return sig
    return parse_update(text)
