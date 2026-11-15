#!/usr/bin/env bash
# Installs the Zyro agent: a Python virtualenv, the packages, and the `zyro` command.
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "python3 is missing: sudo apt install -y python3 python3-venv"; exit 1; }
python3 -m venv .venv 2>/dev/null || { echo "Run: sudo apt install -y python3-venv   then run ./install.sh again"; exit 1; }
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
chmod 600 .env
mkdir -p "$HOME/.local/bin"
ln -sf "$(pwd)/zyro" "$HOME/.local/bin/zyro"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"; echo "Added ~/.local/bin to PATH. Open a new terminal or run: source ~/.bashrc";; esac
echo
echo "Zyro agent installed. Next:"
echo "  1. nano $(pwd)/.env      (add your keys and rules)"
echo "  2. zyro scan 0x...       (try a scan)"
