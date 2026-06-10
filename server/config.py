"""Server configuration and shared constants."""

import os
from pathlib import Path

SERVER_HOST = os.getenv("C2_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("C2_PORT", "8443"))
DATABASE_PATH = Path(os.getenv("C2_DB_PATH", "c2_framework.db"))

# AES-256-GCM pre-shared key (32 bytes hex)
# In production: derive from password or HSM. Here: env var with fallback for dev.
# WARNING: fallback key is PUBLIC — override with C2_PSK env var for real ops.
PSK_HEX = os.getenv("C2_PSK", "deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe")
PSK = bytes.fromhex(PSK_HEX)

# Default beacon timing (seconds)
DEFAULT_SLEEP = 5
DEFAULT_JITTER = 0.15  # ±15%

# Server keypair for beacon public key storage
# Ed25519 for future signature verification (Phase 2)
SERVER_ID = "c2-server-v1"
