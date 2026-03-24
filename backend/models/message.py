"""
All_Chat - Message Model
E2E encrypted DMs. Server stores ciphertext only — never plaintext.
"""

from datetime import datetime, timezone
from sqlalchemy import Integer, ForeignKey, DateTime, Text, Boolean, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class Message(Base):
    __tablename__ = "messages"

    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    sender_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    recipient_id: Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                                   nullable=False, index=True)
    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                   default=lambda: datetime.now(timezone.utc), index=True)
    read_at:      Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted_sender:    Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted_recipient: Mapped[bool] = mapped_column(Boolean, default=False)

    # Encrypted payload (AES-256-GCM, key exchanged via Kyber/X25519)
    # All fields are base64-encoded bytes
    kyber_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)  # encapsulated shared secret
    aes_ciphertext:   Mapped[str] = mapped_column(Text, nullable=False)  # encrypted message body
    aes_nonce:        Mapped[str] = mapped_column(String(32), nullable=False)  # 12-byte GCM nonce

    # Algorithm tag for forward compatibility
    crypto_version: Mapped[str] = mapped_column(String(16), default="kyber768-aes256gcm")

    sender:    Mapped["User"] = relationship("User", foreign_keys=[sender_id],    back_populates="sent_messages")
    recipient: Mapped["User"] = relationship("User", foreign_keys=[recipient_id], back_populates="recv_messages")

    __table_args__ = (
        Index("ix_messages_conversation", "sender_id", "recipient_id", "created_at"),
    )
