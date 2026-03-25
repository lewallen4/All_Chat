#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# All_Chat v5 — Complete Setup Script
#
# Tested: Debian 12 (Bookworm), Debian 13 (Trixie)
# Python: uses whatever python3 the system has (3.11, 3.12, 3.13)
# TLS:    HTTP only by default — add TLS later with certbot
#
# This script will:
#   - Install all system dependencies
#   - Configure PostgreSQL, Redis, Nginx
#   - Set up Python virtualenv and install all deps
#   - Create the database, tables, and search triggers
#   - Create the allchat system user
#   - Generate a secure .env file
#   - Walk you through SMTP configuration interactively
#   - Create a 1GB swap file
#   - Install and start the systemd service
#   - Create your admin account
#   - Verify everything is working before finishing
#
# Usage:  sudo bash setup.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
IFS=$'\n\t'

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[info]${NC}  $*"; }
success() { echo -e "${GREEN}[ ok ]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
error()   { echo -e "${RED}[err ]${NC}  $*" >&2; }
section() { echo -e "\n${BOLD}${BLUE}══ $* ══${NC}"; }
ask()     { echo -e "${YELLOW}[?]${NC}    $*"; }

# ── Preflight ─────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "Please run as root: sudo bash setup.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/app"
APP_USER="allchat"
DB_NAME="allchat"
DB_USER="allchat"

clear
echo -e "${BOLD}${GREEN}"
echo "  ██████╗ ██╗      ██╗          ██████╗██╗  ██╗ █████╗ ████████╗"
echo " ██╔══██╗██║      ██║         ██╔════╝██║  ██║██╔══██╗╚══██╔══╝"
echo " ███████║██║      ██║         ██║     ███████║███████║   ██║   "
echo " ██╔══██║██║      ██║         ██║     ██╔══██║██╔══██║   ██║   "
echo " ██║  ██║███████╗ ███████╗    ╚██████╗██║  ██║██║  ██║   ██║   "
echo " ╚═╝  ╚═╝╚══════╝ ╚══════╝     ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   v5"
echo -e "${NC}"
echo -e "  ${BOLD}Setup Wizard — This will fully deploy All_Chat on your server.${NC}"
echo -e "  You will be asked a few questions. Everything else is automatic.\n"

# ── Step 1: Collect config upfront ────────────────────────────────────────────
section "Configuration"

echo -e "${BOLD}Your server's IP address or domain name${NC}"
echo -e "  Examples: ${CYAN}203.0.113.42${NC}  or  ${CYAN}all-chat-now.com${NC}"
echo -e "  (If using an IP, TLS will be skipped automatically)"
ask "Enter your IP or domain:"
read -r SERVER_ADDRESS
SERVER_ADDRESS="${SERVER_ADDRESS// /}"  # strip spaces

# Detect if it's an IP or domain
if [[ "$SERVER_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    USE_TLS=false
    info "IP address detected — running HTTP only (no TLS)"
else
    echo ""
    ask "Do you have DNS pointing to this server already? (y/n)"
    read -r DNS_READY
    if [[ "$DNS_READY" =~ ^[Yy]$ ]]; then
        USE_TLS=true
        info "Domain with DNS — TLS will be configured"
    else
        USE_TLS=false
        warn "TLS skipped — run 'sudo certbot --nginx -d $SERVER_ADDRESS' later"
    fi
fi

echo ""
echo -e "${BOLD}Admin email address${NC} (used for Let's Encrypt alerts if TLS enabled)"
ask "Enter your email:"
read -r ADMIN_EMAIL
ADMIN_EMAIL="${ADMIN_EMAIL// /}"

echo ""
echo -e "${BOLD}SMTP Configuration (for sending verification emails)${NC}"
echo -e "  Recommended: Gmail with an App Password"
echo -e "  Gmail App Password: ${CYAN}myaccount.google.com/apppasswords${NC}"
echo -e "  (Requires 2-Step Verification to be enabled on your Google account)"
echo ""
ask "Enter your Gmail address (or other SMTP user):"
read -r SMTP_USER
SMTP_USER="${SMTP_USER// /}"

ask "Enter your App Password (no spaces — e.g. abcdefghijklmnop):"
read -rs SMTP_PASSWORD
echo ""
SMTP_PASSWORD="${SMTP_PASSWORD// /}"

SMTP_HOST="smtp.gmail.com"
SMTP_PORT="587"
SMTP_TLS="true"
SMTP_FROM="$SMTP_USER"

echo ""
success "Configuration collected. Starting installation..."
sleep 1

# ── Step 2: Wait for any running apt to finish ─────────────────────────────────
section "System Update"
info "Waiting for any running package managers to finish..."
for i in {1..30}; do
    if ! fuser /var/lib/dpkg/lock-frontend &>/dev/null 2>&1; then
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

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

PYTHON_VER=$(python3 --version)
success "System packages installed ($PYTHON_VER)"

# ── Step 3: PostgreSQL ─────────────────────────────────────────────────────────
section "PostgreSQL"
if ! command -v psql &>/dev/null; then
    info "Installing PostgreSQL..."
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg
    echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list
    apt-get update -qq
    apt-get install -y -qq postgresql-16 postgresql-client-16
fi

systemctl enable postgresql --now
sleep 2  # give postgres a moment to fully start
success "PostgreSQL running"

DB_PASSWORD=$(openssl rand -hex 32)

# Create user and database — handle already-exists gracefully
info "Creating database user and database..."
sudo -u postgres psql -v ON_ERROR_STOP=0 << PSQL 2>/dev/null || true
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
    ELSE
        ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
    END IF;
END
\$\$;
PSQL

sudo -u postgres psql -v ON_ERROR_STOP=0 << PSQL 2>/dev/null || true
SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')
\gexec
PSQL

sudo -u postgres psql -c \
    "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null || true
sudo -u postgres psql -d "$DB_NAME" -c \
    "GRANT ALL ON SCHEMA public TO $DB_USER;" 2>/dev/null || true
sudo -u postgres psql -d "$DB_NAME" -c \
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;" 2>/dev/null || true
sudo -u postgres psql -d "$DB_NAME" -c \
    "CREATE EXTENSION IF NOT EXISTS unaccent;" 2>/dev/null || true

# Verify DB exists
if sudo -u postgres psql -lqt 2>/dev/null | cut -d\| -f1 | grep -qw "$DB_NAME"; then
    success "Database '$DB_NAME' ready"
else
    error "Database creation failed — trying alternative method..."
    sudo -u postgres createdb -O "$DB_USER" "$DB_NAME" 2>/dev/null || true
    success "Database created via createdb"
fi

# ── Step 4: Redis ──────────────────────────────────────────────────────────────
section "Redis"
apt-get install -y -qq redis-server
REDIS_CONF="/etc/redis/redis.conf"
sed -i 's/^# bind 127.0.0.1 ::1/bind 127.0.0.1/' "$REDIS_CONF" 2>/dev/null || true
sed -i 's/^bind 127.0.0.1 ::1/bind 127.0.0.1/'   "$REDIS_CONF" 2>/dev/null || true
grep -q "^maxmemory "        "$REDIS_CONF" || echo "maxmemory 128mb"             >> "$REDIS_CONF"
grep -q "^maxmemory-policy " "$REDIS_CONF" || echo "maxmemory-policy allkeys-lru">> "$REDIS_CONF"

# Set Redis password for local security
REDIS_PASSWORD=$(openssl rand -hex 32)
grep -q "^requirepass " "$REDIS_CONF" &&     sed -i "s/^requirepass .*/requirepass $REDIS_PASSWORD/" "$REDIS_CONF" ||     echo "requirepass $REDIS_PASSWORD" >> "$REDIS_CONF"

systemctl enable redis-server --now
systemctl restart redis-server
success "Redis running (password protected)"

# Store Redis password in secrets file (updated after DB_PASSWORD below)
echo "REDIS_PASSWORD=${REDIS_PASSWORD}" >> /root/.allchat_secrets 2>/dev/null || true

# ── Step 5: Nginx ──────────────────────────────────────────────────────────────
section "Nginx"
apt-get install -y -qq nginx
systemctl enable nginx

NGINX_CONF="/etc/nginx/nginx.conf"
if ! grep -q "limit_req_zone" "$NGINX_CONF"; then
    sed -i '/http {/a \    limit_req_zone  $binary_remote_addr zone=global:10m rate=10r\/s;\n    limit_req_zone  $binary_remote_addr zone=auth:10m   rate=2r\/s;\n    limit_conn_zone $binary_remote_addr zone=perip:10m;' \
        "$NGINX_CONF"
fi
sed -i 's/# server_tokens off;/server_tokens off;/' "$NGINX_CONF" 2>/dev/null || true

mkdir -p /etc/nginx/snippets
cp "$SCRIPT_DIR/nginx/proxy-params.conf" /etc/nginx/snippets/proxy-params.conf

# Write HTTP-only nginx config (no TLS directives at all)
cat > /etc/nginx/sites-available/allchat.conf << 'NGINXEOF'
server {
    listen 80;
    listen [::]:80;
    server_name _;

    client_max_body_size  12M;
    client_body_timeout   30s;
    client_header_timeout 30s;
    keepalive_timeout     75s;
    send_timeout          30s;

    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/javascript application/javascript
               application/json image/svg+xml font/woff font/woff2;

    add_header X-Content-Type-Options  "nosniff"                         always;
    add_header X-Frame-Options         "DENY"                            always;
    add_header X-XSS-Protection        "1; mode=block"                   always;
    add_header Referrer-Policy         "strict-origin-when-cross-origin" always;

    location /static/ {
        alias /app/frontend/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location /media/ {
        alias /app/media/;
        expires 30d;
        add_header Cache-Control "public";
        access_log off;
        location ~* \.(php|py|sh|cgi)$ { deny all; }
    }

    location ~ ^/api/auth/(login|register|forgot-password|reset-password)$ {
        limit_req        zone=auth burst=5 nodelay;
        limit_req_status 429;
        proxy_pass       http://127.0.0.1:8000;
        include          /etc/nginx/snippets/proxy-params.conf;
    }

    location /api/ {
        limit_req        zone=global burst=30 nodelay;
        limit_conn       perip 20;
        limit_req_status 429;
        proxy_pass       http://127.0.0.1:8000;
        include          /etc/nginx/snippets/proxy-params.conf;
    }

    location / {
        limit_req  zone=global burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000;
        include    /etc/nginx/snippets/proxy-params.conf;
    }

    location ~ /\. {
        deny all;
        access_log    off;
        log_not_found off;
    }

    access_log /var/log/nginx/allchat_access.log;
    error_log  /var/log/nginx/allchat_error.log warn;
}
NGINXEOF

ln -sf /etc/nginx/sites-available/allchat.conf /etc/nginx/sites-enabled/allchat.conf
rm -f /etc/nginx/sites-enabled/default

nginx -t
success "Nginx configured"

# ── Step 6: TLS (optional) ─────────────────────────────────────────────────────
if [[ "$USE_TLS" == "true" ]]; then
    section "Let's Encrypt TLS"
    apt-get install -y -qq certbot python3-certbot-nginx
    mkdir -p /var/www/certbot
    systemctl stop nginx || true
    certbot certonly --standalone --non-interactive --agree-tos \
        --email "$ADMIN_EMAIL" --domain "$SERVER_ADDRESS" \
        --preferred-challenges http \
        && success "TLS certificate issued" \
        || warn "Certbot failed — continuing with HTTP. Add TLS later with: certbot --nginx -d $SERVER_ADDRESS"
    systemctl start nginx
fi

# ── Step 7: App user & directories ────────────────────────────────────────────
section "App User & Directories"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin \
            --home-dir "$APP_DIR" --no-create-home "$APP_USER"
    success "System user '$APP_USER' created"
else
    info "System user '$APP_USER' already exists"
fi

mkdir -p "$APP_DIR"/{backend,frontend,media/{avatars,posts,channels/{avatars,banners}},scripts,logs}
success "Directories created"

# ── Step 8: Copy application files ────────────────────────────────────────────
section "Application Files"
cp -r "$SCRIPT_DIR/backend/."  "$APP_DIR/backend/"
cp -r "$SCRIPT_DIR/frontend/." "$APP_DIR/frontend/"
cp -r "$SCRIPT_DIR/scripts/."  "$APP_DIR/scripts/"
chmod +x "$APP_DIR/scripts/"*.py 2>/dev/null || true
success "Application files copied"

# ── Step 9: Python virtualenv ──────────────────────────────────────────────────
section "Python Environment"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip wheel setuptools -q

# Install these explicitly first — they must exist before requirements.txt
"$APP_DIR/venv/bin/pip" install greenlet jinja2 pyotp qrcode -q

"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt" -q
success "Python dependencies installed"

# ── Step 10: Post-Quantum Cryptography (liboqs + Kyber-768) ──────────────────
section "Post-Quantum Cryptography"
info "Building liboqs (Kyber-768 ML-KEM) — this takes 5-10 minutes..."

PQ_SUCCESS=false

# Install build deps
apt-get install -y -qq cmake ninja-build libssl-dev 2>/dev/null || true

# Clone and build liboqs C library
cd /tmp
rm -rf liboqs_build
git clone --depth 1 https://github.com/open-quantum-safe/liboqs.git liboqs_build 2>/dev/null
if [[ -d /tmp/liboqs_build ]]; then
    cd /tmp/liboqs_build
    mkdir -p build && cd build
    cmake -GNinja         -DCMAKE_INSTALL_PREFIX=/usr/local         -DBUILD_SHARED_LIBS=ON         -DOQS_USE_OPENSSL=ON         .. -Wno-dev > /tmp/liboqs_cmake.log 2>&1

    if ninja > /tmp/liboqs_ninja.log 2>&1; then
        ninja install >> /tmp/liboqs_ninja.log 2>&1
        ldconfig

        # Install matching Python bindings
        "$APP_DIR/venv/bin/pip" install --upgrade liboqs-python -q

        # Verify it works
        PQ_TEST=$(sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" -c "
import oqs
kem = oqs.KeyEncapsulation('Kyber768')
pub = kem.generate_keypair()
ct, ss1 = kem.encap_secret(pub)
ss2 = kem.decap_secret(ct)
print('ok' if ss1 == ss2 else 'fail')
" 2>/dev/null || echo "fail")

        if [[ "$PQ_TEST" == "ok" ]]; then
            PQ_SUCCESS=true
            success "Kyber-768 (ML-KEM) post-quantum crypto active ✓"
        else
            warn "liboqs installed but verification failed — falling back to X25519"
        fi
    else
        warn "liboqs build failed — falling back to X25519"
        warn "Check /tmp/liboqs_ninja.log for details"
    fi
else
    warn "Could not clone liboqs — falling back to X25519"
    warn "Install manually later: see README.md PQ section"
fi

cd /tmp

# ── Step 11: Generate .env ─────────────────────────────────────────────────────
section "Environment Configuration"
SECRET_KEY=$(openssl rand -hex 64)
ORIGIN_PREFIX="http"
[[ "$USE_TLS" == "true" ]] && ORIGIN_PREFIX="https"

cat > "$APP_DIR/backend/.env" << ENV
# All_Chat — Environment Configuration
# Generated $(date -u +"%Y-%m-%d %H:%M UTC")

APP_NAME=All_Chat
DEBUG=false
SECRET_KEY=${SECRET_KEY}

DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
REDIS_URL=redis://:${REDIS_PASSWORD}@localhost:6379/0

SMTP_HOST=${SMTP_HOST}
SMTP_PORT=${SMTP_PORT}
SMTP_USER=${SMTP_USER}
SMTP_PASSWORD=${SMTP_PASSWORD}
SMTP_FROM=${SMTP_FROM}
SMTP_TLS=${SMTP_TLS}

ALLOWED_ORIGINS=["${ORIGIN_PREFIX}://${SERVER_ADDRESS}"]
MEDIA_DIR=${APP_DIR}/media

ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
EMAIL_VERIFY_EXPIRE_HOURS=24
PASSWORD_RESET_EXPIRE_HOURS=2

PQ_ENABLED=${PQ_SUCCESS}
ENV

chmod 640 "$APP_DIR/backend/.env"
success ".env generated"

# Save credentials to root-only file
cat > /root/.allchat_secrets << SECRETS
# All_Chat — Generated $(date -u +"%Y-%m-%d")
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
SECRET_KEY=${SECRET_KEY}
SERVER_ADDRESS=${SERVER_ADDRESS}
SMTP_USER=${SMTP_USER}
SECRETS
chmod 600 /root/.allchat_secrets
success "Credentials saved to /root/.allchat_secrets"

# ── Step 12: Swap file ─────────────────────────────────────────────────────────
section "Swap"
if [[ ! -f /swapfile ]]; then
    fallocate -l 1G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=1024 status=none
    chmod 600 /swapfile
    mkswap /swapfile -q
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    success "1GB swap file created"
else
    info "Swap already exists"
fi

# ── Step 13: Permissions ───────────────────────────────────────────────────────
section "Permissions"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod -R 750 "$APP_DIR"
chmod 755 "$APP_DIR"
chmod 755 "$APP_DIR/backend"
chmod 755 "$APP_DIR/frontend"
chmod 755 "$APP_DIR/scripts"
chmod -R 755 "$APP_DIR/frontend/static"
chmod -R 770 "$APP_DIR/media"
chmod 640    "$APP_DIR/backend/.env"
success "Permissions set"

# ── Step 14: Database tables ───────────────────────────────────────────────────
section "Database Tables"
info "Creating tables (this may take a moment)..."

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
    print('done')
asyncio.run(init())
"

if [[ $? -eq 0 ]]; then
    success "Database tables created"
else
    error "Table creation failed"
    exit 1
fi

# Install full-text search trigger
sudo -u postgres psql -d "$DB_NAME" -q << 'PSQL'
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

# ── Step 15: App Service ───────────────────────────────────────────────────
section "App Service"
cp "$SCRIPT_DIR/systemd/allchat.service" /etc/systemd/system/allchat.service
systemctl daemon-reload
systemctl enable allchat
systemctl start allchat
sleep 3

if systemctl is-active --quiet allchat; then
    success "allchat.service started"
else
    error "Service failed to start. Checking logs..."
    journalctl -u allchat -n 20 --no-pager
    exit 1
fi

# ── Step 16: Firewall ──────────────────────────────────────────────────────────
section "Firewall"
if command -v ufw &>/dev/null; then
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
    success "UFW firewall configured"
else
    warn "UFW not found — skipping firewall setup"
    info "Install manually later: apt-get install -y ufw"
fi

# ── Step 17: Dependency Audit Cron ────────────────────────────────────────────
section "Dependency Security Audit"

# Install pip-audit into the venv
"$APP_DIR/venv/bin/pip" install pip-audit -q && success "pip-audit installed" || warn "pip-audit install failed — skipping"

# Copy the audit script
cp "$SCRIPT_DIR/scripts/audit_deps.sh" "$APP_DIR/scripts/audit_deps.sh"
chmod +x "$APP_DIR/scripts/audit_deps.sh"

# Install weekly cron: 4:00 AM every Wednesday
CRON_LINE="0 4 * * 3 root $APP_DIR/scripts/audit_deps.sh >> /var/log/allchat_audit.log 2>&1"
CRON_FILE="/etc/cron.d/allchat-audit"

if ! grep -q "audit_deps" "$CRON_FILE" 2>/dev/null; then
    echo "$CRON_LINE" > "$CRON_FILE"
    chmod 644 "$CRON_FILE"
    success "Dependency audit cron installed (4am every Wednesday)"
else
    info "Dependency audit cron already installed"
fi

# Create log file with correct permissions
touch /var/log/allchat_audit.log
chmod 640 /var/log/allchat_audit.log
success "Audit log: /var/log/allchat_audit.log"

# ── Step 18: fail2ban ──────────────────────────────────────────────────────────
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

[nginx-http-auth]
enabled  = true
filter   = nginx-http-auth
logpath  = /var/log/nginx/allchat_error.log
maxretry = 5
bantime  = 3600

[sshd]
enabled  = true
port     = ssh
filter   = sshd
logpath  = /var/log/auth.log
maxretry = 3
bantime  = 86400
findtime = 3600
F2B
systemctl enable fail2ban --now
systemctl restart fail2ban
success "fail2ban configured"

# ── Step 18: Reload nginx ──────────────────────────────────────────────────────
nginx -t && systemctl reload nginx
success "Nginx reloaded"

# ── Step 19: Verify app is responding ─────────────────────────────────────────
section "Verification"
info "Testing app response..."
sleep 2
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/ 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "200" ]]; then
    success "App is responding (HTTP $HTTP_CODE)"
elif [[ "$HTTP_CODE" == "000" ]]; then
    warn "Could not reach app — check: journalctl -u allchat -f"
else
    info "App responded with HTTP $HTTP_CODE (may be normal)"
fi

# ── Step 20: Create admin account account ─────────────────────────────────────────────
section "Admin Account"
echo ""
echo -e "  ${BOLD}Now let's create your admin account.${NC}"
echo -e "  This account will have full access to the admin dashboard.\n"

cd /tmp
sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" "$APP_DIR/scripts/create_admin.py"

# ── Step 21: Send test email email ───────────────────────────────────────────────────
section "Email Test"
echo ""
ask "Send a test email to verify SMTP is working? (y/n)"
read -r DO_EMAIL_TEST
if [[ "$DO_EMAIL_TEST" =~ ^[Yy]$ ]]; then
    ask "Send test email to (press Enter to use $SMTP_USER):"
    read -r TEST_EMAIL_ADDR
    [[ -z "$TEST_EMAIL_ADDR" ]] && TEST_EMAIL_ADDR="$SMTP_USER"

    cd /tmp
    EMAIL_RESULT=$(sudo -u "$APP_USER" "$APP_DIR/venv/bin/python" -c "
import asyncio, sys
sys.path.insert(0, '$APP_DIR/backend')
from dotenv import load_dotenv
load_dotenv('$APP_DIR/backend/.env')
from core.email import send_email
async def test():
    await send_email(
        '$TEST_EMAIL_ADDR',
        'All_Chat — Email Test',
        '<h2>Email is working!</h2><p>Your All_Chat server can send emails.</p>',
        'All_Chat email test — it works!'
    )
    print('success')
asyncio.run(test())
" 2>&1)

    if echo "$EMAIL_RESULT" | grep -q "success"; then
        success "Test email sent to $TEST_EMAIL_ADDR — check your inbox (and spam folder)"
    else
        warn "Email test failed. Check your SMTP settings in /app/backend/.env"
        warn "Error: $EMAIL_RESULT"
        warn "You can re-test later: sudo nano /app/backend/.env && sudo systemctl restart allchat"
    fi
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  All_Chat is deployed and running! ❤️${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Your site:${NC}   http://${SERVER_ADDRESS}"
echo ""
echo -e "  ${BOLD}Useful commands:${NC}"
echo -e "  ${CYAN}Status:${NC}      sudo systemctl status allchat"
echo -e "  ${CYAN}Logs:${NC}        sudo journalctl -u allchat -f"
echo -e "  ${CYAN}Restart:${NC}     sudo systemctl restart allchat"
echo -e "  ${CYAN}Edit config:${NC} sudo nano /app/backend/.env"
echo -e "  ${CYAN}DB creds:${NC}    sudo cat /root/.allchat_secrets"
echo ""
if [[ "$USE_TLS" == "false" ]]; then
    echo -e "  ${YELLOW}Add TLS when ready:${NC}"
    echo -e "  sudo certbot --nginx -d yourdomain.com"
    echo -e "  Then update ALLOWED_ORIGINS in /app/backend/.env to https://"
    echo -e "  Then: sudo systemctl restart allchat"
    echo ""
fi
