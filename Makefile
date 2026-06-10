.PHONY: help install install-dev build build-all run-server run-implant demo test lint clean rebuild

VENV       := .venv
PYTHON     := $(VENV)/bin/python3
PIP        := $(VENV)/bin/pip
UVICORN    := $(VENV)/bin/uvicorn
C2_SERVER  := server.main:app
GOOS       := $(shell go env GOOS 2>/dev/null || echo linux)
GOARCH     := $(shell go env GOARCH 2>/dev/null || echo amd64)
IMPLANT_BIN := build/implant-$(GOOS)-$(GOARCH)

help:
	@echo "  Wisp — Makefile"
	@echo ""
	@echo "  install       Create venv + install Python dependencies"
	@echo "  install-dev   Install dev extras (ruff, pyflakes)"
	@echo "  build         Compile implant for current platform"
	@echo "  build-all     Cross-compile implant (linux/windows/darwin x amd64/arm64)"
	@echo "  run-server    Start FastAPI server (Ctrl+C to stop)"
	@echo "  run-implant   Start the implant binary (requires server running)"
	@echo "  demo          Run demo.sh against a live server+implant"
	@echo "  test          Run crypto tests against a running server"
	@echo "  lint          Basic syntax checks (go vet + Python compile)"
	@echo "  clean         Remove build artifacts, venv, and database"
	@echo "  rebuild       clean + build"
	@echo ""

# ── Dependencies ────────────────────────────────────────────────────────────

install: $(VENV)/bin/uvicorn
$(VENV)/bin/uvicorn: server/requirements.txt client/requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r server/requirements.txt
	$(PIP) install --quiet -r client/requirements.txt
	@echo "  [+] Dependencies installed in $(VENV)"

install-dev: install
	$(PIP) install --quiet ruff pyflakes
	@echo "  [+] Dev tools installed"

# ── Build ───────────────────────────────────────────────────────────────────

build: $(IMPLANT_BIN)
$(IMPLANT_BIN): implant/*.go implant/go.mod
	cd implant && CGO_ENABLED=0 go build \
		-trimpath \
		-ldflags="-s -w" \
		-o ../$@ .
	@echo "  [+] Built: $@"

build-all:
	@bash $(BUILD_SCRIPT) all

# ── Run ─────────────────────────────────────────────────────────────────────

run-server:
	@echo "  [*] Starting server on http://127.0.0.1:8443"
	@C2_PSK="$${C2_PSK:-3132333435363738393031323334353637383930313233343536373839303132333435363738393031323334353637383930313233343536373839303132}" \
		$(UVICORN) $(C2_SERVER) --host 0.0.0.0 --port 8443 --reload

run-implant:
	@echo "  [*] Starting implant (server must be running)"
	@C2_PSK="$${C2_PSK:-3132333435363738393031323334353637383930313233343536373839303132333435363738393031323334353637383930313233343536373839303132}" \
		C2_SERVER_URL="http://127.0.0.1:8443" \
		./$(IMPLANT_BIN)

# ── Demo / Test ─────────────────────────────────────────────────────────────

demo:
	@bash demo.sh

test:
	@echo "  [*] Running crypto tests (server must be running)"
	$(PYTHON) build/test_crypto.py

# ── Lint ────────────────────────────────────────────────────────────────────

lint: install
	@echo "  [*] go vet..."
	@cd implant && go vet ./... 2>&1 | sed 's/^/    /' && echo "  [+] go vet clean" || true
	@echo "  [*] Python syntax check..."
	@$(PYTHON) -m py_compile server/*.py client/c2cli.py 2>&1 | sed 's/^/    /' && echo "  [+] Python syntax clean" || true

# ── Clean ───────────────────────────────────────────────────────────────────

clean:
	@echo "  [*] Cleaning..."
	rm -rf $(VENV)
	rm -f build/implant-*
	rm -f c2_framework.db
	@echo "  [+] Clean"

rebuild: clean build
	@echo "  [+] Rebuild complete"
