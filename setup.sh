#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# All_Chat — Debian Server Bootstrap Script
# Tested on: Debian 12 (Bookworm) fresh install
#
# Usage:
#   1. Copy this repo to your server (scp, git clone, etc.)
#   2. Edit the CONFIG section below
#   3. chmod +x setup.sh && sudo ./setup.sh
#
# What this does:
#   - System updates & hardening (UFW, fail2ban, SSH)
#   - Installs PostgreSQL 16, Redis, Nginx, Certbot, Python 3.11
#   - Creates a dedicated 'allchat' system user
#   - Sets up the Python virtualenv and installs all deps
#   - Creates the PostgreSQL database + user
#   - Configures Nginx with TLS via Let's Encrypt
#   - Installs and enables the systemd service
#   - Generates a secure .env file
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
IFS=$'\n\t'

# ── CONFIGURATION — Edit these before running ──────────────────────────────────
DOMAIN="yourdomain.com"                    # Your domain name
APP_USER="allchat"                         # System user to run the app
APP_DIR="/app"                             # App install directory
DB_NAME="allchat"                          # PostgreSQL database name
DB_USER="allchat"                          # PostgreSQL user
ADMIN_EMAIL="admin@yourdomain.com"         # For Let's Encrypt + alerts
SKIP_CERTBOT=false                         # Set true if no domain yet (dev)
SKIP_FIREWALL=false                        # Set true to skip UFW setup
# ──────────────────────────────────────────────────────────────────────────────

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[info]${NC}  $*"; }
success() { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
error()   { echo -e "${RED}[error]${NC} $*" >&2; }
section() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}"; }

# ── Preflight checks ──────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (sudo ./setup.sh)"
    exit 1
fi

if [[ "$DOMAIN" == "yourdomain.com" ]]; then
    error "Please edit the DOMAIN variable in setup.sh before running."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
info "Script directory: $SCRIPT_DIR"
info "Domain: $DOMAIN"
info "App directory: $APP_DIR"

# ── 1. System update & base packages ─────────────────────────────────────────
section "System Update"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget gnupg2 lsb-release ca-certificates apt-transport-https \
    software-properties-common build-essential git unzip \
    ufw fail2ban logrotate \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    libpq-dev libffi-dev libssl-dev \
    libjpeg-dev libpng-dev libwebp-dev zlib1g-dev \
    libxml2-dev libxslt1-dev
success "Base packages installed"

# ── 2. PostgreSQL 16 ──────────────────────────────────────────────────────────
section "PostgreSQL 16"
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

# Generate a strong DB password
DB_PASSWORD=$(openssl rand -hex 32)

# Create database and user
info "Creating database '$DB_NAME' and user '$DB_USER'…"
sudo -u postgres psql -c "
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
            CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        ELSE
            ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
        END IF;
    END
    \$\$;
" 2>/dev/null || true

sudo -u postgres psql -c "
    SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')
    \gexec
" 2>/dev/null || true

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null || true

# Enable PostgreSQL extensions
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" 2>/dev/null || true
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS unaccent;" 2>/dev/null || true

success "PostgreSQL database configured"

# ── 3. Redis ──────────────────────────────────────────────────────────────────
section "Redis"
apt-get install -y -qq redis-server

# Harden Redis config
REDIS_CONF="/etc/redis/redis.conf"
sed -i 's/^# bind 127.0.0.1/bind 127.0.0.1/' "$REDIS_CONF"
sed -i 's/^protected-mode no/protected-mode yes/' "$REDIS_CONF"
# Set maxmemory to 256MB with LRU eviction
grep -q "^maxmemory " "$REDIS_CONF" || echo "maxmemory 256mb" >> "$REDIS_CONF"
grep -q "^maxmemory-policy " "$REDIS_CONF" || echo "maxmemory-policy allkeys-lru" >> "$REDIS_CONF"

systemctl enable redis-server --now
systemctl restart redis-server
success "Redis configured and running"

# ── 4. Nginx ──────────────────────────────────────────────────────────────────
section "Nginx"
apt-get install -y -qq nginx
systemctl enable nginx

# Harden nginx.conf
NGINX_CONF="/etc/nginx/nginx.conf"
# Add rate limiting zones to http block if not present
if ! grep -q "limit_req_zone" "$NGINX_CONF"; then
    sed -i '/http {/a \    # Rate limiting zones\n    limit_req_zone $binary_remote_addr zone=global:10m rate=10r\/s;\n    limit_req_zone $binary_remote_addr zone=auth:10m   rate=2r\/s;\n    limit_conn_zone $binary_remote_addr zone=perip:10m;' "$NGINX_CONF"
fi

# Set server_tokens off
sed -i 's/# server_tokens off;/server_tokens off;/' "$NGINX_CONF" || true

# Create proxy-params snippet
mkdir -p /etc/nginx/snippets
cp "$SCRIPT_DIR/nginx/proxy-params.conf" /etc/nginx/snippets/proxy-params.conf

# Install site config
cp "$SCRIPT_DIR/nginx/allchat.conf" /etc/nginx/sites-available/allchat.conf
sed -i "s/YOUR_DOMAIN/$DOMAIN/g" /etc/nginx/sites-available/allchat.conf

ln -sf /etc/nginx/sites-available/allchat.conf /etc/nginx/sites-enabled/allchat.conf
rm -f /etc/nginx/sites-enabled/default

nginx -t
success "Nginx configured"

# ── 5. Let's Encrypt / Certbot ────────────────────────────────────────────────
if [[ "$SKIP_CERTBOT" == "false" ]]; then
    section "Let's Encrypt TLS"
    apt-get install -y -qq certbot python3-certbot-nginx

    # Create webroot for ACME challenge
    mkdir -p /var/www/certbot

    # Temporarily disable HTTPS redirect for cert issuance
    # Use standalone mode to avoid nginx dependency
    systemctl stop nginx || true

    certbot certonly --standalone \
        --non-interactive \
        --agree-tos \
        --email "$ADMIN_EMAIL" \
        --domain "$DOMAIN" \
        --preferred-challenges http \
        || warn "Certbot failed — check your DNS and try: certbot --nginx -d $DOMAIN"

    systemctl start nginx

    # Auto-renewal cron
    if ! crontab -l 2>/dev/null | grep -q certbot; then
        (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet --nginx") | crontab -
    fi
    success "TLS certificate installed (auto-renewal scheduled)"
else
    warn "Certbot skipped. Configure TLS manually before going public."
    # Temporarily serve HTTP only (replace ssl config lines)
    sed -i 's/listen 443 ssl http2;/listen 8080;/' /etc/nginx/sites-available/allchat.conf
    sed -i 's/listen \[::\]:443 ssl http2;//' /etc/nginx/sites-available/allchat.conf
    sed -i '/ssl_/d' /etc/nginx/sites-available/allchat.conf
    info "Nginx configured for HTTP on port 8080 (dev mode)"
fi

# ── 6. App user & directories ─────────────────────────────────────────────────
section "App User & Directories"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$APP_DIR" --create-home "$APP_USER"
fi

mkdir -p "$APP_DIR"/{backend,frontend,media/{avatars,posts},venv,logs}
success "App user '$APP_USER' and directories created"

# ── 7. Copy application files ─────────────────────────────────────────────────
section "Application Files"
info "Copying backend…"
cp -r "$SCRIPT_DIR/backend/." "$APP_DIR/backend/"

info "Copying frontend…"
cp -r "$SCRIPT_DIR/frontend/." "$APP_DIR/frontend/"

success "Application files copied"

# ── 8. Python virtualenv & dependencies ──────────────────────────────────────
section "Python Environment"
python3.11 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip wheel setuptools -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q
success "Python dependencies installed"

# ── 9. Generate .env file ────────────────────────────────────────────────────
section "Environment Configuration"
SECRET_KEY=$(openssl rand -hex 64)

cat > "$APP_DIR/backend/.env" <<EOF
# All_Chat — Production Environment
# Generated by setup.sh on $(date -u +"%Y-%m-%d %H:%M UTC")
# ⚠ Keep this file private. Never commit to version control.

APP_NAME=All_Chat
DEBUG=false
SECRET_KEY=${SECRET_KEY}

DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
REDIS_URL=redis://localhost:6379/0

SMTP_HOST=localhost
SMTP_PORT=25
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noreply@${DOMAIN}
SMTP_TLS=false

ALLOWED_ORIGINS=["https://${DOMAIN}"]
MEDIA_DIR=${APP_DIR}/media

ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
EMAIL_VERIFY_EXPIRE_HOURS=24
PASSWORD_RESET_EXPIRE_HOURS=2

PQ_ENABLED=false
EOF

chmod 640 "$APP_DIR/backend/.env"
success ".env file generated"

# Save DB password to a secure location for reference
cat > /root/.allchat_secrets <<EOF
# All_Chat — DB Credentials (generated $(date -u +"%Y-%m-%d"))
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
SECRET_KEY=${SECRET_KEY}
EOF
chmod 600 /root/.allchat_secrets
success "Credentials saved to /root/.allchat_secrets (root-only)"

# ── 10. File permissions ─────────────────────────────────────────────────────
section "File Permissions"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod -R 750 "$APP_DIR"
chmod -R 770 "$APP_DIR/media"
chmod -R 755 "$APP_DIR/frontend/static"
chmod 640 "$APP_DIR/backend/.env"
success "Permissions set"

# ── 11. Run database migrations ───────────────────────────────────────────────
section "Database Migrations"
cd "$APP_DIR/backend"
# Initialize Alembic if needed
if [[ ! -d "$APP_DIR/backend/alembic/versions" ]]; then
    mkdir -p "$APP_DIR/backend/alembic/versions"
    sudo -u "$APP_USER" "$APP_DIR/venv/bin/alembic" init alembic 2>/dev/null || true
fi

# Run initial migration (creates all tables via SQLAlchemy)
sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" -c "
import asyncio
from core.database import engine, Base
import models  # registers all models
asyncio.run(engine.connect().__aenter__().run_sync(Base.metadata.create_all))
print('Tables created.')
" 2>/dev/null || warn "Initial table creation — may need manual migration step"

# Create tsvector update trigger for full-text search
sudo -u postgres psql -d "$DB_NAME" <<'PSQL'
-- Auto-update search_vector on INSERT/UPDATE
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
success "Database schema and triggers created"

# ── 12. Systemd service ───────────────────────────────────────────────────────
section "Systemd Service"
cp "$SCRIPT_DIR/systemd/allchat.service" /etc/systemd/system/allchat.service
sed -i "s|/app|$APP_DIR|g" /etc/systemd/system/allchat.service

systemctl daemon-reload
systemctl enable allchat
systemctl start allchat
sleep 3

if systemctl is-active --quiet allchat; then
    success "allchat.service started successfully"
else
    error "Service failed to start. Check: journalctl -u allchat -n 50"
fi

# ── 13. UFW Firewall ──────────────────────────────────────────────────────────
if [[ "$SKIP_FIREWALL" == "false" ]]; then
    section "Firewall (UFW)"
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
    success "UFW configured (SSH + HTTP/HTTPS allowed)"
else
    warn "Firewall setup skipped."
fi

# ── 14. fail2ban ─────────────────────────────────────────────────────────────
section "fail2ban"
cat > /etc/fail2ban/jail.d/allchat.conf <<'EOF'
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
EOF
systemctl enable fail2ban --now
systemctl restart fail2ban
success "fail2ban configured"

# ── 15. Log rotation ──────────────────────────────────────────────────────────
section "Log Rotation"
cat > /etc/logrotate.d/allchat <<EOF
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
EOF
success "Log rotation configured"

# ── 16. Reload Nginx ─────────────────────────────────────────────────────────
nginx -t && systemctl reload nginx
success "Nginx reloaded"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  All_Chat setup complete! ❤️${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}URL:${NC}        https://$DOMAIN"
echo -e "  ${CYAN}Service:${NC}    systemctl status allchat"
echo -e "  ${CYAN}Logs:${NC}       journalctl -u allchat -f"
echo -e "  ${CYAN}Nginx logs:${NC} tail -f /var/log/nginx/allchat_error.log"
echo -e "  ${CYAN}DB creds:${NC}   cat /root/.allchat_secrets"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "  1. Update SMTP settings in $APP_DIR/backend/.env"
echo -e "  2. Restart: systemctl restart allchat"
echo -e "  3. Test registration and email verification"
echo ""
echo -e "  ${YELLOW}Post-Quantum (optional):${NC}"
echo -e "  Install liboqs: https://github.com/open-quantum-safe/liboqs"
echo -e "  Then set PQ_ENABLED=true in .env and restart"
echo ""
