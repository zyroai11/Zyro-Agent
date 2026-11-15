"""Market data and the safety score. Same rules as the Zyro Telegram bot."""
import time
import httpx
from . import config as C

_http = httpx.Client(timeout=20, headers={"user-agent": "zyro-agent"})

def pairs(address: str) -> list[dict]:
    r = _http.get(f"https://api.dexscreener.com/tokens/v1/{C.CHAIN_DEX}/{address}")
    r.raise_for_status()
    data = r.json()
    return [p for p in (data if isinstance(data, list) else data.get("pairs") or []) if p.get("chainId") == C.CHAIN_DEX]

def best_pair(address: str) -> dict | None:
    """Most liquid pair where this token is the base token."""
    a = address.lower()
    ps = [p for p in pairs(address) if (p.get("baseToken") or {}).get("address", "").lower() == a]
    if not ps:
        return None
    return max(ps, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))

_eth_cache = {"t": 0, "v": None}
def eth_usd() -> float:
    if _eth_cache["v"] and time.time() - _eth_cache["t"] < 60:
        return _eth_cache["v"]
    p = best_pair(C.WETH)
    v = float(p["priceUsd"]) if p and p.get("priceUsd") else None
    if not v:
        raise RuntimeError("Could not read the ETH price from DexScreener")
    _eth_cache.update(t=time.time(), v=v)
    return v

def search_symbol(symbol: str) -> list[dict]:
    """Robinhood Chain pairs matching a ticker, most liquid first."""
    r = _http.get("https://api.dexscreener.com/latest/dex/search", params={"q": symbol})
    r.raise_for_status()
    s = symbol.lstrip("$").upper()
    ps = [p for p in r.json().get("pairs") or [] if p.get("chainId") == C.CHAIN_DEX and (p.get("baseToken") or {}).get("symbol", "").upper() == s]
    return sorted(ps, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)

def _bs(path):
    if C.BLOCKSCOUT_API_KEY:
        return f"https://api.blockscout.com/{C.CHAIN_ID}/api/v2/{path}", {"apikey": C.BLOCKSCOUT_API_KEY}
    return f"{C.EXPLORER}/api/v2/{path}", {}

def explorer_info(address: str) -> dict:
    info = {"verified": None, "holders": None}
    try:
        url, params = _bs(f"smart-contracts/{address}")
        r = _http.get(url, params=params)
        if r.status_code == 200:
            info["verified"] = bool(r.json().get("is_verified"))
        elif r.status_code == 404:
            info["verified"] = False
    except Exception:
        pass
    try:
        url, params = _bs(f"tokens/{address}")
        r = _http.get(url, params=params)
        if r.status_code == 200:
            h = r.json().get("holders") or r.json().get("holders_count")
            info["holders"] = int(h) if h is not None else None
    except Exception:
        pass
    return info

def score(pair: dict, chain: dict) -> tuple[int, list[tuple[str, str]]]:
    """Score 0-100, higher is safer, plus the list of (level, reason) that lowered it."""
    s, flags = 100, []
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    fdv = float(pair.get("fdv") or 0)
    vol = float((pair.get("volume") or {}).get("h24") or 0)
    tx = (pair.get("txns") or {}).get("h24") or {}
    buys, sells = tx.get("buys", 0), tx.get("sells", 0)
    created = pair.get("pairCreatedAt")
    age_h = (time.time() * 1000 - created) / 3_600_000 if created else None
    info = pair.get("info") or {}
    if liq < 5_000:
        s -= 30; flags.append(("bad", "Very low liquidity, under $5K"))
    elif liq < 25_000:
        s -= 15; flags.append(("warn", "Low liquidity, under $25K"))
    if age_h is not None and age_h < 24:
        s -= 15; flags.append(("warn", "New pair, under 24 hours old"))
    if fdv and liq and fdv / liq > 50:
        s -= 10; flags.append(("warn", "FDV is far above liquidity"))
    if liq and vol / liq > 20:
        s -= 10; flags.append(("warn", "Volume is unusually high for the liquidity"))
    if buys > 20 and sells == 0:
        s -= 30; flags.append(("bad", "Buys but zero sells: possible honeypot"))
    elif buys + sells > 20 and sells / max(buys, 1) > 3:
        s -= 10; flags.append(("warn", "Heavy selling pressure"))
    if not info.get("socials") and not info.get("websites"):
        s -= 10; flags.append(("warn", "No website or socials listed"))
    if chain.get("verified") is False:
        s -= 15; flags.append(("warn", "Contract not verified on the explorer"))
    h = chain.get("holders")
    if h is not None and h < 50:
        s -= 10; flags.append(("warn", f"Few holders ({h})"))
    if chain.get("verified") is None or h is None:
        s = min(s, 90); flags.append(("info", "Holder or contract data unavailable, score capped at 90"))
    return max(0, min(100, s)), flags

def verdict(s: int) -> tuple[str, str]:
    if s >= 75: return "Low risk", "green"
    if s >= 50: return "Medium risk", "yellow"
    if s >= 25: return "High risk", "dark_orange"
    return "Very high risk", "red"

def scan(address: str) -> dict | None:
    p = best_pair(address)
    if not p:
        return None
    chain = explorer_info(address)
    s, flags = score(p, chain)
    return {"pair": p, "chain": chain, "score": s, "flags": flags,
            "symbol": (p.get("baseToken") or {}).get("symbol") or "?",
            "name": (p.get("baseToken") or {}).get("name") or "?",
            "price_usd": float(p.get("priceUsd") or 0)}
