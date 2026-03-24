"""
All_Chat - Pydantic Schemas
Request/response validation for all API endpoints.
"""

from pydantic import BaseModel, EmailStr, field_validator, model_validator, HttpUrl
from typing import Optional
from datetime import datetime
import re


# ─── Auth ─────────────────────────────────────────────────────────────────────

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3–32 chars, letters/numbers/underscores only.")
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        from core.security import validate_password_strength
        errors = validate_password_strength(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v


class LoginRequest(BaseModel):
    username: str  # accept username or email
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        from core.security import validate_password_strength
        errors = validate_password_strength(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v


class VerifyEmailRequest(BaseModel):
    token: str


# ─── Users ────────────────────────────────────────────────────────────────────

class UserPublic(BaseModel):
    id: int
    username: str
    display_name: Optional[str]
    bio_markdown: Optional[str]
    avatar_path: Optional[str]
    created_at: datetime
    pq_public_key: Optional[str]  # for DM key exchange

    model_config = {"from_attributes": True}


class UserPrivate(UserPublic):
    email: str
    email_verified: bool
    is_active: bool

    model_config = {"from_attributes": True}


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None
    bio_markdown: Optional[str] = None

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v):
        if v is not None:
            from core.security import sanitize_text
            v = sanitize_text(v)
            if len(v) > 64:
                raise ValueError("Display name too long (max 64 chars).")
        return v

    @field_validator("bio_markdown")
    @classmethod
    def validate_bio(cls, v):
        if v is not None and len(v) > 5000:
            raise ValueError("Bio too long (max 5000 chars).")
        return v


class RegisterPublicKeyRequest(BaseModel):
    public_key: str  # base64-encoded Kyber/X25519 public key


# ─── Posts ────────────────────────────────────────────────────────────────────

class CreatePostRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    link_url: Optional[str] = None
    channel_slug: Optional[str] = None  # if set, post goes into that channel

    @model_validator(mode="after")
    def at_least_one_field(self):
        if not self.title and not self.body and not self.link_url:
            raise ValueError("Post must have at least a title, body text, or link.")
        return self

    @field_validator("title")
    @classmethod
    def validate_title(cls, v):
        if v is not None:
            from core.security import sanitize_text
            v = sanitize_text(v)
            if len(v) > 300:
                raise ValueError("Title too long (max 300 chars).")
            if len(v) < 1:
                raise ValueError("Title cannot be empty.")
        return v

    @field_validator("body")
    @classmethod
    def validate_body(cls, v):
        if v is not None:
            from core.security import sanitize_html
            v = sanitize_html(v)
            if len(v) > 40000:
                raise ValueError("Post body too long (max 40,000 chars).")
        return v

    @field_validator("link_url")
    @classmethod
    def validate_link(cls, v):
        if v is not None:
            # Basic URL validation
            if not v.startswith(("http://", "https://")):
                raise ValueError("Link must be a valid http/https URL.")
            if len(v) > 2048:
                raise ValueError("Link URL too long.")
        return v


class ChannelMini(BaseModel):
    slug: str
    name: str
    avatar_path: Optional[str] = None
    model_config = {"from_attributes": True}


class PostResponse(BaseModel):
    id: int
    author: UserPublic
    title: Optional[str]
    body: Optional[str]
    image_path: Optional[str]
    link_url: Optional[str]
    link_title: Optional[str]
    link_preview: Optional[str]
    upvotes: int
    downvotes: int
    wilson_score: float
    created_at: datetime
    updated_at: datetime
    user_vote: Optional[int] = None       # +1, -1, or None
    channel_id: Optional[int] = None
    channel: Optional[ChannelMini] = None
    is_pinned: bool = False
    removed_by_lead: bool = False

    model_config = {"from_attributes": True}


class FeedResponse(BaseModel):
    posts: list[PostResponse]
    total: int
    page: int
    has_more: bool


# ─── Votes ────────────────────────────────────────────────────────────────────

class VoteRequest(BaseModel):
    post_id: int
    value: int  # +1 or -1

    @field_validator("value")
    @classmethod
    def validate_value(cls, v):
        if v not in (1, -1):
            raise ValueError("Vote value must be +1 or -1.")
        return v


class VoteResponse(BaseModel):
    post_id: int
    upvotes: int
    downvotes: int
    wilson_score: float
    user_vote: Optional[int]


# ─── Messages ────────────────────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    recipient_username: str
    kyber_ciphertext: str   # base64: encapsulated shared secret
    aes_ciphertext: str     # base64: encrypted message
    aes_nonce: str          # base64: 12-byte nonce
    crypto_version: str = "kyber768-aes256gcm"


class MessageResponse(BaseModel):
    id: int
    sender: UserPublic
    recipient: UserPublic
    kyber_ciphertext: str
    aes_ciphertext: str
    aes_nonce: str
    crypto_version: str
    created_at: datetime
    read_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ConversationSummary(BaseModel):
    user: UserPublic
    last_message_at: datetime
    unread_count: int


# ─── Search ──────────────────────────────────────────────────────────────────

class ChannelMiniSearch(BaseModel):
    slug: str
    name: str
    description: Optional[str]
    avatar_path: Optional[str]
    member_count: int
    post_count: int
    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    posts: list[PostResponse]
    users: list[UserPublic]
    channels: list[ChannelMiniSearch] = []
    total_posts: int
    total_users: int
    total_channels: int = 0


# ─── Generic ─────────────────────────────────────────────────────────────────

class MessageOut(BaseModel):
    message: str


class ErrorOut(BaseModel):
    detail: str
