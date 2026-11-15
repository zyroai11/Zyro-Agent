"""Positions, trade history and today's realised result, kept in a local JSON file."""
import json, os, time
from datetime import datetime, timezone
from . import config as C

def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def load() -> dict:
    try:
        return json.loads(C.STATE_FILE.read_text())
    except Exception:
        return {}

def book(mode: str) -> dict:
    s = load()
    b = s.get(mode) or {}
    b.setdefault("positions", {}); b.setdefault("trades", []); b.setdefault("daily", {})
    return b

def save_book(mode: str, b: dict) -> None:
    s = load(); s[mode] = b
    tmp = C.STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2))
    os.replace(tmp, C.STATE_FILE)

def realised_today(b: dict) -> float:
    return float(b["daily"].get(today(), 0.0))

def log_trade(b: dict, **kw) -> None:
    kw["time"] = int(time.time())
    b["trades"].append(kw)
    b["trades"] = b["trades"][-500:]
