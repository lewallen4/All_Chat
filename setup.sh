#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# All_Chat — Debian Server Bootstrap Script
#
# Tested on: Debian 12 (Bookworm) and Debian 13 (Trixie)
# Uses whatever python3 the system provides (3.11, 3.12, 3.13 all work)
# HTTP-only by default — add TLS later with certbot when you have a domain
#
# Usage:
#   1. Edit the CONFIG section below
#   2. sudo bash setup.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
IFS=$'\n\t'

# ── CONFIGURATION ──────────────────────────────────────────────────────────────
DOMAIN="yourdomain.com"          # or your server IP e.g. 203.0.113.42
APP_USER="allchat"
APP_DIR="/app"
DB_NAME="allchat"
DB_USER="allchat"
ADMIN_EMAIL="admin@yourdomain.com"
SKIP_CERTBOT=true                # keep true until you have a real domain + DNS
SKIP_FIREWALL=false
# ──────────────────────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[info]${NC}  $*"; }
success() { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
error()   { echo -e "${RED}[error]${NC} $*" >&2; }
section() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}"; }

# ── Preflight ──────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "Run as root: sudo bash setup.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
info "Script directory : $SCRIPT_DIR"
info "Domain / IP      : $DOMAIN"
info "App directory    : $APP_DIR"

# ── 1. System update ──────────────────────────────────────────────────────────
section "System Update"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget gnupg2 lsb-release ca-certificates apt-transport-https \
    build-essential git unzip \
    ufw fail2ban logrotate \
    python3 python3-venv python3-dev python3-pip \
    libpq-dev libffi-dev libssl-dev \
    libjpeg-dev libpng-dev libwebp-dev zlib1g-dev \
    libxml2-dev libxslt1-dev
success "Base packages installed (Python $(python3 --version))"

# ── 2. PostgreSQL ─────────────────────────────────────────────────────────────
section "PostgreSQL"
if ! command -v psql &>/dev/null; then
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | \
        gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
    echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list
    apt-get update -qq
    apt-get install -y -qq postgresql-16 postgresql-client-16
fi
systemctl enable postgresql --now
success "PostgreSQL installed and running"

DB_PASSWORD=$(openssl rand -hex 32)

sudo -u postgres psql -c "
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
            CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        ELSE
            ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        END IF;
    END
    \$\$;" 2>/dev/null || true

sudo -u postgres psql -c "
    SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')
    \gexec" 2>/dev/null || true

sudo -u postgres psql -c \
    "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null || true
sudo -u postgres psql -d "$DB_NAME" -c \
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;" 2>/dev/null || true
sudo -u postgres psql -d "$DB_NAME" -c \
    "CREATE EXTENSION IF NOT EXISTS unaccent;" 2>/dev/null || true
success "PostgreSQL database configured"

# ── 3. Redis ──────────────────────────────────────────────────────────────────
section "Redis"
apt-get install -y -qq redis-server
REDIS_CONF="/etc/redis/redis.conf"
sed -i 's/^# bind 127.0.0.1/bind 127.0.0.1/' "$REDIS_CONF" 2>/dev/null || true
sed -i 's/^protected-mode no/protected-mode yes/' "$REDIS_CONF" 2>/dev/null || true
grep -q "^maxmemory "        "$REDIS_CONF" || echo "maxmemory 128mb"        >> "$REDIS_CONF"
grep -q "^maxmemory-policy " "$REDIS_CONF" || echo "maxmemory-policy allkeys-lru" >> "$REDIS_CONF"
systemctl enable redis-server --now
systemctl restart redis-server
success "Redis configured and running"

# ── 4. Nginx ──────────────────────────────────────────────────────────────────
section "Nginx"
apt-get install -y -qq nginx
systemctl enable nginx

NGINX_CONF="/etc/nginx/nginx.conf"

# Inject rate limiting zones into http{} block (only once)
if ! grep -q "limit_req_zone" "$NGINX_CONF"; then
    sed -i '/http {/a \    limit_req_zone  $binary_remote_addr zone=global:10m rate=10r\/s;\n    limit_req_zone  $binary_remote_addr zone=auth:10m   rate=2r\/s;\n    limit_conn_zone $binary_remote_addr zone=perip:10m;' \
        "$NGINX_CONF"
fi

# Disable server tokens
sed -i 's/# server_tokens off;/server_tokens off;/' "$NGINX_CONF" 2>/dev/null || true

# Install proxy params snippet
mkdir -p /etc/nginx/snippets
cp "$SCRIPT_DIR/nginx/proxy-params.conf" /etc/nginx/snippets/proxy-params.conf

# Install site config (already HTTP-only, no TLS directives)
cp "$SCRIPT_DIR/nginx/allchat.conf" /etc/nginx/sites-available/allchat.conf
ln -sf /etc/nginx/sites-available/allchat.conf /etc/nginx/sites-enabled/allchat.conf
rm -f /etc/nginx/sites-enabled/default

nginx -t
success "Nginx configured (HTTP-only)"

# ── 5. Skip Certbot ───────────────────────────────────────────────────────────
if [[ "$SKIP_CERTBOT" == "false" ]]; then
    section "Let's Encrypt TLS"
    apt-get install -y -qq certbot python3-certbot-nginx
    mkdir -p /var/www/certbot
    systemctl stop nginx || true
    certbot certonly --standalone --non-interactive --agree-tos \
        --email "$ADMIN_EMAIL" --domain "$DOMAIN" \
        --preferred-challenges http \
        || warn "Certbot failed — add TLS manually later with: certbot --nginx -d $DOMAIN"
    systemctl start nginx
    if ! crontab -l 2>/dev/null | grep -q certbot; then
        (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet --nginx") | crontab -
    fi
    success "TLS certificate installed"
else
    info "TLS skipped — running HTTP only on port 80"
    info "To add TLS later: sudo certbot --nginx -d yourdomain.com"
fi

# ── 6. App user & directories ─────────────────────────────────────────────────
section "App User & Directories"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin \
            --home-dir "$APP_DIR" --no-create-home "$APP_USER"
fi

mkdir -p "$APP_DIR"/{backend,frontend,media/{avatars,posts,channels/{avatars,banners}},scripts,logs}
success "User '$APP_USER' and directories ready"

# ── 7. Copy application files ─────────────────────────────────────────────────
section "Application Files"
cp -r "$SCRIPT_DIR/backend/."  "$APP_DIR/backend/"
cp -r "$SCRIPT_DIR/frontend/." "$APP_DIR/frontend/"
cp -r "$SCRIPT_DIR/scripts/."  "$APP_DIR/scripts/"
chmod +x "$APP_DIR/scripts/"*.py 2>/dev/null || true
success "Application files copied"

# ── 8. Python virtualenv ──────────────────────────────────────────────────────
section "Python Environment"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip wheel setuptools -q

# greenlet must be installed explicitly before SQLAlchemy async deps
"$APP_DIR/venv/bin/pip" install greenlet -q

"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q
success "Python dependencies installed"

# ── 9. Generate .env ──────────────────────────────────────────────────────────
section "Environment Configuration"
SECRET_KEY=$(openssl rand -hex 64)

# Use http:// since we're not using TLS
ORIGIN_SCHEME="http"
if [[ "$SKIP_CERTBOT" == "false" ]]; then
    ORIGIN_SCHEME="https"
fi

cat > "$APP_DIR/backend/.env" << ENV
# All_Chat — Production Environment
# Generated $(date -u +"%Y-%m-%d %H:%M UTC")
# Keep this file private. Never commit to version control.

APP_NAME=All_Chat
DEBUG=false
SECRET_KEY=${SECRET_KEY}

DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
REDIS_URL=redis://localhost:6379/0

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noreply@${DOMAIN}
SMTP_TLS=true

ALLOWED_ORIGINS=["${ORIGIN_SCHEME}://${DOMAIN}"]
MEDIA_DIR=${APP_DIR}/media

ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
EMAIL_VERIFY_EXPIRE_HOURS=24
PASSWORD_RESET_EXPIRE_HOURS=2

PQ_ENABLED=false
ENV

chmod 640 "$APP_DIR/backend/.env"
success ".env generated"

# Save credentials
cat > /root/.allchat_secrets << SECRETS
# All_Chat credentials — generated $(date -u +"%Y-%m-%d")
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
SECRET_KEY=${SECRET_KEY}
SECRETS
chmod 600 /root/.allchat_secrets
success "Credentials saved to /root/.allchat_secrets"

# ── 10. Swap file (helps on low-RAM servers) ──────────────────────────────────
section "Swap"
if [[ ! -f /swapfile ]]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    success "1GB swap file created"
else
    info "Swap file already exists — skipping"
fi

# ── 11. File permissions ──────────────────────────────────────────────────────
section "Permissions"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod -R 750 "$APP_DIR"
chmod -R 770 "$APP_DIR/media"
chmod -R 755 "$APP_DIR/frontend/static"
chmod 640    "$APP_DIR/backend/.env"
success "Permissions set"

# ── 12. Database tables ───────────────────────────────────────────────────────
section "Database Tables"
cd /tmp
sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" -c "
import asyncio, sys
sys.path.insert(0, '$APP_DIR/backend')
from dotenv import load_dotenv
load_dotenv('$APP_DIR/backend/.env')
from core.database import engine, Base
import models
async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Tables created.')
asyncio.run(init())
" && success "Database tables created" || warn "Table creation had issues — check logs"

# Install full-text search trigger
sudo -u postgres psql -d "$DB_NAME" << 'PSQL'
CREATE OR REPLACE FUNCTION update_post_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        to_tsvector('english',
            coalesce(NEW.title, '') || ' ' ||
            coalesce(regexp_replace(NEW.body, '<[^>]+>', ' ', 'g'), '')
        );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS post_search_vector_update ON posts;
CREATE TRIGGER post_search_vector_update
    BEFORE INSERT OR UPDATE OF title, body ON posts
    FOR EACH ROW EXECUTE FUNCTION update_post_search_vector();
PSQL
success "Full-text search trigger installed"

# ── 13. Systemd service ───────────────────────────────────────────────────────
section "Systemd Service"
cp "$SCRIPT_DIR/systemd/allchat.service" /etc/systemd/system/allchat.service
systemctl daemon-reload
systemctl enable allchat
systemctl start allchat
sleep 3

if systemctl is-active --quiet allchat; then
    success "allchat.service started"
else
    warn "Service failed to start — check: journalctl -u allchat -n 50"
fi

# ── 14. Firewall ──────────────────────────────────────────────────────────────
if [[ "$SKIP_FIREWALL" == "false" ]]; then
    section "Firewall (UFW)"
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
    success "UFW configured"
else
    warn "Firewall skipped"
fi

# ── 15. fail2ban ──────────────────────────────────────────────────────────────
section "fail2ban"
cat > /etc/fail2ban/jail.d/allchat.conf << 'F2B'
[nginx-limit-req]
enabled  = true
filter   = nginx-limit-req
action   = iptables-multiport[name=ReqLimit, port="http,https", protocol=tcp]
logpath  = /var/log/nginx/allchat_error.log
findtime = 600
bantime  = 7200
maxretry = 10

[sshd]
enabled  = true
port     = ssh
filter   = sshd
logpath  = /var/log/auth.log
maxretry = 3
bantime  = 86400
F2B
systemctl enable fail2ban --now
systemctl restart fail2ban
success "fail2ban configured"

# ── 16. Log rotation ──────────────────────────────────────────────────────────
section "Log Rotation"
cat > /etc/logrotate.d/allchat << LR
/var/log/nginx/allchat_*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        systemctl reload nginx 2>/dev/null || true
    endscript
}
LR
success "Log rotation configured"

# ── 17. Reload nginx ──────────────────────────────────────────────────────────
nginx -t && systemctl reload nginx
success "Nginx reloaded"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  All_Chat setup complete! ❤️${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}URL:${NC}        http://$DOMAIN"
echo -e "  ${CYAN}Service:${NC}    systemctl status allchat"
echo -e "  ${CYAN}Logs:${NC}       journalctl -u allchat -f"
echo -e "  ${CYAN}DB creds:${NC}   cat /root/.allchat_secrets"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "  1. Add your Gmail SMTP details:"
echo -e "     nano $APP_DIR/backend/.env"
echo -e "  2. Restart the app:"
echo -e "     systemctl restart allchat"
echo -e "  3. Create your admin account:"
echo -e "     sudo -u allchat $APP_DIR/venv/bin/python $APP_DIR/scripts/create_admin.py"
echo ""
echo -e "  ${YELLOW}Add TLS when you have a domain:${NC}"
echo -e "     sudo certbot --nginx -d yourdomain.com"
echo -e "     Update ALLOWED_ORIGINS in $APP_DIR/backend/.env to https://"
echo -e "     systemctl restart allchat"
echo ""
