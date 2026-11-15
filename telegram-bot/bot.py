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
ZYRO_TOKEN_ADDRESS = os.getenv("ZYRO_TOKEN_ADDRESS", "").strip() or "0x50e05d1ee5e545540190a1136667af06a496f6d2"
HOLDER_MIN = float(os.getenv("HOLDER_MIN_BALANCE", "").strip() or "100000")
FREE_SCANS_PER_DAY = int(os.getenv("FREE_SCANS_PER_DAY", "3"))
RPC_URL = os.getenv("RPC_URL", "https://rpc.mainnet.chain.robinhood.com")
EXPLORER = os.getenv("EXPLORER_URL", "https://robinhoodchain.blockscout.com")
BLOCKSCOUT_API_KEY = os.getenv("BLOCKSCOUT_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

CHAIN_ID_DEX = "robinhood"
DATA_FILE = Path(os.getenv("DATA_FILE", "zyro_data.json"))
ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

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

async def dex_token(client: httpx.AsyncClient, address: str) -> list[dict]:
    r = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{address}")
    r.raise_for_status()
    pairs = r.json().get("pairs") or []
    return [p for p in pairs if p.get("chainId") == CHAIN_ID_DEX]

async def dex_trending(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get("https://api.dexscreener.com/token-boosts/top/v1")
    r.raise_for_status()
    items = r.json() if isinstance(r.json(), list) else []
    items = [i for i in items if i.get("chainId") == CHAIN_ID_DEX][:10]
    # look up real names and symbols for the boosted tokens
    names = {}
    addrs = ",".join(i.get("tokenAddress", "") for i in items if i.get("tokenAddress"))
    if addrs:
        try:
            r2 = await client.get(f"https://api.dexscreener.com/tokens/v1/{CHAIN_ID_DEX}/{addrs}")
            if r2.status_code == 200:
                for p in r2.json() or []:
                    bt = p.get("baseToken") or {}
                    a = (bt.get("address") or "").lower()
                    if a and a not in names:
                        names[a] = (bt.get("name") or "", bt.get("symbol") or "")
        except Exception as e:
            log.info("trending name lookup failed: %s", e)
    for i in items:
        i["_name"] = names.get((i.get("tokenAddress") or "").lower())
    return items

def bs(path: str) -> tuple[str, dict]:
    """Blockscout v2 URL: PRO API when a key is set, else the public explorer."""
    if BLOCKSCOUT_API_KEY:
        return f"https://api.blockscout.com/4663/api/v2/{path}", {"apikey": BLOCKSCOUT_API_KEY}
    return f"{EXPLORER}/api/v2/{path}", {}

async def explorer_info(client: httpx.AsyncClient, address: str) -> dict:
    """Contract verification + holder count from Blockscout (best effort)."""
    info = {"verified": None, "holders": None}
    try:
        url, params = bs(f"smart-contracts/{address}")
        r = await client.get(url, params=params)
        if r.status_code == 200:
            info["verified"] = bool(r.json().get("is_verified"))
        elif r.status_code == 404:
            info["verified"] = False
        else:
            log.info("explorer contract lookup: HTTP %s", r.status_code)
    except Exception as e:
        log.info("explorer contract lookup failed: %s", e)
    try:
        url, params = bs(f"tokens/{address}")
        r = await client.get(url, params=params)
        if r.status_code == 200:
            h = r.json().get("holders") or r.json().get("holders_count")
            info["holders"] = int(h) if h is not None else None
        else:
            log.info("explorer token lookup: HTTP %s", r.status_code)
    except Exception as e:
        log.info("explorer token lookup failed: %s", e)
    return info

async def rpc_call(client: httpx.AsyncClient, to: str, data: str) -> str:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
               "params": [{"to": to, "data": data}, "latest"]}
    r = await client.post(RPC_URL, json=payload)
    r.raise_for_status()
    out = r.json()
    if "error" in out or not out.get("result") or out["result"] == "0x":
        raise RuntimeError(f"rpc error: {out.get('error')}")
    return out["result"]

async def zyro_balance(client: httpx.AsyncClient, wallet: str) -> float:
    """ERC-20 balanceOf(wallet) for the ZYRO token, in whole tokens."""
    if not ZYRO_TOKEN_ADDRESS:
        return 0.0
    padded = wallet.lower().replace("0x", "").rjust(64, "0")
    last = None
    for _ in range(3):
        try:
            raw = await rpc_call(client, ZYRO_TOKEN_ADDRESS, "0x70a08231" + padded)
            return int(raw, 16) / 1e18  # $ZYRO uses 18 decimals
        except Exception as e:
            last = e
            await asyncio.sleep(0.6)
    raise last

async def ai_summary(client: httpx.AsyncClient, facts: str) -> str | None:
    if not GEMINI_API_KEY:
        return None
    prompt = (
        "You are Zyro, a crypto token risk analyst. Based ONLY on these facts, "
        "write 3 short bullet points in English: overall read, the biggest risk, "
        "and what to watch next. No price predictions, no financial advice. "
        "Use plain text with '•' bullets.\n\n" + facts
    )
    try:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        log.info("AI summary failed: %s", e)
        return None

def risk_score(pair: dict, chain: dict) -> tuple[int, list[str]]:
    """Return (score 0-100 where higher = safer, list of flags)."""
    score, flags = 100, []
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    fdv = float(pair.get("fdv") or 0)
    vol24 = float((pair.get("volume") or {}).get("h24") or 0)
    tx24 = (pair.get("txns") or {}).get("h24") or {}
    buys, sells = tx24.get("buys", 0), tx24.get("sells", 0)
    created = pair.get("pairCreatedAt")
    age_h = (time.time() * 1000 - created) / 3_600_000 if created else None
    socials = (pair.get("info") or {}).get("socials") or []
    websites = (pair.get("info") or {}).get("websites") or []

    if liq < 5_000:
        score -= 30; flags.append("⚠️ Very low liquidity (under $5K)")
    elif liq < 25_000:
        score -= 15; flags.append("⚠️ Low liquidity (under $25K)")

    if age_h is not None and age_h < 24:
        score -= 15; flags.append("⚠️ New pair (under 24 hours old)")

    if fdv and liq and fdv / liq > 50:
        score -= 10; flags.append("⚠️ FDV is far above liquidity")

    if liq and vol24 / liq > 20:
        score -= 10; flags.append("⚠️ Volume is unusually high for the liquidity")

    if buys > 20 and sells == 0:
        score -= 30; flags.append("🚨 Buys but zero sells: possible honeypot")
    elif buys + sells > 20 and sells / max(buys, 1) > 3:
        score -= 10; flags.append("⚠️ Heavy selling pressure")

    if not socials and not websites:
        score -= 10; flags.append("⚠️ No website or socials listed")

    if chain.get("verified") is False:
        score -= 15; flags.append("⚠️ Contract not verified on the explorer")

    holders = chain.get("holders")
    if holders is not None and holders < 50:
        score -= 10; flags.append(f"⚠️ Few holders ({holders})")

    if chain.get("verified") is None or holders is None:
        score = min(score, 90)
        flags.append("ℹ️ Holder or contract data unavailable, score capped at 90")

    return max(0, min(100, score)), flags

def verdict(score: int) -> str:
    if score >= 75:
        return "🟢 LOW RISK"
    if score >= 50:
        return "🟡 MEDIUM RISK"
    if score >= 25:
        return "🟠 HIGH RISK"
    return "🔴 VERY HIGH RISK"

async def user_tier(client: httpx.AsyncClient, uid: int) -> tuple[str, float]:
    wallet = DATA["wallets"].get(str(uid))
    if not wallet or not ZYRO_TOKEN_ADDRESS:
        return "free", 0.0
    try:
        bal = await zyro_balance(client, wallet)
    except Exception as e:
        log.warning("balance check failed for %s: %s", wallet, e)
        return "error", 0.0
    return ("holder" if bal >= HOLDER_MIN else "free"), bal

HELP = (
    "⚡ <b>Zyro Agent</b> — AI token scanner for Robinhood Chain\n\n"
    "/scan &lt;contract&gt; — check a token's risk\n"
    "/trending — tokens getting attention now\n"
    "/link &lt;wallet&gt; — link your wallet for holder access\n"
    "/me — your tier and scans left\n\n"
    f"Free: {FREE_SCANS_PER_DAY} scans a day, no AI analysis.\n"
    f"Holders of {HOLDER_MIN:,.0f}+ $ZYRO: unlimited scans and AI analysis.\n\n"
    "<i>Always do your own research.</i>"
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(HELP, disable_web_page_preview=True)

async def cmd_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ADDR_RE.match(ctx.args[0]):
        await update.message.reply_html(
            "🔗 <b>Link your wallet for holder access</b>\n\n"
            "Send your Robinhood Chain wallet address like this:\n"
            "<code>/link 0xYourWalletAddress</code>\n\n"
            f"Hold {HOLDER_MIN:,.0f}+ $ZYRO to unlock unlimited scans and AI analysis.\n"
            "Only your public address is needed. Never send a private key or seed phrase."
        )
        return
    DATA["wallets"][str(update.effective_user.id)] = ctx.args[0]
    save_data(DATA)
    async with httpx.AsyncClient(timeout=15) as c:
        tier, bal = await user_tier(c, update.effective_user.id)
    await update.message.reply_html(
        ("✅ Wallet linked.\n⚠️ Could not read your balance right now. Send /me in a minute to check again."
         if tier == "error" else
         f"✅ Wallet linked.\nBalance: <b>{bal:,.0f} $ZYRO</b>\nTier: <b>{tier.upper()}</b>")
        + ("\n\n💎 Holder access is on: unlimited scans and AI analysis." if tier == "holder"
           else "" if tier == "error" else f"\n\nYou need {max(0, HOLDER_MIN - bal):,.0f} more $ZYRO for holder access.")
    )

async def cmd_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with httpx.AsyncClient(timeout=15) as c:
        tier, bal = await user_tier(c, uid)
    wallet = DATA["wallets"].get(str(uid), "not linked. Send /link 0xYourWallet")
    left = "∞" if tier == "holder" else max(0, FREE_SCANS_PER_DAY - scans_used(uid))
    await update.message.reply_html(
        f"👤 Wallet: <code>{esc(wallet)}</code>\n"
        + ("💎 Balance: could not read it right now, try again in a minute\n" if tier == "error" else f"💎 Balance: {bal:,.0f} $ZYRO\n") +
        f"🏷 Tier: <b>{'FREE (balance not checked)' if tier == 'error' else tier.upper()}</b>\n"
        f"🔍 Scans left today: {left}"
    )

async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args or not ADDR_RE.match(ctx.args[0]):
        await update.message.reply_text("Usage: /scan 0xTokenContractAddress")
        return
    address = ctx.args[0]

    async with httpx.AsyncClient(timeout=20) as c:
        tier, _ = await user_tier(c, uid)
        if tier != "holder" and scans_used(uid) >= FREE_SCANS_PER_DAY:
            await update.message.reply_html(
                f"⛔ You have used your {FREE_SCANS_PER_DAY} free scans for today.\n"
                f"Hold {HOLDER_MIN:,.0f}+ $ZYRO and /link your wallet for unlimited scans."
            )
            return

        msg = await update.message.reply_text("🔍 Zyro is scanning...")
        try:
            pairs = await dex_token(c, address)
        except Exception as e:
            log.warning("dexscreener error: %s", e)
            await msg.edit_text("❌ Could not load market data. Try again in a moment.")
            return
        if not pairs:
            await msg.edit_text("❌ No trading pair found for this token on Robinhood Chain.")
            return

        pair = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        chain = await explorer_info(c, address)
        score, flags = risk_score(pair, chain)

        base = pair.get("baseToken", {})
        pc = pair.get("priceChange") or {}
        tx = (pair.get("txns") or {}).get("h24") or {}
        lines = [
            f"⚡ <b>ZYRO SCAN</b> — {esc(base.get('name', '?'))} (${esc(base.get('symbol', '?'))})",
            f"<code>{address}</code>",
            "",
            f"<b>Safety score: {score}/100</b>  {verdict(score)}",
            "",
            f"💵 Price: {fmt_usd(pair.get('priceUsd'))}",
            f"💧 Liquidity: {fmt_usd((pair.get('liquidity') or {}).get('usd'))}",
            f"🏦 FDV: {fmt_usd(pair.get('fdv'))}",
            f"📊 Volume 24h: {fmt_usd((pair.get('volume') or {}).get('h24'))}",
            f"🔁 Txns 24h: {tx.get('buys', 0)} buy / {tx.get('sells', 0)} sell",
            f"⏱ Pair age: {age_text(pair.get('pairCreatedAt'))}",
            f"📈 1h {fmt_pct(pc.get('h1'))} | 24h {fmt_pct(pc.get('h24'))}",
            f"👥 Holders: {chain['holders'] if chain['holders'] is not None else '-'}",
            f"📜 Contract verified: "
            f"{'✅' if chain['verified'] else ('❌' if chain['verified'] is False else '-')}",
            f"🏛 DEX: {esc(pair.get('dexId', '-'))}",
            "",
        ]
        lines += ["<b>Risk notes:</b>"] + (flags or ["✅ No major red flags found"])

        if tier == "holder":
            facts = "\n".join(re.sub("<[^>]+>", "", l) for l in lines)
            summary = await ai_summary(c, facts)
            if summary:
                lines += ["", "🤖 <b>AI analysis</b>", esc(summary)]
        else:
            lines += ["", "🔒 <i>AI analysis is for $ZYRO holders</i>"]

        lines += [
            "",
            f"<a href=\"{pair.get('url', '')}\">DexScreener</a> · "
            f"<a href=\"{EXPLORER}/token/{address}\">Explorer</a>",
        ]
        add_scan(uid)
        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)

async def cmd_trending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            items = await dex_trending(c)
        except Exception as e:
            log.warning("trending error: %s", e)
            await update.message.reply_text("❌ Could not load trending tokens.")
            return
    if not items:
        await update.message.reply_text("No trending tokens on Robinhood Chain right now.")
        return
    lines = ["🔥 <b>Trending on Robinhood Chain</b>", ""]
    for i, it in enumerate(items[:10], 1):
        addr = it.get("tokenAddress", "")
        nm = it.get("_name")
        name = f"{esc(nm[0])} (${esc(nm[1])})" if nm and nm[0] else esc((it.get("description") or addr)[:40])
        lines.append(f"{i}. <a href=\"{it.get('url', '')}\">{name}</a>\n   <code>{addr}</code>")
    lines += ["", "Send /scan &lt;contract&gt; to check one."]
    await update.message.reply_html("\n".join(lines), disable_web_page_preview=True)

def main():
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is missing in the .env file")
    async def set_menu(app):
        await app.bot.set_my_commands([
            BotCommand("scan", "Check a token's risk"),
            BotCommand("trending", "Tokens getting attention now"),
            BotCommand("link", "Link your wallet for holder access"),
            BotCommand("me", "Your tier, balance and scans left"),
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
