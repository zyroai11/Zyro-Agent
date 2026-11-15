"""Command line entry: zyro <command>."""
import argparse, sys
from . import __version__, agent, ai, config as C
from .agent import console, Stop

BANNER = r"""[bold blue]
 ███████╗██╗   ██╗██████╗  ██████╗
 ╚══███╔╝╚██╗ ██╔╝██╔══██╗██╔═══██╗
   ███╔╝  ╚████╔╝ ██████╔╝██║   ██║
  ███╔╝    ╚██╔╝  ██╔══██╗██║   ██║
 ███████╗   ██║   ██║  ██║╚██████╔╝
 ╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝[/]  [dim]agent for Robinhood Chain · v{v}[/]"""

def eth_arg(s: str) -> float:
    return float(str(s).lower().replace("eth", "").strip())

def pct_arg(s: str) -> float:
    s = str(s).lower().replace("%", "").strip()
    return 100.0 if s in ("all", "semua") else float(s)

def main(argv=None):
    p = argparse.ArgumentParser(prog="zyro", description="Zyro agent: scan and trade Robinhood Chain tokens from your terminal.")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="Safety score for a token")
    s.add_argument("token")

    for name in ("buy", "trade"):
        b = sub.add_parser(name, help="Buy a token with ETH, after a scan and your rules")
        b.add_argument("token")
        b.add_argument("eth", nargs="?", type=eth_arg, help="ETH to spend, e.g. 0.02")
        b.add_argument("--max", dest="eth_max", type=eth_arg, help="Same as the eth amount, e.g. --max 0.2eth")
        b.add_argument("--sl", type=float, help="Stop loss percent for this position")
        b.add_argument("--tp", type=float, help="Take profit percent for this position")
        b.add_argument("--min-score", type=float, help="Only buy if the score is at least this")
        b.add_argument("--live", action="store_true", help="Send a real transaction")
        b.add_argument("--yes", action="store_true", help="Skip the confirmation question")

    se = sub.add_parser("sell", help="Sell part or all of a token")
    se.add_argument("token")
    se.add_argument("percent", nargs="?", default="100", type=pct_arg, help="Percent to sell, or 'all' (default)")
    se.add_argument("--live", action="store_true")
    se.add_argument("--yes", action="store_true")

    po = sub.add_parser("positions", help="Open positions and today's result")
    po.add_argument("--live", action="store_true")

    w = sub.add_parser("watch", help="Watch positions and sell on stop loss or take profit")
    w.add_argument("--live", action="store_true")
    w.add_argument("--interval", type=int)

    c = sub.add_parser("chat", help="Talk to the agent in plain language")
    c.add_argument("--live", action="store_true")

    sub.add_parser("init", help="Show where your settings file is")
    sub.add_parser("wallet", help="Wallet address and ETH balance")
    sub.add_parser("rules", help="Show your trading rules")

    a = p.parse_args(argv)
    console.print(BANNER.replace("{v}", __version__))
    if not a.cmd:
        p.print_help(); return 0
    try:
        if a.cmd == "scan":
            agent.scan(a.token)
        elif a.cmd in ("buy", "trade"):
            eth = a.eth if a.eth is not None else a.eth_max
            if eth is None:
                raise Stop("How much ETH? Example: zyro buy 0x… 0.02")
            agent.buy(a.token, eth, live=a.live, yes=a.yes, sl=a.sl, tp=a.tp, min_score=a.min_score)
        elif a.cmd == "sell":
            agent.sell(a.token, a.percent, live=a.live, yes=a.yes)
        elif a.cmd == "positions":
            agent.positions(a.live)
        elif a.cmd == "watch":
            agent.watch(a.live, a.interval)
        elif a.cmd == "chat":
            ai.chat(a.live)
        elif a.cmd == "init":
            env = C.HOME / ".env"
            if not env.exists() and (C.HOME / ".env.example").exists():
                env.write_text((C.HOME / ".env.example").read_text()); env.chmod(0o600)
            console.print(f"Your settings file:\n  {env}\n\nOpen it with:  nano {env}\n"
                          "Add UNISWAP_API_KEY, PRIVATE_KEY (a new wallet with small funds) and GEMINI_API_KEY. Then try: zyro scan 0x…")
        elif a.cmd == "wallet":
            agent.wallet()
        elif a.cmd == "rules":
            agent.rules()
    except Stop as e:
        console.print(f"[yellow]{e}[/]"); return 1
    except KeyboardInterrupt:
        console.print("\nStopped."); return 130
    except Exception as e:
        console.print(f"[red]Error: {e}[/]"); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
