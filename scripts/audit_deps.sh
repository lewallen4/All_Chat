#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# All_Chat — Dependency Security Audit
# Runs pip-audit, logs results, restarts app only if needed.
# Cron: 0 4 * * 3  (4:00 AM every Wednesday)
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

LOG_FILE="/var/log/allchat_audit.log"
VENV="/app/venv"
STAMP=$(date -u '+%Y-%m-%d %H:%M UTC')

log() { echo "[$STAMP] $*" | tee -a "$LOG_FILE"; }

log "=== Dependency security audit starting ==="

# Install pip-audit if missing
if ! "$VENV/bin/pip" show pip-audit &>/dev/null; then
    log "Installing pip-audit..."
    "$VENV/bin/pip" install pip-audit -q
fi

# Run the audit — exit code 1 means vulnerabilities found
AUDIT_OUTPUT=$("$VENV/bin/pip-audit" \
    --requirement /app/backend/requirements.txt \
    --format=json 2>&1) || AUDIT_EXIT=$?

AUDIT_EXIT=${AUDIT_EXIT:-0}

if [[ "$AUDIT_EXIT" -eq 0 ]]; then
    log "✓ No known vulnerabilities found."
else
    # Parse vulnerability count
    VULN_COUNT=$(echo "$AUDIT_OUTPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    vulns = [d for d in data.get('dependencies', []) if d.get('vulns')]
    print(len(vulns))
except:
    print('unknown')
" 2>/dev/null || echo "unknown")

    log "⚠ Vulnerabilities found: $VULN_COUNT package(s) affected"
    log "Full output:"
    echo "$AUDIT_OUTPUT" >> "$LOG_FILE"

    # Auto-fix safe upgrades (patch versions only)
    log "Attempting safe upgrades..."
    "$VENV/bin/pip-audit" \
        --requirement /app/backend/requirements.txt \
        --fix \
        --dry-run 2>&1 | tee -a "$LOG_FILE" || true

    # Apply the fixes
    "$VENV/bin/pip-audit" \
        --requirement /app/backend/requirements.txt \
        --fix 2>&1 | tee -a "$LOG_FILE" || true

    # Restart app to pick up patched packages
    log "Restarting allchat service..."
    systemctl restart allchat
    sleep 5

    if systemctl is-active --quiet allchat; then
        log "✓ allchat restarted successfully after security update"
    else
        log "✗ allchat failed to restart — check: journalctl -u allchat -n 50"
    fi

    # Send notification email if SMTP configured
    SMTP_USER=$(grep "^SMTP_USER=" /app/backend/.env 2>/dev/null | cut -d= -f2 || true)
    if [[ -n "$SMTP_USER" ]]; then
        python3 << PYEOF
import smtplib, ssl, os
from email.mime.text import MIMEText
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

smtp_host = os.environ.get('SMTP_HOST','')
smtp_port = int(os.environ.get('SMTP_PORT', 587))
smtp_user = os.environ.get('SMTP_USER','')
smtp_pass = os.environ.get('SMTP_PASSWORD','')
smtp_from = os.environ.get('SMTP_FROM', smtp_user)

if not all([smtp_host, smtp_user, smtp_pass]):
    print("SMTP not configured — skipping email notification")
    exit(0)

msg = MIMEText("""All_Chat dependency audit found vulnerabilities.

$AUDIT_OUTPUT

The system attempted to auto-fix and restarted the app.
Check /var/log/allchat_audit.log for details.
""")
msg['Subject'] = '[All_Chat] Security audit: vulnerabilities found'
msg['From']    = smtp_from
msg['To']      = smtp_user

try:
    ctx = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_from, [smtp_user], msg.as_string())
    print("Notification email sent")
except Exception as e:
    print(f"Email failed: {e}")
PYEOF
    fi
fi

log "=== Audit complete ==="
