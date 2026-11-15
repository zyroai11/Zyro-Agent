"""Settings and trading rules, read from the .env file next to the agent."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Settings live in ZYRO_HOME (set by the npm launcher, ~/.zyro), or next to the code for a git install.
HOME = Path(os.getenv("ZYRO_HOME") or Path(__file__).resolve().parent.parent)
load_dotenv(HOME / ".env")

def _f(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)

CHAIN_ID = 4663
CHAIN_DEX = "robinhood"
RPC_URL = os.getenv("RPC_URL", "https://rpc.mainnet.chain.robinhood.com")
EXPLORER = os.getenv("EXPLORER_URL", "https://robinhoodchain.blockscout.com")
BLOCKSCOUT_API_KEY = os.getenv("BLOCKSCOUT_API_KEY", "").strip()

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "").strip()
UNISWAP_API_KEY = os.getenv("UNISWAP_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

NATIVE = "0x0000000000000000000000000000000000000000"
WETH = "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"

# Trading rules. Every buy is checked against these before anything is sent.
MIN_SCORE = _f("MIN_SCORE", 60)                    # skip tokens scoring below this
MAX_TRADE_ETH = _f("MAX_TRADE_ETH", 0.05)          # largest single buy, in ETH
MAX_DAILY_LOSS_USD = _f("MAX_DAILY_LOSS_USD", 50)  # stop buying after this realised loss today (UTC)
MAX_OPEN_POSITIONS = int(_f("MAX_OPEN_POSITIONS", 5))
STOP_LOSS_PCT = _f("STOP_LOSS_PCT", 15)            # default stop loss per position
TAKE_PROFIT_PCT = _f("TAKE_PROFIT_PCT", 50)        # default take profit per position
SLIPPAGE_PCT = _f("SLIPPAGE_PCT", 3)
WATCH_INTERVAL = int(_f("WATCH_INTERVAL", 20))     # seconds between price checks
GAS_RESERVE_ETH = _f("GAS_RESERVE_ETH", 0.0005)    # ETH kept aside for gas

STATE_FILE = Path(os.getenv("STATE_FILE", HOME / "zyro_state.json"))
