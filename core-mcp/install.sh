#!/usr/bin/env bash
# install.sh — set up core-mcp and register it with Claude Code
set -euo pipefail

die()  { echo "❌  $*" >&2; exit 1; }
ok()   { echo "✅  $*"; }
info() { echo "▶  $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_SCRIPT="$SCRIPT_DIR/core_mcp.py"

# ── 1. install the mcp package ─────────────────────────────────────────────────

info "Installing mcp Python package…"
pip3 install --quiet "mcp[cli]"
ok "mcp installed ($(pip3 show mcp | grep Version))"

# ── 2. make the server executable ──────────────────────────────────────────────

chmod +x "$MCP_SCRIPT"
ok "core_mcp.py is executable"

# ── 3. register with Claude Code ───────────────────────────────────────────────

info "Registering core-mcp with Claude Code…"
claude mcp add --scope user core-mcp -- python3 "$MCP_SCRIPT"
ok "core-mcp registered"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ok "Installation complete!"
echo
echo "  Verify:  claude mcp list"
echo "  Test:    claude  →  /mcp"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
