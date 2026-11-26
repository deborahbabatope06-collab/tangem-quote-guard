#!/usr/bin/env bash
# One-step setup for macOS and Linux.
#   ./scripts/setup.sh            install, test, and add both MCP servers to Claude Code
#   ./scripts/setup.sh --no-mcp   install and test only
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

PY="${PYTHON:-$(command -v python3 || command -v python || true)}"
if [ -z "$PY" ]; then echo "Python 3.10+ not found. Install it from python.org and retry."; exit 1; fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Python 3.10+ needed, found $("$PY" --version 2>&1)."; exit 1; }

echo "== Creating virtual environment in .venv"
"$PY" -m venv .venv
VENV_PY="$ROOT/.venv/bin/python"
"$VENV_PY" -m pip install --quiet --upgrade pip

echo "== Installing"
# --only-binary=cryptography: avoids a Rust source build on platforms (e.g. Intel Macs)
# where the newest cryptography release has no prebuilt wheel.
"$VENV_PY" -m pip install --quiet --prefer-binary --only-binary=cryptography -e ".[dev]"

echo "== Tests"
"$VENV_PY" -m pytest -q
echo "== Demo"
"$VENV_PY" -m quote_guard.demo

if [ "${1:-}" = "--no-mcp" ]; then exit 0; fi

CLAUDE="$(command -v claude || true)"
[ -z "$CLAUDE" ] && [ -x "$HOME/.local/bin/claude" ] && CLAUDE="$HOME/.local/bin/claude"
echo
if [ -n "$CLAUDE" ]; then
  echo "== Adding MCP servers to Claude Code (user scope, works from any folder)"
  "$CLAUDE" mcp add --scope user --transport http tangem https://mcp.tangem.org/mcp || true
  "$CLAUDE" mcp add --scope user quote-guard -- "$VENV_PY" -m quote_guard.server || true
  "$CLAUDE" mcp list || true
  echo
  echo "Done. Run 'claude' and ask it to list your Tangem tokens; scan the QR code with the Tangem app to sign in."
else
  echo "Claude Code not found, so the MCP servers were not added. Install it, then run:"
  echo "  claude mcp add --scope user --transport http tangem https://mcp.tangem.org/mcp"
  echo "  claude mcp add --scope user quote-guard -- \"$VENV_PY\" -m quote_guard.server"
fi
