# ⬡ All_Chat

> Open conversation. Encrypted by default.

A self-hosted, privacy-first social platform combining the best of Twitter and Reddit — with real security baked in from day one.

---

## Features

| Feature | Details |
|---|---|
| **Posts** | Text, image (up to 10MB), link with preview unfurling |
| **Feed** | New · Top · Hot — filter by 24h / week / month / year / all time |
| **Voting** | Upvote / downvote with Wilson score ranking |
| **Comments** | Threaded comments with voting and reply support |
| **Search** | PostgreSQL full-text search across posts and users |
| **Profiles** | Markdown bio, avatar upload, join date |
| **Follow** | Follow users, dedicated following feed |
| **Bookmarks** | Save posts for later |
| **E2E Messages** | Direct messages encrypted with X25519 + AES-256-GCM (Kyber-768 ready) |
| **Notifications** | In-app bell for votes, follows, comments, messages |
| **Auth** | Registration, email verification, JWT, password reset |
| **Themes** | Dark (navy/purple/gold) and Light (warm vanilla) |

---

## Security

- **Argon2id** password hashing (OWASP recommended)
- **JWT** access + refresh token rotation
- **Rate limiting** — Redis sliding window, per-IP per-route
- **Input sanitization** — `bleach` server-side, DOMPurify-style client-side
- **Image processing** — Pillow strips EXIF, re-encodes, enforces dimensions
- **SSRF protection** — link preview blocks private IP ranges
- **Security headers** — HSTS, CSP, X-Frame-Options, etc.
- **E2E encryption** — private keys never leave the browser (IndexedDB)
- **Soft deletes** — vote integrity preserved
- **Post-quantum ready** — Kyber-768 via liboqs (opt-in, see below)

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn (async) |
| Database | PostgreSQL 16 + asyncpg |
| Cache | Redis |
| Auth | JWT (python-jose) + Argon2id |
| Frontend | Vanilla JS + CSS custom properties |
| Reverse proxy | Nginx + Let's Encrypt TLS |
| Process manager | systemd |
| Migrations | Alembic |

---

## Quick Start (Fresh Debian 12 Server)

```bash
# 1. Clone the repo onto your server
git clone https://github.com/YOUR_USERNAME/all_chat.git
cd all_chat

# 2. Edit setup.sh — set your domain and email
nano setup.sh

# 3. Run the bootstrap (as root)
chmod +x setup.sh
sudo ./setup.sh
```

The script will:
- Install and configure PostgreSQL, Redis, Nginx, Certbot, Python 3.11
- Create a dedicated `allchat` system user
- Set up the Python virtualenv and install dependencies
- Create the database, run schema migrations, install triggers
- Generate a secure `.env` with random `SECRET_KEY` and DB password
- Configure Nginx with TLS (Let's Encrypt)
- Install and start the `allchat` systemd service
- Configure UFW firewall and fail2ban

Credentials are saved to `/root/.allchat_secrets` (root-readable only).

---

## Configuration

All configuration lives in `/app/backend/.env`. Key settings:

```env
SECRET_KEY=...             # Auto-generated — do not change after launch
DATABASE_URL=...           # Auto-configured by setup.sh
SMTP_HOST=smtp.example.com # Configure for email verification
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASSWORD=...
SMTP_FROM=noreply@yourdomain.com
ALLOWED_ORIGINS=["https://yourdomain.com"]
PQ_ENABLED=false           # Set true after installing liboqs
```

After editing `.env`:
```bash
sudo systemctl restart allchat
```

---

## Post-Quantum Encryption (Optional)

All_Chat supports Kyber-768 (ML-KEM) for DM key exchange when liboqs is installed:

```bash
# Install liboqs C library
git clone https://github.com/open-quantum-safe/liboqs.git
cd liboqs && mkdir build && cd build
cmake -DCMAKE_INSTALL_PREFIX=/usr/local ..
make -j$(nproc) && sudo make install

# Install Python bindings
sudo /app/venv/bin/pip install liboqs-python

# Enable in config
sudo sed -i 's/PQ_ENABLED=false/PQ_ENABLED=true/' /app/backend/.env
sudo systemctl restart allchat
```

When `PQ_ENABLED=false` (default), the system falls back to X25519 ECDH — still secure, just not post-quantum.

---

## Operations

```bash
# Service management
sudo systemctl status  allchat
sudo systemctl restart allchat
sudo systemctl reload  allchat   # graceful reload (SIGHUP)

# Logs
journalctl -u allchat -f          # live app logs
tail -f /var/log/nginx/allchat_error.log

# Database
sudo -u postgres psql allchat

# Backup database
sudo -u postgres pg_dump allchat > allchat_$(date +%Y%m%d).sql

# Update application
cd /path/to/all_chat
git pull
sudo cp -r backend/. /app/backend/
sudo cp -r frontend/. /app/frontend/
sudo /app/venv/bin/pip install -r /app/backend/requirements.txt -q
sudo systemctl restart allchat
```

---

## Project Structure

```
all_chat/
├── backend/
│   ├── main.py                  # FastAPI app entry point
│   ├── core/
│   │   ├── config.py            # Settings (env-based)
│   │   ├── database.py          # Async SQLAlchemy
│   │   ├── security.py          # Argon2, JWT, sanitization, headers
│   │   ├── rate_limiter.py      # Redis sliding window rate limiter
│   │   ├── deps.py              # JWT auth dependency
│   │   ├── email.py             # Async SMTP email service
│   │   └── crypto.py            # Kyber-768 / X25519 + AES-256-GCM
│   ├── models/
│   │   ├── user.py              # User model
│   │   ├── post.py              # Post (text/image/link, tsvector)
│   │   ├── vote.py              # Votes (Wilson score)
│   │   ├── message.py           # E2E encrypted DMs
│   │   ├── comment.py           # Threaded comments
│   │   ├── follow.py            # Follow relationships
│   │   ├── bookmark.py          # Saved posts
│   │   └── notification.py      # In-app notifications
│   ├── routers/
│   │   ├── auth.py              # Register, login, verify, reset
│   │   ├── users.py             # Profiles, avatars, public keys
│   │   ├── posts.py             # Create/read/delete posts
│   │   ├── feed.py              # Sorted/filtered feed + caching
│   │   ├── votes.py             # Vote with cache invalidation
│   │   ├── messages.py          # E2E DMs
│   │   ├── search.py            # Full-text search
│   │   ├── media.py             # Link preview (SSRF-protected)
│   │   └── social.py            # Follow, bookmarks, notifications, comments
│   ├── services/
│   │   └── wilson.py            # Wilson score + hot score algorithms
│   ├── schemas/
│   │   └── schemas.py           # All Pydantic request/response models
│   ├── alembic/                 # Database migrations
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── templates/
│   │   └── index.html           # SPA shell
│   └── static/
│       ├── css/
│       │   ├── themes.css       # Dark + light theme variables
│       │   ├── main.css         # Layout, typography, nav
│       │   └── components.css   # All UI components
│       └── js/
│           ├── api.js           # Fetch client + token refresh
│           ├── auth.js          # Login/register/logout
│           ├── crypto.js        # Web Crypto E2E (IndexedDB keys)
│           ├── ui.js            # Toast, modal, nav, theme, time
│           ├── feed.js          # Feed, sorting, voting
│           ├── post.js          # Post submission
│           ├── messages.js      # Encrypted DM UI
│           ├── profile.js       # Profile view + edit
│           ├── search.js        # Search results
│           ├── social.js        # Follow, bookmarks, notifications, comments
│           ├── router.js        # SPA client-side router
│           └── app.js           # Bootstrap + route definitions
├── nginx/
│   ├── allchat.conf             # Nginx site config (TLS, rate limits)
│   └── proxy-params.conf        # Reusable proxy headers
├── systemd/
│   └── allchat.service          # systemd unit (hardened)
├── setup.sh                     # Full Debian bootstrap script
└── README.md
```

---

## Roadmap

- [ ] WebSocket real-time feed updates
- [ ] CAPTCHA / anti-bot on registration
- [ ] Admin dashboard (user management, post moderation)
- [ ] Post tags / categories
- [ ] CDN support (MinIO / S3-compatible)
- [ ] OAuth2 (GitHub, Google)
- [ ] Mobile PWA manifest
- [ ] Two-factor authentication (TOTP)

---

## License

MIT — do what you want, but don't remove the encryption. People deserve privacy. ❤️
