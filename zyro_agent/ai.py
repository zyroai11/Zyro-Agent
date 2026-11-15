"""Chat mode: plain-language instructions turned into agent actions.

The AI only proposes an action. The agent's own rules still apply, and live trades
still ask for confirmation.
"""
import json, re
import httpx
from . import config as C, agent, market
from .agent import console, Stop

SYSTEM = """You are Zyro, a trading agent for Robinhood Chain running in the user's terminal.
Turn the user's message into ONE action as JSON with these keys:
action: one of "scan", "buy", "sell", "positions", "wallet", "rules", "help", "none"
token: contract address (0x...) or ticker like "ZYRO" if given, else null
eth: number of ETH to spend for buy, else null
percent: percent of the position to sell (100 if they say all), else null
min_score: minimum safety score if the user sets a condition like "if the score is above 70", else null
stop_loss: stop loss percent if given, else null
take_profit: take profit percent if given, else null
reply: one short sentence to the user, always in English, saying what you will do, or answering their question if action is "none".
Never invent addresses. Never promise profits. Output only the JSON."""

def ask_ai(msg: str) -> dict:
    if not C.GEMINI_API_KEY:
        raise RuntimeError("no key")
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{C.GEMINI_MODEL}:generateContent",
        params={"key": C.GEMINI_API_KEY},
        json={"systemInstruction": {"parts": [{"text": SYSTEM}]},
              "contents": [{"role": "user", "parts": [{"text": msg}]}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 0}},
        timeout=90)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)

NUM = r"(\d+(?:\.\d+)?)"
ADDR = r"(0x[a-fA-F0-9]{40})"
def parse_local(msg: str) -> dict | None:
    """Exact direct commands only (scan 0x.., buy 0.05 eth 0x.., sell 50% 0x..).
    Anything with extra conditions goes to the AI, so a condition is never silently dropped."""
    low = " ".join(msg.strip().lower().split())
    if low in ("positions", "pos", "posisi"): return {"action": "positions"}
    if low in ("wallet", "balance", "saldo"): return {"action": "wallet"}
    if low in ("rules", "config", "aturan"): return {"action": "rules"}
    if low in ("help", "?", "bantuan"): return {"action": "help"}
    m = re.fullmatch(r"(?:scan|cek)\s+" + ADDR, low)
    if m: return {"action": "scan", "token": m.group(1)}
    m = re.fullmatch(r"(?:buy|beli)\s+" + NUM + r"\s*(?:eth)?\s+" + ADDR, low) or \
        re.fullmatch(r"(?:buy|beli)\s+" + ADDR + r"\s+" + NUM + r"\s*(?:eth)?", low)
    if m:
        a, b = m.groups()
        addr, eth = (a, b) if a.startswith("0x") else (b, a)
        return {"action": "buy", "token": addr, "eth": float(eth)}
    m = re.fullmatch(r"(?:sell|jual)\s+(?:" + NUM + r"\s*%|(all|semua)\s+)?\s*" + ADDR, low)
    if m:
        pct, _all, addr = m.groups()
        return {"action": "sell", "token": addr, "percent": float(pct) if pct else 100.0}
    return None

def resolve(token: str | None) -> str:
    if not token:
        raise Stop("Which token? Paste its contract address.")
    if agent.is_addr(token):
        return token
    found = market.search_symbol(token)
    if not found:
        raise Stop(f"No Robinhood Chain token found for {token}. Paste the contract address instead.")
    a = found[0]["baseToken"]["address"]
    console.print(f"[yellow]▲ ${token.lstrip('$').upper()} matched {a} (the most liquid pair). "
                  "Fake tokens copy tickers, so check this address is the real one.[/]")
    if not agent.confirm("Use this address?"):
        raise Stop("Cancelled.")
    return a

HELP = """Talk to me in plain words, or use direct commands:
  scan 0x…                  safety score for a token
  buy 0.05 eth 0x…           buy with your rules checked first
  sell 50% 0x…               sell part or all of a position
  positions · wallet · rules
Examples: "beli 0.02 ETH 0x… kalau skornya di atas 70, stop loss 10%"
          "jual semua 0x…"   ·   "exit" to leave"""

def run(action: dict, live: bool) -> None:
    a = (action.get("action") or "none").lower()
    if a == "scan":
        agent.scan(resolve(action.get("token")))
    elif a == "buy":
        if not action.get("eth"):
            raise Stop("How much ETH should I spend? For example: buy 0.02 eth 0x…")
        agent.buy(resolve(action.get("token")), float(action["eth"]), live=live,
                  sl=action.get("stop_loss"), tp=action.get("take_profit"), min_score=action.get("min_score"))
    elif a == "sell":
        agent.sell(resolve(action.get("token")), float(action.get("percent") or 100), live=live)
    elif a == "positions":
        agent.positions(live)
    elif a == "wallet":
        agent.wallet()
    elif a == "rules":
        agent.rules()
    elif a == "help":
        console.print(HELP)

def chat(live: bool = False) -> None:
    console.print(agent.mode_tag(live), " [bold]Zyro chat[/]  [dim]type 'help' for examples, 'exit' to leave[/]")
    if not C.GEMINI_API_KEY:
        console.print("[dim]No GEMINI_API_KEY in .env, so only direct commands work (scan, buy, sell, positions).[/]")
    while True:
        try:
            msg = console.input("[bold blue]zyro›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print(); return
        if not msg:
            continue
        if msg.lower() in ("exit", "quit", "keluar", "q"):
            return
        try:
            act = parse_local(msg)
            if act is None:
                with console.status("Thinking…"):
                    act = ask_ai(msg)
                if act.get("reply"):
                    console.print(f"[cyan]{act['reply']}[/]")
            run(act, live)
        except Stop as e:
            console.print(f"[yellow]{e}[/]")
        except RuntimeError as e:
            if str(e) == "no key":
                console.print("[yellow]I need GEMINI_API_KEY in .env to understand free text. Try: scan 0x…, buy 0.02 eth 0x…[/]")
            else:
                console.print(f"[red]{e}[/]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
