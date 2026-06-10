#!/usr/bin/env bash
set -e

# ──────────────────────────────────────────────────
#  C2 Framework — Demo Script
#  Shows the full beacon cycle via the REST API.
# ──────────────────────────────────────────────────

BASE="${1:-http://127.0.0.1:8443}"
PASS=0
FAIL=0

green() { printf "  \033[32m✓ %s\033[0m\n" "$1"; ((PASS = PASS + 1)); }
red()   { printf "  \033[31m✗ %s\033[0m\n" "$1"; ((FAIL = FAIL + 1)); }
bold()  { printf "\n  \033[1m%s\033[0m\n" "$1"; }

# ── 1. Health check ──────────────────────────────────────────────────
bold "1. Health check"
HEALTH=$(curl -s "$BASE/")
if echo "$HEALTH" | grep -q '"status":"running"'; then
    green "Server is running — $HEALTH"
else
    red "Health check failed — got: $HEALTH"
fi

# ── 2. Wait for implant ──────────────────────────────────────────────
bold "2. Waiting for implant to register..."
for i in $(seq 1 12); do
    BEACONS=$(curl -s "$BASE/api/v1/beacons")
    COUNT=$(echo "$BEACONS" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('beacons',[])))" 2>/dev/null || echo 0)
    if [ "$COUNT" -gt 0 ]; then
        BID=$(echo "$BEACONS" | python3 -c "import sys,json; print(json.load(sys.stdin)['beacons'][0]['id'])" 2>/dev/null || echo "")
        if [ -n "$BID" ]; then
            green "Beacon registered: $BID"
            break
        fi
    fi
    sleep 2
done

if [ -z "$BID" ]; then
    red "No beacon registered after 24s"
    echo "  Raw beacons response: $BEACONS"
fi

# ── 3. Beacon details ────────────────────────────────────────────────
bold "3. Beacon details"
if [ -n "$BID" ]; then
    DETAILS=$(curl -s "$BASE/api/v1/beacons/$BID")
    echo "  $DETAILS" | python3 -m json.tool 2>/dev/null | sed 's/^/  /'
    green "Beacon detail retrieved"
fi

# ── 4. Issue a command ───────────────────────────────────────────────
bold "4. Issuing command: whoami"
if [ -n "$BID" ]; then
    TASK=$(curl -s -X POST "$BASE/api/v1/beacons/$BID/tasks" \
        -H "Content-Type: application/json" \
        -d '{"command":"whoami","args":[],"timeout":30}')
    TID=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('task',{}).get('id',''))" 2>/dev/null || echo "")
    if [ -n "$TID" ]; then
        green "Task created: $TID"
    else
        red "Task creation failed — $TASK"
    fi
fi

# ── 5. Wait for result ───────────────────────────────────────────────
bold "5. Polling for result..."
if [ -n "$BID" ] && [ -n "$TID" ]; then
    for i in $(seq 1 6); do
        TASKS=$(curl -s "$BASE/api/v1/beacons/$BID/tasks")
        STATUS=$(echo "$TASKS" | python3 -c "
import sys, json
tasks = json.load(sys.stdin).get('tasks', [])
for t in tasks:
    if t['id'] == '$TID':
        print(t.get('status', 'unknown'))
        sys.exit(0)
print('not_found')
" 2>/dev/null)
        if [ "$STATUS" = "complete" ]; then
            OUTPUT=$(echo "$TASKS" | python3 -c "
import sys, json
tasks = json.load(sys.stdin).get('tasks', [])
for t in tasks:
    if t['id'] == '$TID':
        print(t.get('output', ''))
" 2>/dev/null)
            bold "RESULT — $OUTPUT"
            green "Task completed successfully"
            break
        elif [ "$STATUS" = "failed" ]; then
            ERR=$(echo "$TASKS" | python3 -c "
import sys, json
tasks = json.load(sys.stdin).get('tasks', [])
for t in tasks:
    if t['id'] == '$TID':
        print(t.get('error', 'unknown error'))
" 2>/dev/null)
            red "Task failed: $ERR"
            break
        fi
        sleep 2
    done

    if [ "$STATUS" != "complete" ] && [ "$STATUS" != "failed" ]; then
        red "Timed out waiting for result (status: $STATUS)"
        echo "  Raw tasks: $(curl -s "$BASE/api/v1/beacons/$BID/tasks" | python3 -m json.tool 2>/dev/null | head -20)"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────
bold "─── Summary ───"
echo "  Passed: $PASS  Failed: $FAIL"
if [ "$FAIL" -eq 0 ]; then
    green "All checks passed!"
else
    red "$FAIL check(s) failed"
    exit 1
fi
