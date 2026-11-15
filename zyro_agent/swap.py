"""Swaps through the Uniswap Trading API (v2, v3 and v4 pools on Robinhood Chain)."""
import httpx
from eth_account import Account
from web3 import Web3
from . import config as C

API = "https://trade-api.gateway.uniswap.org/v1"
_http = httpx.Client(timeout=30)

class NoRoute(Exception):
    pass

def _post(path: str, body: dict) -> dict:
    if not C.UNISWAP_API_KEY:
        raise RuntimeError("UNISWAP_API_KEY is not set in .env. Get a free key at developers.uniswap.org.")
    r = _http.post(f"{API}{path}", json=body, headers={"x-api-key": C.UNISWAP_API_KEY, "content-type": "application/json", "accept": "application/json"})
    try:
        data = r.json()
    except Exception:
        data = {"detail": r.text[:300]}
    if r.status_code >= 400:
        detail = str(data.get("detail") or data.get("errorCode") or data)
        if r.status_code == 404 or "no quote" in detail.lower() or "NoRoute" in detail or "No quotes" in detail:
            raise NoRoute(detail)
        raise RuntimeError(f"Uniswap API {r.status_code}: {detail}")
    return data

def quote(token_in: str, token_out: str, amount_raw: int, swapper: str) -> dict:
    return _post("/quote", {
        "type": "EXACT_INPUT",
        "amount": str(amount_raw),
        "tokenInChainId": C.CHAIN_ID, "tokenOutChainId": C.CHAIN_ID,
        "tokenIn": token_in, "tokenOut": token_out,
        "swapper": swapper,
        "slippageTolerance": C.SLIPPAGE_PCT,
        "routingPreference": "BEST_PRICE",
        "protocols": ["V2", "V3", "V4"],   # on-chain pools only, so the result is a normal swap transaction
    })

def amount_out(q: dict) -> int:
    return int(q["quote"]["output"]["amount"])

def price_impact(q: dict):
    v = q["quote"].get("priceImpact")
    return float(v) if v is not None else None

def gas_usd(q: dict):
    v = q["quote"].get("gasFeeUSD")
    return float(v) if v is not None else None

def approval_tx(token: str, amount_raw: int, wallet: str) -> dict | None:
    """ERC-20 approval needed before selling a token, or None if it is already approved."""
    r = _post("/check_approval", {"walletAddress": wallet, "token": token, "amount": str(amount_raw), "chainId": C.CHAIN_ID})
    return r.get("approval")

def _ints(types: dict, primary: str, values):
    """The API sends uint values as strings; typed-data signing needs ints."""
    out = {}
    for f in types.get(primary, []):
        v = values.get(f["name"])
        t = f["type"]
        if t in types:
            out[f["name"]] = _ints(types, t, v)
        elif t.startswith(("uint", "int")) and isinstance(v, str):
            out[f["name"]] = int(v, 16) if v.startswith("0x") else int(v)
        else:
            out[f["name"]] = v
    return out

def sign_permit(permit: dict, private_key: str) -> str:
    types = {k: v for k, v in permit["types"].items() if k != "EIP712Domain"}
    used = {f["type"] for fs in types.values() for f in fs}
    primary = next(k for k in types if k not in used)
    values = _ints(types, primary, permit["values"])
    signed = Account.sign_typed_data(private_key, domain_data=permit["domain"], message_types=types, message_data=values)
    return Web3.to_hex(signed.signature)

def swap_tx(q: dict, private_key: str | None = None) -> dict:
    body = {"quote": q["quote"]}
    if q.get("permitData"):
        body["permitData"] = q["permitData"]
        body["signature"] = sign_permit(q["permitData"], private_key)
    return _post("/swap", body)["swap"]
