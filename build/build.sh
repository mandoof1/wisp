#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "[*] Building implant for current platform..."
cd "$PROJECT_DIR/implant"

GOOS="${GOOS:-$(go env GOOS)}"
GOARCH="${GOARCH:-$(go env GOARCH)}"

echo "[*] GOOS=$GOOS GOARCH=$GOARCH"

CGO_ENABLED=0 go build \
    -trimpath \
    -ldflags="-s -w" \
    -o "$PROJECT_DIR/build/implant-${GOOS}-${GOARCH}" .

echo "[+] Built: build/implant-${GOOS}-${GOARCH}"

# Cross-compile helpers (uncomment as needed)
if [ "${1:-}" = "all" ]; then
    echo "[*] Cross-compiling..."
    for target in "linux/amd64" "linux/arm64" "windows/amd64" "darwin/amd64" "darwin/arm64"; do
        GOOS="${target%/*}"
        GOARCH="${target#*/}"
        ext=""
        [ "$GOOS" = "windows" ] && ext=".exe"
        CGO_ENABLED=0 GOOS="$GOOS" GOARCH="$GOARCH" go build \
            -trimpath \
            -ldflags="-s -w" \
            -o "$PROJECT_DIR/build/implant-${GOOS}-${GOARCH}${ext}" .
        echo "[+] Built: build/implant-${GOOS}-${GOARCH}${ext}"
    done
fi
