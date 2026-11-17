import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
FREE_SCANS_PER_DAY = int(os.getenv("FREE_SCANS_PER_DAY", "3"))

SITE_API = os.getenv("SITE_API", "https://www.zyro-ai.xyz").rstrip("/")
DATA_FILE = Path(os.getenv("DATA_FILE", "zyro_data.json"))
# Solana mint addresses (base58) and Robinhood Chain contracts (0x...)
SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
def is_token(a: str) -> bool:
    return bool(SOL_RE.match(a or "") or EVM_RE.match(a or ""))

_CLIENT: httpx.AsyncClient | None = None
def client() -> httpx.AsyncClient:
    """One shared HTTP client, so connections are reused between commands."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(12, connect=4),
                                    headers={"User-Agent": "zyro-bot/1.0"}, follow_redirects=True)
    return _CLIENT

TREND_CACHE: dict[str, tuple[float, list]] = {}
TREND_TTL = 60

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("zyro")

def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            log.warning("Data file unreadable, starting fresh")
    return {"wallets": {}, "usage": {}}

def save_data(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, indent=2))

DATA = load_data()

def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def scans_used(uid: int) -> int:
    u = DATA["usage"].get(str(uid), {})
    return u.get("count", 0) if u.get("day") == today() else 0

def add_scan(uid: int) -> None:
    DATA["usage"][str(uid)] = {"day": today(), "count": scans_used(uid) + 1}
    save_data(DATA)

def fmt_usd(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    if v >= 1e3:
        return f"${v/1e3:.1f}K"
    if v >= 1:
        return f"${v:,.2f}"
    return f"${v:.8f}".rstrip("0")

def fmt_pct(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return f"{'🟢' if v >= 0 else '🔴'} {v:+.1f}%"

def age_text(created_ms) -> str:
    if not created_ms:
        return "unknown"
    hours = (time.time() * 1000 - created_ms) / 3_600_000
    if hours < 1:
        return f"{int(hours*60)}m"
    if hours < 48:
        return f"{hours:.0f}h"
    return f"{hours/24:.0f}d"

def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

async def site_scan(c: httpx.AsyncClient, address: str) -> dict:
    """The same scan as zyro-ai.xyz/app: Solana via DexScreener + RugCheck, Robinhood Chain via DexScreener + Blockscout."""
    r = await c.get(f"{SITE_API}/api/scan", params={"address": address})
    return r.json()

async def site_ai(c: httpx.AsyncClient, address: str) -> dict | None:
    try:
        r = await c.post(f"{SITE_API}/api/holder", json={"address": address}, timeout=35)
        d = r.json()
        return None if d.get("error") else d
    except Exception as e:
        log.info("AI analysis failed: %s", e)
        return None

async def site_trending(c: httpx.AsyncClient, chain: str) -> list[dict]:
    r = await c.get(f"{SITE_API}/api/trending", params={"chain": chain})
    r.raise_for_status()
    return r.json().get("tokens") or []

def verdict(score: int) -> str:
    if score >= 75:
        return "🟢 LOW RISK"
    if score >= 50:
        return "🟡 MEDIUM RISK"
    if score >= 25:
        return "🟠 HIGH RISK"
    return "🔴 VERY HIGH RISK"

ICON = {"ok": "✅", "warn": "⚠️", "bad": "🚨", "unknown": "ℹ️"}

HELP = (
    "⚡ <b>Zyro</b> — the AI agent for Solana\n\n"
    "/scan &lt;token address&gt; — safety score for a Solana token (Robinhood Chain 0x addresses work too)\n"
    "/trending — what is getting attention on Solana\n"
    "/trending robinhood — the same for Robinhood Chain\n"
    "/me — scans left today\n\n"
    f"{FREE_SCANS_PER_DAY} free scans a day, AI analysis included. Unlimited scans at zyro-ai.xyz/app\n\n"
    "🚀 $ZYRO is launching soon on StonkFun. No contract address yet: only trust the launch post on X @ZyroxRH.\n\n"
    "<i>Always do your own research.</i>"
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(HELP, disable_web_page_preview=True)

async def cmd_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    left = max(0, FREE_SCANS_PER_DAY - scans_used(update.effective_user.id))
    await update.message.reply_html(
        f"🔍 Scans left today: <b>{left}</b> of {FREE_SCANS_PER_DAY}\n"
        "They reset at 00:00 UTC. Unlimited scans on the web: zyro-ai.xyz/app",
        disable_web_page_preview=True)

async def cmd_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "Holder access is paused while $ZYRO moves to Solana.\n"
        "$ZYRO is launching soon on StonkFun. Until then AI analysis is free for everyone.")

async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    address = (ctx.args[0].strip() if ctx.args else "")
    if not is_token(address):
        await update.message.reply_html("Send a token address like this:\n<code>/scan DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263</code>\n\nSolana mint addresses and Robinhood Chain 0x contracts both work.")
        return
    if scans_used(uid) >= FREE_SCANS_PER_DAY:
        await update.message.reply_html(
            f"⛔ You have used your {FREE_SCANS_PER_DAY} free scans for today.\n"
            f"Scan without limits on the web: <a href=\"https://zyro-ai.xyz/app?token={address}\">zyro-ai.xyz/app</a>",
            disable_web_page_preview=True)
        return
    c = client()
    msg = await update.message.reply_text("🔍 Zyro is scanning...")
    try:
        d = await site_scan(c, address)
    except Exception as e:
        log.warning("scan error: %s", e)
        await msg.edit_text("❌ Could not load market data. Try again in a moment.")
        return
    if d.get("error"):
        await msg.edit_text("❌ " + d["error"])
        return

    tok, m, links = d.get("token") or {}, d.get("market") or {}, d.get("links") or {}
    sol = d.get("chain") == "solana"
    lines = [
        f"⚡ <b>ZYRO SCAN</b> — {esc(tok.get('name', '?'))} (${esc(tok.get('symbol', '?'))})",
        f"{'◎ Solana' if sol else '⛓ Robinhood Chain'}",
        f"<code>{esc(address)}</code>",
        "",
        f"<b>Safety score: {d.get('score')}/100</b>  {verdict(int(d.get('score') or 0))}",
        "",
        f"💵 Price: {fmt_usd(m.get('price'))}",
        f"💧 Liquidity: {fmt_usd(m.get('liquidity'))}",
        f"🏦 FDV: {fmt_usd(m.get('fdv'))}",
        f"📊 Volume 24h: {fmt_usd(m.get('volume24h'))}",
        f"🔁 Txns 24h: {m.get('buys24h', 0)} buy / {m.get('sells24h', 0)} sell",
        f"⏱ Pair age: {age_text(m.get('pairCreatedAt'))}",
        f"📈 24h {fmt_pct(m.get('change24h'))}",
        "👥 Holders: " + (f"{m['holders']:,}" if m.get("holders") is not None else "-"),
        "",
        "<b>What Zyro checked:</b>",
    ]
    for k in d.get("checks") or []:
        pts = f" (−{k['points']})" if k.get("points") else ""
        lines.append(f"{ICON.get(k.get('status'), '•')} {esc(k.get('detail', ''))}{pts}")
    if d.get("capped"):
        lines.append("ℹ️ Some data was unavailable, so the score is capped at 90")
    link_parts = []
    if links.get("chart"): link_parts.append(f"<a href=\"{links['chart']}\">DexScreener</a>")
    if links.get("explorer"): link_parts.append(f"<a href=\"{links['explorer']}\">{'Solscan' if sol else 'Explorer'}</a>")
    if links.get("rugcheck"): link_parts.append(f"<a href=\"{links['rugcheck']}\">RugCheck</a>")
    link_parts.append(f"<a href=\"https://zyro-ai.xyz/app?token={address}\">Full report</a>")
    links_l = ["", " · ".join(link_parts)]
    add_scan(uid)

    await msg.edit_text("\n".join(lines + ["", "🤖 <i>AI analysis is loading...</i>"] + links_l),
                        parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    ai = await site_ai(c, address)
    tail = ["", "🤖 <b>AI analysis</b>", f"• {esc(ai['read'])}", f"• Biggest risk: {esc(ai['risk'])}", f"• Watch: {esc(ai['watch'])}"] if ai else []
    try:
        await msg.edit_text("\n".join(lines + tail + links_l), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        log.info("AI edit failed: %s", e)

async def cmd_trending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chain = "robinhood" if ctx.args and ctx.args[0].lower().startswith("rob") else "solana"
    hit = TREND_CACHE.get(chain)
    if hit and time.time() - hit[0] < TREND_TTL:
        items = hit[1]
    else:
        try:
            items = await site_trending(client(), chain)
            TREND_CACHE[chain] = (time.time(), items)
        except Exception as e:
            log.warning("trending error: %s", e)
            await update.message.reply_text("❌ Could not load trending tokens.")
            return
    label = "Solana" if chain == "solana" else "Robinhood Chain"
    if not items:
        await update.message.reply_text(f"No trending tokens on {label} right now.")
        return
    lines = [f"🔥 <b>Trending on {label}</b>", ""]
    for i, t in enumerate(items[:10], 1):
        lines.append(f"{i}. <b>{esc(t.get('name', '?'))}</b> (${esc(t.get('symbol', '?'))})  {fmt_pct(t.get('change24h'))}\n"
                     f"   Liq {fmt_usd(t.get('liquidity'))}\n   <code>{t.get('address', '')}</code>")
    lines += ["", "Send /scan &lt;address&gt; to check one."]
    await update.message.reply_html("\n".join(lines), disable_web_page_preview=True)

def main():
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing in the .env file")
    async def set_menu(app):
        await app.bot.set_my_commands([
            BotCommand("scan", "Safety score for a Solana token"),
            BotCommand("trending", "Trending on Solana"),
            BotCommand("me", "Scans left today"),
            BotCommand("help", "How Zyro works"),
        ])
    app = Application.builder().token(BOT_TOKEN).post_init(set_menu).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("trending", cmd_trending))
    app.add_handler(CommandHandler("link", cmd_link))
    app.add_handler(CommandHandler("me", cmd_me))
    log.info("Zyro bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
