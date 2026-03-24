#!/usr/bin/env python3
"""
All_Chat — Create Admin User
Run this after setup.sh to create your first admin account.

Usage (on the server):
    cd /app
    sudo -u allchat /app/venv/bin/python scripts/create_admin.py

Or during development from the project root:
    python scripts/create_admin.py
"""

import asyncio
import sys
import os
import re
import getpass

# Resolve backend path whether run from project root or /app
_here        = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.join(_here, '..', 'backend')
sys.path.insert(0, os.path.normpath(_backend_dir))

# Load .env from backend dir
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_backend_dir, '.env'))
except ImportError:
    pass  # dotenv optional; env vars may already be set


async def main():
    # Late imports — after sys.path and env are set
    from core.config import settings
    from core.security import hash_password, validate_password_strength
    from core.database import AsyncSessionLocal, engine, Base
    from sqlalchemy import select
    import models          # noqa: registers all ORM models
    from models.user import User

    print("\n⬡  All_Chat — Admin Account Setup")
    print("─" * 42)

    # Ensure all tables exist (idempotent)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Database schema verified\n")

    async with AsyncSessionLocal() as db:

        # ── Username ─────────────────────────────────────────────
        while True:
            username = input("Username: ").strip().lower()
            if not username:
                print("  Username cannot be empty.\n")
                continue
            if not re.match(r'^[a-zA-Z0-9_]{3,32}$', username):
                print("  Must be 3–32 chars, letters/numbers/underscores only.\n")
                continue

            result   = await db.execute(select(User).where(User.username == username))
            existing = result.scalar_one_or_none()

            if existing:
                if existing.is_admin:
                    print(f"\n  @{username} is already an admin. Nothing to do.\n")
                    return
                ans = input(f"  @{username} already exists. Promote to admin? [y/N] ").strip().lower()
                if ans == 'y':
                    existing.is_admin       = True
                    existing.email_verified = True
                    existing.is_active      = True
                    await db.commit()
                    print(f"\n✓ @{username} promoted to admin.\n")
                    return
                print()
                continue
            break

        # ── Email ─────────────────────────────────────────────────
        while True:
            email = input("Email address: ").strip().lower()
            if not email or '@' not in email or '.' not in email:
                print("  Enter a valid email address.\n")
                continue
            result = await db.execute(select(User).where(User.email == email))
            if result.scalar_one_or_none():
                print("  That email is already registered.\n")
                continue
            break

        # ── Password ──────────────────────────────────────────────
        while True:
            try:
                password = getpass.getpass("Password (min 10 chars): ")
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return
            errors = validate_password_strength(password)
            if errors:
                for err in errors:
                    print(f"  ✗ {err}")
                print()
                continue
            try:
                confirm = getpass.getpass("Confirm password: ")
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return
            if password != confirm:
                print("  ✗ Passwords do not match.\n")
                continue
            break

        # ── Create ────────────────────────────────────────────────
        user = User(
            username       = username,
            email          = email,
            password_hash  = hash_password(password),
            email_verified = True,   # admin accounts skip email verification
            is_active      = True,
            is_admin       = True,
        )
        db.add(user)
        await db.commit()

    print(f"\n✓ Admin account created successfully!")
    print(f"  Username : @{username}")
    print(f"  Email    : {email}")
    print(f"  Role     : admin")
    print(f"\n  Log in at your domain and the ◈ Admin link")
    print(f"  will appear in the sidebar.\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
