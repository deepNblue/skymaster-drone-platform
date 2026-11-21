#!/usr/bin/env bash
# scripts/e2e_smoke.sh — end-to-end smoke test for SkyMaster v0.1.
#
# Prereqs (via docker compose or local run):
#   - API listening on ${API_BASE:-http://localhost:8000}
#   - Postgres reachable via the app's DATABASE_URL
#   - Python env with app deps (for scripts/db_seed.py)
#
# Usage:
#   ./scripts/e2e_smoke.sh
#
# Env overrides:
#   API_BASE   Base URL of the API (default: http://localhost:8000)
#   SEED_EMAIL Login email        (default: admin@test.local)
#   SEED_PASS  Login password     (default: admin123)

set -u  # do NOT set -e — we track failures explicitly to always print a summary.

API_BASE="${API_BASE:-http://localhost:8000}"
SEED_EMAIL="${SEED_EMAIL:-admin@test.local}"
SEED_PASS="${SEED_PASS:-admin123}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
FAILURES=()

log()  { printf "\033[36m[e2e]\033[0m %s\n" "$*"; }
ok()   { PASS=$((PASS+1)); printf "  \033[32m✓\033[0m %s\n" "$*"; }
fail() { FAIL=$((FAIL+1)); FAILURES+=("$*"); printf "  \033[31m✗\033[0m %s\n" "$*"; }

require() {
    command -v "$1" >/dev/null 2>&1 || { echo "missing dependency: $1"; exit 2; }
}
require curl
require python3

# ---------------------------------------------------------------------------
# 1. Wait for API health (up to 30s).
# ---------------------------------------------------------------------------
log "waiting for API health at $API_BASE/api/v1/health ..."
health_ok=0
for i in $(seq 1 30); do
    if curl -fsS -o /dev/null "$API_BASE/api/v1/health"; then
        health_ok=1
        break
    fi
    sleep 1
done
if [ "$health_ok" -eq 1 ]; then
    ok "API healthy"
else
    fail "API did not become healthy within 30s"
    printf "\n\033[31m❌ FAIL\033[0m — aborting: API unreachable\n"
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Seed org + admin user (idempotent).
# ---------------------------------------------------------------------------
log "seeding org + admin user via scripts/db_seed.py ..."
if (cd "$REPO_ROOT" && python3 -m scripts.db_seed); then
    ok "db seed complete"
else
    fail "db seed failed"
fi

# ---------------------------------------------------------------------------
# 3. Login → capture token.
# ---------------------------------------------------------------------------
log "logging in as $SEED_EMAIL ..."
login_body=$(printf '{"email":"%s","password":"%s"}' "$SEED_EMAIL" "$SEED_PASS")
login_resp=$(curl -sS -X POST "$API_BASE/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "$login_body")

TOKEN=$(printf '%s' "$login_resp" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); print(d.get("access_token",""))')

if [ -n "$TOKEN" ]; then
    ok "login → token received"
else
    fail "login failed — response: $login_resp"
    printf "\n\033[31m❌ FAIL\033[0m — aborting: no token\n"
    exit 1
fi

AUTH_H="Authorization: Bearer $TOKEN"

# ---------------------------------------------------------------------------
# 4. POST /drones — sn SITL-01, protocol mavlink.
# ---------------------------------------------------------------------------
log "creating drone SITL-01 ..."
drone_body='{"sn":"SITL-01","model":"SITL","protocol":"mavlink","metadata":{"mavlink_endpoint":"udpin:0.0.0.0:14550"}}'
drone_resp=$(curl -sS -X POST "$API_BASE/api/v1/drones" \
    -H "$AUTH_H" -H "Content-Type: application/json" \
    -d "$drone_body")
DRONE_ID=$(printf '%s' "$drone_resp" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); print(d.get("id",""))')
if [ -n "$DRONE_ID" ]; then
    ok "drone created / retrieved: id=$DRONE_ID"
else
    fail "drone create failed — response: $drone_resp"
fi

# ---------------------------------------------------------------------------
# 5. POST /missions with 3 waypoints (around PX4 default home in Beijing).
# ---------------------------------------------------------------------------
log "creating mission with 3 waypoints ..."
mission_body=$(cat <<JSON
{
  "name": "SITL smoke mission",
  "drone_id": "$DRONE_ID",
  "template": "waypoint",
  "waypoints": [
    {"lat": 39.9042, "lng": 116.4074, "alt": 60, "speed": 5},
    {"lat": 39.9052, "lng": 116.4084, "alt": 60, "speed": 5},
    {"lat": 39.9042, "lng": 116.4074, "alt": 60, "speed": 5}
  ]
}
JSON
)
mission_resp=$(curl -sS -X POST "$API_BASE/api/v1/missions" \
    -H "$AUTH_H" -H "Content-Type: application/json" \
    -d "$mission_body")
MISSION_ID=$(printf '%s' "$mission_resp" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); print(d.get("id",""))')
if [ -n "$MISSION_ID" ]; then
    ok "mission created: id=$MISSION_ID"
else
    fail "mission create failed — response: $mission_resp"
fi

# ---------------------------------------------------------------------------
# 6. POST /missions/{id}/validate → assert ok=true.
# ---------------------------------------------------------------------------
if [ -n "$MISSION_ID" ]; then
    log "validating mission $MISSION_ID ..."
    validate_resp=$(curl -sS -X POST "$API_BASE/api/v1/missions/$MISSION_ID/validate" \
        -H "$AUTH_H")
    validate_ok=$(printf '%s' "$validate_resp" | python3 -c \
        'import json,sys; d=json.load(sys.stdin); print("true" if d.get("ok") else "false")')
    if [ "$validate_ok" = "true" ]; then
        ok "mission validation ok=true"
    else
        fail "mission validation not ok — response: $validate_resp"
    fi
fi

# ---------------------------------------------------------------------------
# 7. GET /drones — assert non-empty.
# ---------------------------------------------------------------------------
log "listing drones ..."
drones_list=$(curl -sS "$API_BASE/api/v1/drones" -H "$AUTH_H")
drones_total=$(printf '%s' "$drones_list" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); print(d.get("total",0))')
if [ "${drones_total:-0}" -gt 0 ] 2>/dev/null; then
    ok "GET /drones non-empty (total=$drones_total)"
else
    fail "GET /drones empty or malformed — response: $drones_list"
fi

# ---------------------------------------------------------------------------
# 8. GET /missions — assert non-empty.
# ---------------------------------------------------------------------------
log "listing missions ..."
missions_list=$(curl -sS "$API_BASE/api/v1/missions" -H "$AUTH_H")
missions_total=$(printf '%s' "$missions_list" | python3 -c \
    'import json,sys; d=json.load(sys.stdin); print(d.get("total",0))')
if [ "${missions_total:-0}" -gt 0 ] 2>/dev/null; then
    ok "GET /missions non-empty (total=$missions_total)"
else
    fail "GET /missions empty or malformed — response: $missions_list"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "──────────────────────────────────────────────"
echo "  passed: $PASS   failed: $FAIL"
if [ "$FAIL" -eq 0 ]; then
    printf "  \033[32m✅ PASS\033[0m — all e2e smoke checks green.\n"
    echo "──────────────────────────────────────────────"
    exit 0
else
    printf "  \033[31m❌ FAIL\033[0m — %d check(s) failed:\n" "$FAIL"
    for f in "${FAILURES[@]}"; do
        printf "     - %s\n" "$f"
    done
    echo "──────────────────────────────────────────────"
    exit 1
fi
