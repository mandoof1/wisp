"""AES-256-GCM encrypt/decrypt for C2 payloads + X25519 key exchange.

Wire payload envelope:
  24-char hex nonce || base64-encoded ciphertext+tag

Phase 2 adds X25519 ephemeral key exchange for per-session keys.
"""

import os
import base64
import hashlib
import threading
from base64 import b64decode, b64encode
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from server.config import PSK


# ═══════════════════════════════════════════════════════════════════════
# Session Key Store
# ═══════════════════════════════════════════════════════════════════════

class SessionKeyStore:
    """Thread-safe in-memory store for per-beacon session keys (X25519-derived)."""

    def __init__(self):
        self._store: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def set(self, key_id: str, aes_key: bytes):
        with self._lock:
            self._store[key_id] = aes_key

    def get(self, key_id: str) -> Optional[bytes]:
        with self._lock:
            return self._store.get(key_id)

    def delete(self, key_id: str):
        with self._lock:
            self._store.pop(key_id, None)

    def clear(self):
        with self._lock:
            self._store.clear()


session_keys = SessionKeyStore()


# ═══════════════════════════════════════════════════════════════════════
# X25519 Key Exchange
# ═══════════════════════════════════════════════════════════════════════

def generate_x25519_keypair() -> tuple[bytes, bytes]:
    """Generate an X25519 ephemeral keypair. Returns (private_bytes, public_bytes)."""
    private_key = X25519PrivateKey.generate()
    private_bytes = private_key.private_bytes_raw()
    public_bytes = private_key.public_key().public_bytes_raw()
    return private_bytes, public_bytes


def compute_shared_secret(private_bytes: bytes, peer_public_bytes: bytes) -> bytes:
    """Compute an X25519 shared secret."""
    private_key = X25519PrivateKey.from_private_bytes(private_bytes)
    public_key = X25519PublicKey.from_public_bytes(peer_public_bytes)
    return private_key.exchange(public_key)


def derive_session_key(shared_secret: bytes) -> bytes:
    """Derive a 32-byte AES-256-GCM key from an X25519 shared secret.

    Uses SHA-256(shared_secret || domain_separator) to match Go implant
    (which avoids importing golang.org/x/crypto/hkdf for cross-compilation).
    """
    return hashlib.sha256(shared_secret + b"c2-framework-v1").digest()


# ═══════════════════════════════════════════════════════════════════════
# AES-256-GCM Payload Encryption (key-parameterized)
# ═══════════════════════════════════════════════════════════════════════

def encrypt(plaintext: bytes, key: Optional[bytes] = None) -> str:
    """Encrypt bytes with AES-256-GCM. Returns 'nonce_hex:ciphertext_b64'.

    Args:
        plaintext: bytes to encrypt.
        key: 32-byte AES key. Defaults to PSK from config.
    """
    if key is None:
        key = PSK
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return f"{nonce.hex()}:{b64encode(ciphertext).decode()}"


def decrypt(payload: str, key: Optional[bytes] = None) -> bytes:
    """Decrypt a 'nonce_hex:ciphertext_b64' string back to bytes.

    Args:
        payload: encrypted string.
        key: 32-byte AES key. Defaults to PSK from config.
    """
    if key is None:
        key = PSK
    try:
        nonce_hex, ct_b64 = payload.split(":", 1)
        nonce = bytes.fromhex(nonce_hex)
        ciphertext = b64decode(ct_b64)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")


def encrypt_json(data: dict, key: Optional[bytes] = None) -> str:
    """Encrypt a JSON-serializable dict.

    Args:
        data: dict to encrypt.
        key: 32-byte AES key. Defaults to PSK from config.
    """
    import json
    return encrypt(json.dumps(data, separators=(",", ":")).encode("utf-8"), key)


def decrypt_json(payload: str, key: Optional[bytes] = None) -> dict:
    """Decrypt a payload back to a dict.

    Args:
        payload: encrypted string.
        key: 32-byte AES key. Defaults to PSK from config.
    """
    import json
    return json.loads(decrypt(payload, key).decode("utf-8"))


def resolve_key(key_id: Optional[str]) -> bytes:
    """Resolve the encryption key for a request.

    Checks the session key store first (by implant public key hex),
    falls back to the static PSK.
    """
    if key_id:
        session_key = session_keys.get(key_id)
        if session_key:
            return session_key
    return PSK
