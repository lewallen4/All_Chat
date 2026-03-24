"""
All_Chat - Messages Router
End-to-end encrypted direct messages.

The server stores ONLY ciphertext. It never sees plaintext.
Encryption/decryption happens entirely client-side using the
Web Crypto API (X25519 + AES-GCM) or liboqs (Kyber-768) in the browser.

Flow:
  1. Sender fetches recipient's public key via GET /api/users/{username}
  2. Sender encapsulates shared secret client-side → (kyber_ciphertext, shared_secret)
  3. Sender encrypts message body with AES-256-GCM → (aes_ciphertext, aes_nonce)
  4. Sender POSTs {recipient_username, kyber_ciphertext, aes_ciphertext, aes_nonce}
  5. Server stores encrypted blob, sends notification email
  6. Recipient fetches messages, decapsulates kyber_ciphertext with their private key
  7. Recipient decrypts aes_ciphertext with shared_secret — all client-side
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func, desc

from core.database import get_db
from core.deps import get_current_user
from core.email import send_new_message_notification
from core.security import sanitize_text
from models.user import User
from models.message import Message
from schemas.schemas import (
    SendMessageRequest, MessageResponse, ConversationSummary, MessageOut
)

router = APIRouter()


@router.post("", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    req: SendMessageRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve recipient
    clean_username = sanitize_text(req.recipient_username).lower()
    result = await db.execute(
        select(User).where(User.username == clean_username, User.is_active == True)
    )
    recipient = result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found.")
    if recipient.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot message yourself.")
    if not recipient.pq_public_key:
        raise HTTPException(
            status_code=400,
            detail="Recipient has not registered an encryption key. They need to log in first."
        )

    # Validate crypto fields (basic length sanity check)
    if not req.kyber_ciphertext or not req.aes_ciphertext or not req.aes_nonce:
        raise HTTPException(status_code=400, detail="Encrypted message payload is incomplete.")

    message = Message(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        kyber_ciphertext=req.kyber_ciphertext,
        aes_ciphertext=req.aes_ciphertext,
        aes_nonce=req.aes_nonce,
        crypto_version=req.crypto_version,
    )
    db.add(message)
    await db.flush()

    # Notify recipient (non-blocking)
    background_tasks.add_task(
        send_new_message_notification, recipient.email, current_user.username
    )

    return {"message": "Message sent."}


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return list of unique conversation partners with last message time and unread count."""
    uid = current_user.id

    # Get all unique conversation partners
    sent = await db.execute(
        select(Message.recipient_id, func.max(Message.created_at).label("last_at"))
        .where(Message.sender_id == uid, Message.is_deleted_sender == False)
        .group_by(Message.recipient_id)
    )
    received = await db.execute(
        select(Message.sender_id, func.max(Message.created_at).label("last_at"))
        .where(Message.recipient_id == uid, Message.is_deleted_recipient == False)
        .group_by(Message.sender_id)
    )

    # Merge and deduplicate, keeping latest timestamp per partner
    partner_times: dict[int, datetime] = {}
    for row in sent.all():
        pid, last = row
        if pid not in partner_times or last > partner_times[pid]:
            partner_times[pid] = last
    for row in received.all():
        pid, last = row
        if pid not in partner_times or last > partner_times[pid]:
            partner_times[pid] = last

    if not partner_times:
        return []

    # Fetch user objects
    users_result = await db.execute(
        select(User).where(User.id.in_(partner_times.keys()))
    )
    users = {u.id: u for u in users_result.scalars().all()}

    # Count unread per partner
    conversations = []
    for partner_id, last_at in sorted(partner_times.items(), key=lambda x: x[1], reverse=True):
        unread_result = await db.execute(
            select(func.count()).select_from(Message).where(
                Message.sender_id == partner_id,
                Message.recipient_id == uid,
                Message.read_at == None,
                Message.is_deleted_recipient == False,
            )
        )
        unread = unread_result.scalar() or 0
        if partner_id in users:
            conversations.append(ConversationSummary(
                user=users[partner_id],
                last_message_at=last_at,
                unread_count=unread,
            ))

    return conversations


@router.get("/{username}", response_model=list[MessageResponse])
async def get_conversation(
    username: str,
    page: int = Query(1, ge=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch paginated message history with a specific user. Returns encrypted blobs."""
    clean_username = sanitize_text(username).lower()
    result = await db.execute(select(User).where(User.username == clean_username))
    partner = result.scalar_one_or_none()
    if not partner:
        raise HTTPException(status_code=404, detail="User not found.")

    uid = current_user.id
    pid = partner.id

    page_size = 50
    offset = (page - 1) * page_size

    messages_result = await db.execute(
        select(Message)
        .where(
            or_(
                and_(
                    Message.sender_id == uid,
                    Message.recipient_id == pid,
                    Message.is_deleted_sender == False,
                ),
                and_(
                    Message.sender_id == pid,
                    Message.recipient_id == uid,
                    Message.is_deleted_recipient == False,
                ),
            )
        )
        .order_by(desc(Message.created_at))
        .offset(offset)
        .limit(page_size)
    )
    messages = messages_result.scalars().all()

    # Mark unread messages as read
    now = datetime.now(timezone.utc)
    for msg in messages:
        if msg.recipient_id == uid and msg.read_at is None:
            msg.read_at = now

    await db.flush()

    # Load relationships
    responses = []
    for msg in reversed(messages):  # chronological order
        await db.refresh(msg, ["sender", "recipient"])
        responses.append(msg)

    return responses


@router.delete("/{message_id}", response_model=MessageOut)
async def delete_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Message).where(Message.id == message_id))
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")
    if message.sender_id != current_user.id and message.recipient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized.")

    # Soft delete per side — only hard delete when both sides deleted
    if message.sender_id == current_user.id:
        message.is_deleted_sender = True
    if message.recipient_id == current_user.id:
        message.is_deleted_recipient = True

    if message.is_deleted_sender and message.is_deleted_recipient:
        await db.delete(message)

    return {"message": "Message deleted."}
