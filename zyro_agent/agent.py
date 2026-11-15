"""What the agent does: scan, buy, sell, list positions and watch stop loss / take profit.

Every action runs in simulation unless live=True. Live trades always show the plan
first and ask for confirmation, except inside `watch --live`, which the user arms once.
"""
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from web3 import Web3

from . import config as C, market, state, chain, swap

console = Console()
LEVEL = {"bad": ("✖", "red"), "warn": ("▲", "yellow"), "info": ("•", "cyan")}


class Stop(Exception):
    """Ends an action with a message, without a traceback."""


def is_addr(s: str) -> bool:
    return isinstance(s, str) and s.startswith("0x") and len(s) == 42 and Web3.is_address(s)


def usd(v) -> str:
    if v is None:
        return "n/a"
    v = float(v)
    sign = "-" if v < 0 else ""
    a = abs(v)
    for n, s in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= n:
            return f"{sign}${a / n:,.2f}{s}"
    if a == 0 or a >= 1:
        return f"{sign}${a:,.2f}"
    return f"{sign}${a:.4f}" if a >= 0.01 else f"{sign}${a:.8f}".rstrip("0")

def mode_name(live: bool) -> str:
    return "live" if live else "sim"


def mode_tag(live: bool) -> Text:
    return Text(" LIVE ", style="bold white on red") if live else Text(" SIMULATION ", style="bold black on yellow")


def confirm(prompt: str) -> bool:
    try:
        return console.input(f"[bold]{prompt}[/] [dim](type yes)[/] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ---------- scan ----------

def scan(address: str, show: bool = True) -> dict:
    if not is_addr(address):
        raise Stop("That is not a contract address. It starts with 0x and has 42 characters.")
    with console.status("Scanning token…"):
        r = market.scan(address)
    if not r:
        raise Stop("No trading pair found for this token on Robinhood Chain. "
                   "If it is still on the Pons bonding curve, the agent can trade it after it graduates to Uniswap.")
    if show:
        print_scan(address, r)
    return r


def print_scan(address: str, r: dict) -> None:
    v, col = market.verdict(r["score"])
    p = r["pair"]
    tx = (p.get("txns") or {}).get("h24") or {}
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim"); t.add_column(justify="right")
    t.add_column(style="dim"); t.add_column(justify="right")
    t.add_row("Price", usd(r["price_usd"]), "Liquidity", usd((p.get("liquidity") or {}).get("usd")))
    t.add_row("FDV", usd(p.get("fdv")), "Volume 24h", usd((p.get("volume") or {}).get("h24")))
    t.add_row("Txns 24h", f"{tx.get('buys', 0)} buy / {tx.get('sells', 0)} sell",
              "Holders", str(r["chain"].get("holders") or "n/a"))
    head = Text.assemble((f"{r['score']}", f"bold {col}"), ("/100  ", "dim"), (v, f"bold {col}"),
                         ("   " + f"{r['name']} (${r['symbol']})", "white"))
    flags = Text()
    for lvl, msg in r["flags"] or [("ok", "No red flags found")]:
        icon, c = LEVEL.get(lvl, ("✔", "green"))
        flags.append(f"\n{icon} {msg}", style=c)
    console.print(Panel.fit(head, title="[bold]Zyro scan[/]", border_style=col))
    console.print(t)
    console.print(flags)
    console.print()


# ---------- rules ----------

def rule_check(r: dict, eth_amount: float, b: dict, min_score: float | None) -> list[str]:
    fails = []
    need = max(C.MIN_SCORE, min_score or 0)
    if r["score"] < need:
        fails.append(f"Score {r['score']} is below your minimum of {need:g}")
    if eth_amount > C.MAX_TRADE_ETH:
        fails.append(f"{eth_amount:g} ETH is above your max per trade of {C.MAX_TRADE_ETH:g} ETH")
    if eth_amount <= 0:
        fails.append("Amount must be more than 0")
    lost = -state.realised_today(b)
    if lost >= C.MAX_DAILY_LOSS_USD:
        fails.append(f"Daily loss limit reached ({usd(lost)} of {usd(C.MAX_DAILY_LOSS_USD)} today, UTC)")
    if len(b["positions"]) >= C.MAX_OPEN_POSITIONS:
        fails.append(f"Already {len(b['positions'])} open positions (max {C.MAX_OPEN_POSITIONS})")
    return fails


# ---------- buy ----------

def buy(address: str, eth_amount: float, live: bool = False, yes: bool = False,
        sl: float | None = None, tp: float | None = None, min_score: float | None = None) -> None:
    console.print(mode_tag(live), f" Buy {eth_amount:g} ETH of {address}")
    r = scan(address)
    b = state.book(mode_name(live))
    fails = rule_check(r, eth_amount, b, min_score)
    if fails:
        console.print("[bold red]Trade skipped. Your rules said no:[/]")
        for f in fails:
            console.print(f"  [red]✖[/] {f}")
        return
    console.print("[green]✔ Passed your rules[/]")

    amount_raw = Web3.to_wei(eth_amount, "ether")
    ethp = market.eth_usd()
    wallet = chain.address() if live or C.PRIVATE_KEY else None
    if live:
        bal = chain.eth_balance(wallet)
        if bal < amount_raw + Web3.to_wei(C.GAS_RESERVE_ETH, "ether"):
            raise Stop(f"Not enough ETH. Wallet has {Web3.from_wei(bal, 'ether'):.5f} ETH, "
                       f"needs {eth_amount + C.GAS_RESERVE_ETH:.5f} ETH including gas.")

    dec = int(r["pair"].get("baseToken", {}).get("decimals") or 0) or (chain.decimals(address) if live else 18)
    q = None
    if C.UNISWAP_API_KEY:
        with console.status("Getting the best Uniswap route…"):
            try:
                q = swap.quote(C.NATIVE, address, amount_raw, wallet or "0x000000000000000000000000000000000000dEaD")
            except swap.NoRoute:
                raise Stop("Uniswap has no route for this token. If it is still on the Pons bonding curve, "
                           "the agent can trade it after it graduates.")
    elif live:
        raise Stop("UNISWAP_API_KEY is not set in .env. Live trades need it.")

    if q:
        out_raw = swap.amount_out(q)
        tokens = out_raw / 10 ** dec
    else:
        tokens = eth_amount * ethp / r["price_usd"] if r["price_usd"] else 0
        out_raw = int(tokens * 10 ** dec)

    sl = C.STOP_LOSS_PCT if sl is None else sl
    tp = C.TAKE_PROFIT_PCT if tp is None else tp
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]You pay[/]", f"{eth_amount:g} ETH  [dim]({usd(eth_amount * ethp)})[/]")
    t.add_row("[dim]You get[/]", f"≈ {tokens:,.4f} {r['symbol']}" + ("" if q else "  [dim](estimate, no Uniswap quote)[/]"))
    if q:
        pi = swap.price_impact(q)
        t.add_row("[dim]Price impact[/]", f"{pi:.2f}%" if pi is not None else "n/a")
        t.add_row("[dim]Network fee[/]", usd(swap.gas_usd(q)))
    t.add_row("[dim]Max slippage[/]", f"{C.SLIPPAGE_PCT:g}%")
    t.add_row("[dim]Stop loss / take profit[/]", f"-{sl:g}% / +{tp:g}%")
    console.print(Panel(t, title="Order", border_style="blue", expand=False))
    if q and (swap.price_impact(q) or 0) > 10:
        console.print("[yellow]▲ Price impact is above 10%. The pool is thin for this size.[/]")

    if live:
        if not yes and not confirm("Send this buy on Robinhood Chain?"):
            console.print("Cancelled. Nothing was sent."); return
        before = chain.token_balance(address, wallet)
        with console.status("Sending swap…"):
            tx = swap.swap_tx(q, Web3.to_hex(chain.account().key))
            h, ok = chain.send(tx)
        if not ok:
            raise Stop(f"Swap failed on chain: {chain.tx_url(h)}")
        out_raw = chain.token_balance(address, wallet) - before
        tokens = out_raw / 10 ** dec
        console.print(f"[green]✔ Bought {tokens:,.4f} {r['symbol']}[/]  {chain.tx_url(h)}")
    else:
        console.print("[yellow]Simulated.[/] Nothing was sent. Add [bold]--live[/] to trade for real.")

    pos = b["positions"].get(address.lower())
    cost_usd = eth_amount * ethp
    if pos:
        pos["amount_raw"] = str(int(pos["amount_raw"]) + out_raw)
        pos["cost_eth"] += eth_amount; pos["cost_usd"] += cost_usd
        pos["sl"], pos["tp"] = sl, tp
    else:
        b["positions"][address.lower()] = {"address": address, "symbol": r["symbol"], "decimals": dec,
                                           "amount_raw": str(out_raw), "cost_eth": eth_amount, "cost_usd": cost_usd,
                                           "sl": sl, "tp": tp, "opened": int(time.time())}
    state.log_trade(b, side="buy", token=address, symbol=r["symbol"], eth=eth_amount, usd=cost_usd, tokens=tokens)
    state.save_book(mode_name(live), b)


# ---------- sell ----------

def find_position(b: dict, token: str):
    return b["positions"].get(token.lower())


def sell(address: str, percent: float = 100, live: bool = False, yes: bool = False, reason: str = "manual") -> None:
    if not is_addr(address):
        raise Stop("That is not a contract address.")
    if not 0 < percent <= 100:
        raise Stop("Percent must be between 1 and 100.")
    b = state.book(mode_name(live))
    pos = find_position(b, address)
    console.print(mode_tag(live), f" Sell {percent:g}% of {pos['symbol'] if pos else address}  [dim]({reason})[/]")
    wallet = chain.address() if live else (chain.address() if C.PRIVATE_KEY else None)

    if live:
        held = chain.token_balance(address, wallet)
        dec = pos["decimals"] if pos else chain.decimals(address)
    else:
        if not pos:
            raise Stop("No simulated position in this token.")
        held, dec = int(pos["amount_raw"]), pos["decimals"]
    if held <= 0:
        raise Stop("Nothing to sell. The wallet holds none of this token.")
    amount_raw = held if percent >= 100 else held * int(percent * 100) // 10000
    p = market.best_pair(address)
    price = float(p["priceUsd"]) if p and p.get("priceUsd") else 0
    ethp = market.eth_usd()
    symbol = (pos or {}).get("symbol") or ((p or {}).get("baseToken") or {}).get("symbol") or "?"

    q = None
    if C.UNISWAP_API_KEY:
        with console.status("Getting the best Uniswap route…"):
            try:
                q = swap.quote(address, C.NATIVE, amount_raw, wallet or "0x000000000000000000000000000000000000dEaD")
            except swap.NoRoute:
                raise Stop("Uniswap has no route to sell this token right now.")
    elif live:
        raise Stop("UNISWAP_API_KEY is not set in .env. Live trades need it.")
    eth_out = swap.amount_out(q) / 1e18 if q else (amount_raw / 10 ** dec) * price / ethp

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]You sell[/]", f"{amount_raw / 10 ** dec:,.4f} {symbol}")
    t.add_row("[dim]You get[/]", f"≈ {eth_out:.6f} ETH  [dim]({usd(eth_out * ethp)})[/]" + ("" if q else "  [dim](estimate)[/]"))
    if q:
        t.add_row("[dim]Network fee[/]", usd(swap.gas_usd(q)))
    console.print(Panel(t, title="Order", border_style="blue", expand=False))

    if live:
        if not yes and not confirm("Send this sell on Robinhood Chain?"):
            console.print("Cancelled. Nothing was sent."); return
        acct = chain.account()
        with console.status("Checking token approval…"):
            appr = swap.approval_tx(address, amount_raw, wallet)
        if appr:
            with console.status("Approving token for Uniswap…"):
                h, ok = chain.send(appr)
            if not ok:
                raise Stop(f"Approval failed: {chain.tx_url(h)}")
            q = swap.quote(address, C.NATIVE, amount_raw, wallet)  # fresh quote after approval
        before = chain.eth_balance(wallet)
        with console.status("Sending swap…"):
            tx = swap.swap_tx(q, Web3.to_hex(acct.key))
            h, ok = chain.send(tx)
        if not ok:
            raise Stop(f"Swap failed on chain: {chain.tx_url(h)}")
        console.print(f"[green]✔ Sold for ≈ {eth_out:.6f} ETH[/]  {chain.tx_url(h)}")
    else:
        console.print("[yellow]Simulated.[/] Nothing was sent.")

    got_usd = eth_out * ethp
    pnl = None
    if pos:
        frac = amount_raw / int(pos["amount_raw"]) if int(pos["amount_raw"]) else 1
        cost = pos["cost_usd"] * frac
        pnl = got_usd - cost
        if frac >= 0.9999 or percent >= 100:
            b["positions"].pop(address.lower(), None)
        else:
            pos["amount_raw"] = str(int(pos["amount_raw"]) - amount_raw)
            pos["cost_usd"] -= cost; pos["cost_eth"] -= pos["cost_eth"] * frac
        b["daily"][state.today()] = state.realised_today(b) + pnl
        col = "green" if pnl >= 0 else "red"
        console.print(f"Result: [{col}]{'+' if pnl >= 0 else ''}{usd(pnl)}[/]")
    state.log_trade(b, side="sell", token=address, symbol=symbol, eth=eth_out, usd=got_usd, pnl=pnl, reason=reason)
    state.save_book(mode_name(live), b)


# ---------- positions & watch ----------

def position_rows(b: dict):
    rows = []
    for addr, pos in b["positions"].items():
        p = market.best_pair(pos["address"])
        price = float(p["priceUsd"]) if p and p.get("priceUsd") else None
        amt = int(pos["amount_raw"]) / 10 ** pos["decimals"]
        value = amt * price if price is not None else None
        pnl_pct = (value - pos["cost_usd"]) / pos["cost_usd"] * 100 if value is not None and pos["cost_usd"] else None
        rows.append((pos, amt, price, value, pnl_pct))
    return rows


def positions(live: bool = False) -> None:
    b = state.book(mode_name(live))
    console.print(mode_tag(live), " Positions")
    if not b["positions"]:
        console.print("[dim]No open positions.[/]")
    else:
        t = Table()
        for c in ("Token", "Amount", "Cost", "Value", "P/L", "Stop / Target"):
            t.add_column(c, justify="right" if c != "Token" else "left")
        for pos, amt, price, value, pnl in position_rows(b):
            col = "green" if (pnl or 0) >= 0 else "red"
            t.add_row(f"${pos['symbol']}", f"{amt:,.2f}", usd(pos["cost_usd"]), usd(value),
                      f"[{col}]{pnl:+.1f}%[/]" if pnl is not None else "n/a", f"-{pos['sl']:g}% / +{pos['tp']:g}%")
        console.print(t)
    r = state.realised_today(b)
    console.print(f"Realised today (UTC): [{'green' if r >= 0 else 'red'}]{usd(r)}[/]   Daily loss limit: {usd(C.MAX_DAILY_LOSS_USD)}")


def watch(live: bool = False, interval: int | None = None) -> None:
    interval = interval or C.WATCH_INTERVAL
    console.print(mode_tag(live), f" Watching positions every {interval}s. Press Ctrl+C to stop.")
    if live and not confirm("The agent will SELL automatically when a stop loss or take profit hits. Start?"):
        console.print("Not started."); return
    while True:
        try:
            b = state.book(mode_name(live))
            stamp = time.strftime("%H:%M:%S", time.gmtime())
            if not b["positions"]:
                console.print(f"[dim]{stamp} UTC  no open positions[/]")
            for pos, amt, price, value, pnl in position_rows(b):
                if pnl is None:
                    continue
                col = "green" if pnl >= 0 else "red"
                console.print(f"[dim]{stamp} UTC[/]  ${pos['symbol']:<10} [{col}]{pnl:+6.1f}%[/]  value {usd(value)}")
                reason = "stop loss" if pnl <= -pos["sl"] else "take profit" if pnl >= pos["tp"] else None
                if reason:
                    console.print(f"[bold]{reason.title()} hit for ${pos['symbol']}[/]")
                    try:
                        sell(pos["address"], 100, live=live, yes=True, reason=reason)
                    except Stop as e:
                        console.print(f"[red]{e}[/]")
            time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\nStopped watching."); return
        except Exception as e:
            console.print(f"[red]Watch error: {e}. Retrying.[/]")
            time.sleep(interval)


def wallet() -> None:
    a = chain.address()
    if not a:
        console.print("No wallet set. Add PRIVATE_KEY to .env to trade live. Simulation works without it.")
        return
    bal = chain.eth_balance(a)
    console.print(f"Wallet  {a}\nETH     {Web3.from_wei(bal, 'ether'):.6f}  ({usd(float(Web3.from_wei(bal, 'ether')) * market.eth_usd())})")


def rules() -> None:
    t = Table(title="Your trading rules (.env)", show_header=False)
    for k, v in [("MIN_SCORE", C.MIN_SCORE), ("MAX_TRADE_ETH", C.MAX_TRADE_ETH), ("MAX_DAILY_LOSS_USD", C.MAX_DAILY_LOSS_USD),
                 ("MAX_OPEN_POSITIONS", C.MAX_OPEN_POSITIONS), ("STOP_LOSS_PCT", C.STOP_LOSS_PCT),
                 ("TAKE_PROFIT_PCT", C.TAKE_PROFIT_PCT), ("SLIPPAGE_PCT", C.SLIPPAGE_PCT), ("WATCH_INTERVAL", C.WATCH_INTERVAL)]:
        t.add_row(k, f"{v:g}" if isinstance(v, float) else str(v))
    console.print(t)
