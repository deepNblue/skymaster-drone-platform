# scripts/

Dev-only utilities for SkyMaster v0.1: DB seeding, SITL smoke testing.

---

## 1. PX4 SITL (Software-In-The-Loop)

`docker-compose.sitl.yml` is an **overlay** that adds a headless PX4 + Gazebo
simulator publishing MAVLink on UDP 14550. Combine it with the base compose
file:

```bash
# Bring up the full stack + SITL
docker compose -f docker-compose.yml -f docker-compose.sitl.yml up -d

# Tear it down
docker compose -f docker-compose.yml -f docker-compose.sitl.yml down
```

The SITL container spawns a drone at PX4 default home (Beijing —
39.9042, 116.4074, 50 m). The base stack's `mavlink-connector` service uses
`network_mode: host`, so it will find the simulated vehicle at
`udpin:0.0.0.0:14550` without extra wiring.

If you want an alternative image, swap `jonasvautherin/px4-gazebo-headless`
for `px4io/px4-dev-simulation-focal` in `docker-compose.sitl.yml`.

### Verifying SITL is up

```bash
# You should see MAVLink packets arriving:
docker compose logs -f mavlink-connector

# Or peek at raw UDP (Linux):
nc -ul 14550
```

---

## 2. DB seed — `scripts/db_seed.py`

Creates a `TestOrg` org and an `admin@test.local` / `admin123` admin user.
Idempotent: safe to run repeatedly.

```bash
# From the repo root (backend-v0.1/):
python -m scripts.db_seed
# → [db_seed] result: {'org_id': '...', 'user_id': '...', ...}
```

Uses whatever `DATABASE_URL` the app is configured with (see `app/db.py`),
so it works the same inside and outside the compose network.

Credentials are for **local/CI only** — never deploy this user.

---

## 3. E2E smoke — `scripts/e2e_smoke.sh`

Exercises the happy path end-to-end against a running API:

1. Waits (up to 30s) for `/api/v1/health` to return 200.
2. Runs the DB seed so login credentials exist.
3. Logs in → captures JWT.
4. `POST /drones` for `SITL-01` (mavlink protocol).
5. `POST /missions` with 3 waypoints.
6. `POST /missions/{id}/validate` — asserts `ok=true`.
7. `GET /drones` and `GET /missions` — asserts non-empty.
8. Prints `✅ PASS` / `❌ FAIL` summary.

```bash
# Local run:
./scripts/e2e_smoke.sh

# Against a specific API base:
API_BASE=http://api.local:8000 ./scripts/e2e_smoke.sh
```

Exit code: `0` on green, `1` on any failed assertion.

---

## 4. Pytest equivalent — `tests/test_e2e_smoke.py`

Same flow as `e2e_smoke.sh`, wrapped in an async pytest test. Skipped by
default; opt in with `RUN_INTEGRATION=1`:

```bash
RUN_INTEGRATION=1 pytest -q tests/test_e2e_smoke.py -m integration
```

Marked with `@pytest.mark.integration` so it stays out of the unit-test
run. Register the marker in `pyproject.toml` (or `pytest.ini`) if pytest
warns about it:

```toml
[tool.pytest.ini_options]
markers = ["integration: end-to-end tests hitting a live stack"]
```

---

## Typical dev loop

```bash
# 1. Bring up stack + SITL
docker compose -f docker-compose.yml -f docker-compose.sitl.yml up -d

# 2. Apply migrations (first run only)
docker compose exec api alembic upgrade head

# 3. Smoke test
./scripts/e2e_smoke.sh
```
