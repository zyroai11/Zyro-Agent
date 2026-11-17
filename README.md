# Zyro agent

Scan and trade Robinhood Chain tokens from your terminal. Every buy is scanned and checked against your own rules first, and open positions can be watched for a stop loss or take profit.

Everything runs in **simulation** unless you add `--live`. Live trades show the order and ask you to type `yes` before anything is sent.

## Install

**With npm** (needs Node 18+ and Python 3.10+):

```bash
npm install -g zyro-agent
zyro init          # creates ~/.zyro/.env and shows where it is
nano ~/.zyro/.env  # add your keys and rules
zyro scan 0x…
```

Or run it once without installing: `npx zyro-agent scan 0x…`

**From GitHub** (Ubuntu or WSL):

```bash
git clone https://github.com/zyroai11/Zyro-Agent.git
cd Zyro-Agent
./install.sh
nano .env
```

### Keys in .env

| Key | Needed for |
|---|---|
| `UNISWAP_API_KEY` | Real quotes and live trades. Free at developers.uniswap.org |
| `PRIVATE_KEY` | Live trades. Use a new wallet with only what you want to trade |
| `GEMINI_API_KEY` | Chat mode. Free at aistudio.google.com |
| `BLOCKSCOUT_API_KEY` | Holder count and contract checks in the score (optional) |

## Commands

| Command | What it does |
|---|---|
| `zyro scan 0x…` | Safety score and every warning for a token |
| `zyro buy 0x… 0.02` | Buy with 0.02 ETH, after the scan and your rules |
| `zyro trade 0x… --max 0.02eth` | Same as buy |
| `zyro sell 0x… 50` | Sell 50% of a position (`all` sells everything) |
| `zyro positions` | Open positions, profit or loss, today's result |
| `zyro watch` | Checks prices and sells when a stop loss or take profit hits |
| `zyro chat` | Talk to the agent in plain language |
| `zyro wallet` | Wallet address and ETH balance |
| `zyro rules` | Your trading rules |

Add `--live` to `buy`, `sell`, `positions`, `watch` and `chat` to use your real wallet. Buy also takes `--sl 10 --tp 40 --min-score 70`.

## Rules (in .env)

| Setting | Default | Meaning |
|---|---|---|
| `MIN_SCORE` | 60 | Skip tokens that score below this |
| `MAX_TRADE_ETH` | 0.05 | Largest single buy |
| `MAX_DAILY_LOSS_USD` | 50 | No more buys after this realised loss today (UTC) |
| `MAX_OPEN_POSITIONS` | 5 | Most positions open at once |
| `STOP_LOSS_PCT` | 15 | Default stop loss per position |
| `TAKE_PROFIT_PCT` | 50 | Default take profit per position |
| `SLIPPAGE_PCT` | 3 | Max slippage on a swap |

## How trades are routed

Swaps go through the Uniswap Trading API, which finds the best route across Uniswap v2, v3 and v4 pools on Robinhood Chain. A token that is still on the Pons bonding curve has no Uniswap pool yet, so the agent can trade it once it graduates.

## Safety

- Use a new wallet that holds only what you are willing to trade.
- Your private key stays in `.env` on your machine. Never share that file.
- Simulation and live positions are tracked separately in `zyro_state.json`.
- The score reads public data at the moment of the scan. It is not a guarantee.

## Links

- Website: https://zyro-ai.xyz
- Telegram bot: https://t.me/ZyroAiAgent_bot
- X: https://x.com/zyroxstonk
- $ZYRO on Robinhood Chain: `0x50e05d1ee5e545540190a1136667af06a496f6d2`
