# Wisp — Design Document

## Overview
A lightweight command-and-control framework for red team operations. Implant polls a REST server for tasks, executes them, and exfiltrates results. Everything is encrypted at rest and in transit.

## Architecture

```
┌─────────────────┐         HTTPS/JSON         ┌──────────────────┐         ┌──────────────────┐
│   Go Implant    │ ◄─────────────────────────► │  Python Server   │ ◄─────► │   CLI Client     │
│  (target host)  │      X25519/AES-GCM        │  (FastAPI + SQL) │         │  (operator box)   │
└─────────────────┘                            └──────────────────┘         └──────────────────┘
```

## Components

### 1. Server (Python/FastAPI)
- REST API for registration, tasking, and results
- SQLite database for persistent storage
- Architecture endpoints: register, poll, complete, operator CRUD
- Crypto: X25519 session keys with AES-256-GCM envelope, PSK fallback

### 2. Implant (Go)
- Cross-compiled binary (Linux x86_64, ARM64, Windows amd64)
- Randomized sleep with jitter
- Encrypted beacon → poll → execute → exfil loop
- Persistence hooks (MVP: crontab + systemd user service)

### 3. CLI Client (Python)
- Interactive shell for issuing commands to beacons
- Task queue (send a command, implant picks it up on next poll)
- View live results, beacon metadata, session history
- Tab-completion for beacons and commands

## Communication Flow

```
Beacon                     Server                       Client
  │                          │                            │
  │  POST /register          │                            │
  │  ──────────────────────► │                            │
  │  ←── {beacon_id, key}    │                            │
  │                          │                            │
  │  POST /poll              │                            │  POST /task
  │  ──────────────────────► │  ◄────────────────────────── │
  │  ←── {tasks: [...]}      │                            │
  │                          │                            │
  │  POST /result            │                            │
  │  ──────────────────────► │                            │
  │                          │  GET /results/:beacon_id   │
  │                          │  ────────────────────────► │
  │                          │  ◄── {results: [...]}     │
```

## Encryption

| Property | Detail |
|----------|--------|
| **Algorithm** | AES-256-GCM (authenticated encryption) |
| **Key exchange** | X25519 ECDH per session (forward secrecy) |
| **Key derivation** | `SHA-256(shared_secret \|\| "c2-framework-v1")` |
| **Fallback** | Static 32-byte PSK via `C2_PSK` env var |
| **Payload format** | `nonce_hex:ciphertext_b64` in JSON envelope |
| **Key transport** | `X-Key-ID` header (implant public key hex) |
| **Nonce** | Random 12 bytes per message |

The implant performs a one-time X25519 handshake on startup. If the server doesn't support it (404), it falls back to the pre-shared key — backwards compatible by design.

## Project Structure

```
c2-framework/
├── DESIGN.md                 # This file
├── LICENSE                   # MIT
├── README.md                 # Quick start + usage
├── .gitignore
├── server/
│   ├── requirements.txt      # Python deps
│   ├── main.py               # FastAPI entrypoint
│   ├── config.py             # Server config + crypto
│   ├── database.py           # SQLAlchemy models + ops
│   ├── crypto.py             # X25519 + AES-GCM
│   └── routes.py             # API route handlers
├── implant/
│   ├── go.mod                # Go module
│   ├── main.go               # Entry + main loop
│   ├── config.go             # Implant config + crypto
│   ├── beacon.go             # HTTP client + protocol
│   └── crypto.go             # X25519 + AES-GCM + key derivation
├── client/
│   ├── c2cli.py              # Interactive CLI controller
│   └── requirements.txt      # Python deps
└── build/
    ├── build.sh              # Cross-compile script
    └── implant               # Compiled binary (gitignored)
```
