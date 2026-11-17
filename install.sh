#!/usr/bin/env bash
# Install or update the print bridge on a Raspberry Pi (Raspberry Pi OS / Debian).
#
#   curl -fsSL https://raw.githubusercontent.com/sauravsood/print-bridge/main/install.sh | sudo bash
#   curl -fsSL https://raw.githubusercontent.com/sauravsood/print-bridge/main/install.sh | sudo bash -s -- <CLOUDFLARE_TUNNEL_TOKEN>
#
# Safe to run again: it pulls the latest code and restarts the service.
set -euo pipefail

REPO="${PRINT_BRIDGE_REPO:-https://github.com/sauravsood/print-bridge.git}"
BRANCH="${PRINT_BRIDGE_BRANCH:-main}"
TOKEN="${1:-}"

[ "$(id -u)" -eq 0 ] || { echo "Please run with sudo."; exit 1; }

echo "==> Installing packages"
apt-get update -qq
apt-get install -y -qq python3 poppler-utils git ca-certificates curl >/dev/null

echo "==> Fetching code"
if [ -d /opt/print-bridge/.git ]; then
  git -C /opt/print-bridge fetch -q origin "$BRANCH"
  git -C /opt/print-bridge reset -q --hard "origin/$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO" /opt/print-bridge
fi

echo "==> Setting up service"
id printbridge >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin printbridge
install -d -o printbridge -g printbridge -m 0750 /var/lib/print-bridge
install -m 0644 /opt/print-bridge/deploy/print-bridge.service /etc/systemd/system/print-bridge.service
systemctl daemon-reload
systemctl enable -q print-bridge
systemctl restart print-bridge

if [ -n "$TOKEN" ]; then
  echo "==> Installing Cloudflare Tunnel"
  if ! command -v cloudflared >/dev/null; then
    install -d -m 0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
      > /etc/apt/sources.list.d/cloudflared.list
    apt-get update -qq
    apt-get install -y -qq cloudflared >/dev/null
  fi
  if systemctl list-unit-files cloudflared.service >/dev/null 2>&1 && systemctl is-enabled -q cloudflared 2>/dev/null; then
    cloudflared service uninstall >/dev/null 2>&1 || true
  fi
  cloudflared service install "$TOKEN"
fi

sleep 1
if curl -fsS http://127.0.0.1:8080/api/settings >/dev/null; then
  echo
  echo "Done. The print bridge is running."
  [ -n "$TOKEN" ] && echo "Open https://print.sauravsood.com (after the tunnel's public hostname is set up)."
else
  echo "The service didn't start. See: sudo journalctl -u print-bridge -n 50"
  exit 1
fi
