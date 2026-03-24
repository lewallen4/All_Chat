"""
All_Chat - Post-Quantum Cryptography
Kyber-768 (ML-KEM) key encapsulation for E2E encrypted DMs.
Uses liboqs-python bindings.

Key exchange flow:
  1. Recipient generates Kyber keypair on registration, stores public key server-side.
  2. Sender fetches recipient's public key.
  3. Sender encapsulates a shared secret → gets (ciphertext, shared_secret).
  4. Sender encrypts message with AES-256-GCM using shared_secret.
  5. Sender sends: {kyber_ciphertext, aes_ciphertext, aes_nonce} to server.
  6. Recipient decapsulates kyber_ciphertext with private key → shared_secret.
  7. Recipient decrypts aes_ciphertext with shared_secret.

Server NEVER sees plaintext or shared secrets.
"""

import base64
import os
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

try:
    import oqs
    OQS_AVAILABLE = True
except ImportError:
    OQS_AVAILABLE = False
    logger.warning("liboqs-python not available. PQ crypto disabled, falling back to X25519.")

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


KEM_ALGORITHM = "Kyber768"


# ─── Key Generation ──────────────────────────────────────────────────────────

def generate_keypair() -> Tuple[bytes, bytes]:
    """
    Generate a keypair for key encapsulation.
    Returns (public_key_bytes, private_key_bytes).
    Uses Kyber-768 if available, X25519 fallback.
    """
    if OQS_AVAILABLE:
        kem = oqs.KeyEncapsulation(KEM_ALGORITHM)
        public_key = kem.generate_keypair()
        private_key = kem.export_secret_key()
        return public_key, private_key
    else:
        # X25519 fallback
        priv = X25519PrivateKey.generate()
        pub = priv.public_key()
        return (
            pub.public_bytes(Encoding.Raw, PublicFormat.Raw),
            priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()),
        )


def encapsulate(public_key_bytes: bytes) -> Tuple[bytes, bytes]:
    """
    Encapsulate a shared secret using recipient's public key.
    Returns (ciphertext, shared_secret).
    """
    if OQS_AVAILABLE:
        kem = oqs.KeyEncapsulation(KEM_ALGORITHM)
        ciphertext, shared_secret = kem.encap_secret(public_key_bytes)
        return ciphertext, shared_secret
    else:
        # Ephemeral X25519 + HKDF fallback
        ephemeral_priv = X25519PrivateKey.generate()
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
        recipient_pub = X25519PublicKey.from_public_bytes(public_key_bytes)
        raw_shared = ephemeral_priv.exchange(recipient_pub)
        shared_secret = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"allchat-dm"
        ).derive(raw_shared)
        ciphertext = ephemeral_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return ciphertext, shared_secret


def decapsulate(ciphertext: bytes, private_key_bytes: bytes) -> bytes:
    """Decapsulate to recover shared secret."""
    if OQS_AVAILABLE:
        kem = oqs.KeyEncapsulation(KEM_ALGORITHM, secret_key=private_key_bytes)
        return kem.decap_secret(ciphertext)
    else:
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey, X25519PublicKey
        )
        priv = X25519PrivateKey.from_private_bytes(private_key_bytes)
        sender_pub = X25519PublicKey.from_public_bytes(ciphertext)
        raw_shared = priv.exchange(sender_pub)
        return HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"allchat-dm"
        ).derive(raw_shared)


# ─── AES-256-GCM Message Encryption ─────────────────────────────────────────

def encrypt_message(plaintext: str, shared_secret: bytes) -> Tuple[bytes, bytes]:
    """
    Encrypt message with AES-256-GCM.
    Returns (ciphertext, nonce).
    """
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(shared_secret[:32])
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def decrypt_message(ciphertext: bytes, nonce: bytes, shared_secret: bytes) -> str:
    """Decrypt AES-256-GCM ciphertext."""
    aesgcm = AESGCM(shared_secret[:32])
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


# ─── Serialization helpers ───────────────────────────────────────────────────

def encode_b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def decode_b64(data: str) -> bytes:
    return base64.b64decode(data.encode())


def is_pq_available() -> bool:
    return OQS_AVAILABLE
