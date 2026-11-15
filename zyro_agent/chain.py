"""Wallet and on-chain calls on Robinhood Chain."""
from web3 import Web3
from eth_account import Account
from . import config as C

ERC20 = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint8"}]},
    {"name": "symbol", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "string"}]},
]

_w3 = None
def w3() -> Web3:
    global _w3
    if _w3 is None:
        _w3 = Web3(Web3.HTTPProvider(C.RPC_URL, request_kwargs={"timeout": 30}))
    return _w3

def account():
    if not C.PRIVATE_KEY:
        raise RuntimeError("PRIVATE_KEY is not set in .env. Live trading needs a wallet.")
    key = C.PRIVATE_KEY if C.PRIVATE_KEY.startswith("0x") else "0x" + C.PRIVATE_KEY
    return Account.from_key(key)

def address() -> str | None:
    try:
        return account().address
    except Exception:
        return None

def eth_balance(addr: str) -> int:
    return w3().eth.get_balance(Web3.to_checksum_address(addr))

def token(addr: str):
    return w3().eth.contract(address=Web3.to_checksum_address(addr), abi=ERC20)

def token_balance(tok: str, owner: str) -> int:
    return token(tok).functions.balanceOf(Web3.to_checksum_address(owner)).call()

def decimals(tok: str) -> int:
    try:
        return int(token(tok).functions.decimals().call())
    except Exception:
        return 18

def _int(v):
    if v is None or v == "":
        return None
    return int(v, 16) if isinstance(v, str) and v.startswith("0x") else int(v)

def send(tx: dict) -> tuple[str, bool]:
    """Sign and send a transaction returned by the Uniswap API. Returns (hash, success)."""
    acct = account(); web3 = w3()
    out = {
        "from": acct.address,
        "to": Web3.to_checksum_address(tx["to"]),
        "data": tx.get("data") or "0x",
        "value": _int(tx.get("value")) or 0,
        "chainId": C.CHAIN_ID,
        "nonce": web3.eth.get_transaction_count(acct.address, "pending"),
    }
    gas = _int(tx.get("gasLimit"))
    out["gas"] = int((gas or web3.eth.estimate_gas(out)) * 1.2)
    base = web3.eth.get_block("latest").get("baseFeePerGas", 0) or 0
    try:
        tip = web3.eth.max_priority_fee
    except Exception:
        tip = Web3.to_wei(0.01, "gwei")
    out["maxPriorityFeePerGas"] = _int(tx.get("maxPriorityFeePerGas")) or tip
    out["maxFeePerGas"] = max(_int(tx.get("maxFeePerGas")) or 0, base * 2 + out["maxPriorityFeePerGas"])
    signed = acct.sign_transaction(out)
    h = web3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = web3.eth.wait_for_transaction_receipt(h, timeout=180)
    return Web3.to_hex(h), rcpt.status == 1

def tx_url(h: str) -> str:
    return f"{C.EXPLORER}/tx/{h}"
