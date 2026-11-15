#!/usr/bin/env node
// Zyro agent launcher for npm. Sets up a private Python environment in ~/.zyro on first run,
// then passes every command through to the Python agent.
const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");

const PKG = path.resolve(__dirname, "..");
const HOME = process.env.ZYRO_HOME || path.join(os.homedir(), ".zyro");
const VENV = path.join(HOME, "venv");
const WIN = process.platform === "win32";
const VPY = path.join(VENV, WIN ? "Scripts" : "bin", WIN ? "python.exe" : "python");
const REQ = path.join(PKG, "requirements.txt");
const ENV_FILE = path.join(HOME, ".env");

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", ...opts });
  return r.status === null ? 1 : r.status;
}

function findPython() {
  for (const c of WIN ? ["py", "python", "python3"] : ["python3", "python"]) {
    const r = spawnSync(c, ["-c", "import sys; print(sys.version_info >= (3, 10))"], { encoding: "utf8" });
    if (r.status === 0 && r.stdout.trim() === "True") return c;
  }
  return null;
}

function ensureEnv() {
  fs.mkdirSync(HOME, { recursive: true });
  if (!fs.existsSync(ENV_FILE)) {
    fs.copyFileSync(path.join(PKG, ".env.example"), ENV_FILE);
    try { fs.chmodSync(ENV_FILE, 0o600); } catch (_) {}
  }
  const want = crypto.createHash("sha1").update(fs.readFileSync(REQ)).digest("hex");
  const stamp = path.join(VENV, ".zyro-req");
  if (fs.existsSync(VPY) && fs.existsSync(stamp) && fs.readFileSync(stamp, "utf8") === want) return;
  const py = findPython();
  if (!py) {
    console.error("Zyro needs Python 3.10 or newer. On Ubuntu: sudo apt install -y python3 python3-venv");
    process.exit(1);
  }
  console.log("Setting up Zyro in " + HOME + " (first run only)…");
  if (!fs.existsSync(VPY) && run(py, ["-m", "venv", VENV]) !== 0) {
    console.error("Could not create a Python environment. On Ubuntu: sudo apt install -y python3-venv");
    process.exit(1);
  }
  if (run(VPY, ["-m", "pip", "install", "-q", "--upgrade", "pip"]) !== 0 ||
      run(VPY, ["-m", "pip", "install", "-q", "-r", REQ]) !== 0) {
    console.error("Installing Python packages failed. Check your internet connection and run the command again.");
    process.exit(1);
  }
  fs.writeFileSync(stamp, want);
}

const args = process.argv.slice(2);
ensureEnv();

if (args[0] === "init" || args[0] === "config") {
  console.log("Your settings file:\n  " + ENV_FILE + "\n\nOpen it with:\n  nano " + ENV_FILE +
    "\n\nAdd UNISWAP_API_KEY for quotes and live trades, PRIVATE_KEY for a trading wallet (use a new wallet with small funds),\nand GEMINI_API_KEY for chat mode. Then try:  zyro scan 0x…");
  process.exit(0);
}

const env = { ...process.env, ZYRO_HOME: HOME, PYTHONPATH: PKG + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : "") };
process.exit(run(VPY, ["-m", "zyro_agent.cli", ...args], { env }));
