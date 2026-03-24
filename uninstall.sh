#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# All_Chat — Uninstaller
# Removes everything setup.sh installed. Leaves the OS clean.
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[info]${NC}  $*"; }
success() { echo -e "${GREEN}[ ok ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
section() { echo -e "\n${BOLD}${RED}══ $* ══${NC}"; }

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Run as root: sudo bash uninstall.sh${NC}"
    exit 1
fi

clear
echo -e "${BOLD}${RED}"
echo "  All_Chat — Uninstaller"
echo -e "${NC}"
echo -e "  This will remove:"
echo -e "    • The allchat systemd service"
echo -e "    • The /app directory (all code, media, virtualenv)"
echo -e "    • The allchat PostgreSQL database and user"
echo -e "    • The allchat nginx site config"
echo -e "    • The allchat system user"
echo -e "    • The swap file (if created by setup.sh)"
echo -e "    • /root/.allchat_secrets"
echo ""
echo -e "  ${YELLOW}This does NOT uninstall PostgreSQL, Redis, Nginx, or Python.${NC}"
echo -e "  Your OS packages stay installed.\n"

echo -e "${YELLOW}Are you sure you want to completely remove All_Chat? (yes/no)${NC}"
read -r CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""

# ── Stop and disable service ───────────────────────────────────────────────────
section "Service"
if systemctl is-active --quiet allchat 2>/dev/null; then
    systemctl stop allchat
    info "Service stopped"
fi
if systemctl is-enabled --quiet allchat 2>/dev/null; then
    systemctl disable allchat
    info "Service disabled"
fi
rm -f /etc/systemd/system/allchat.service
systemctl daemon-reload
success "allchat.service removed"

# ── Remove app directory ───────────────────────────────────────────────────────
section "App Files"
if [[ -d /app ]]; then
    rm -rf /app
    success "/app directory removed"
else
    info "/app not found — skipping"
fi

# ── Remove system user ─────────────────────────────────────────────────────────
section "System User"
if id allchat &>/dev/null; then
    userdel allchat 2>/dev/null || true
    success "System user 'allchat' removed"
else
    info "User 'allchat' not found — skipping"
fi

# ── Remove database ────────────────────────────────────────────────────────────
section "Database"
if sudo -u postgres psql -lqt 2>/dev/null | cut -d\| -f1 | grep -qw allchat; then
    sudo -u postgres psql -c "DROP DATABASE allchat;" 2>/dev/null || true
    success "Database 'allchat' dropped"
else
    info "Database 'allchat' not found — skipping"
fi

if sudo -u postgres psql -c "\du" 2>/dev/null | grep -qw allchat; then
    sudo -u postgres psql -c "DROP USER allchat;" 2>/dev/null || true
    success "Database user 'allchat' dropped"
else
    info "Database user 'allchat' not found — skipping"
fi

# ── Remove nginx config ────────────────────────────────────────────────────────
section "Nginx"
rm -f /etc/nginx/sites-enabled/allchat.conf
rm -f /etc/nginx/sites-available/allchat.conf
rm -f /etc/nginx/snippets/proxy-params.conf

# Restore default site if it doesn't exist
if [[ ! -f /etc/nginx/sites-enabled/default ]]; then
    ln -sf /etc/nginx/sites-available/default \
           /etc/nginx/sites-enabled/default 2>/dev/null || true
fi

# Remove rate limit zones from nginx.conf
sed -i '/limit_req_zone.*zone=global/d'  /etc/nginx/nginx.conf 2>/dev/null || true
sed -i '/limit_req_zone.*zone=auth/d'    /etc/nginx/nginx.conf 2>/dev/null || true
sed -i '/limit_conn_zone.*zone=perip/d'  /etc/nginx/nginx.conf 2>/dev/null || true

# Remove logrotate config
rm -f /etc/logrotate.d/allchat

# Remove nginx logs
rm -f /var/log/nginx/allchat_access.log
rm -f /var/log/nginx/allchat_error.log

if nginx -t 2>/dev/null; then
    systemctl reload nginx
    success "Nginx config cleaned and reloaded"
else
    warn "Nginx config has issues — check manually: sudo nginx -t"
fi

# ── Remove fail2ban config ─────────────────────────────────────────────────────
section "fail2ban"
rm -f /etc/fail2ban/jail.d/allchat.conf
systemctl restart fail2ban 2>/dev/null || true
success "fail2ban config removed"

# ── Remove swap file ───────────────────────────────────────────────────────────
section "Swap"
if [[ -f /swapfile ]]; then
    swapoff /swapfile 2>/dev/null || true
    rm -f /swapfile
    sed -i '/\/swapfile/d' /etc/fstab
    success "Swap file removed"
else
    info "No swap file found — skipping"
fi

# ── Remove secrets file ────────────────────────────────────────────────────────
section "Credentials"
rm -f /root/.allchat_secrets
success "Credentials file removed"

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  All_Chat completely removed.${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  PostgreSQL, Redis, Nginx, and Python are still installed."
echo -e "  To reinstall All_Chat: ${CYAN}sudo bash setup.sh${NC}"
echo ""
