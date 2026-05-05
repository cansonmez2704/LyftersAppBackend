#!/usr/bin/env bash
#
# Bootstrap + run a load test against an isolated Postgres database.
#
#   ./loadtest/run_loadtest.sh             # full bootstrap (create db, migrate, seed, serve)
#   ./loadtest/run_loadtest.sh --no-seed   # skip the seed step (re-running)
#   ./loadtest/run_loadtest.sh --reset     # DROP and re-create the test DB first
#
# Tune the gunicorn config without editing the script:
#   GUNICORN_WORKERS=8 ./loadtest/run_loadtest.sh                                     # more sync workers
#   GUNICORN_WORKER_CLASS=gevent ./loadtest/run_loadtest.sh                           # async (IO-bound) workers
#   GUNICORN_WORKER_CLASS=gevent GUNICORN_WORKER_CONNECTIONS=2000 ./loadtest/run_loadtest.sh
#
# Front Postgres with pgbouncer (transaction pooling) to clear the
# max_connections=100 ceiling at 500u:
#   USE_PGBOUNCER=True GUNICORN_WORKER_CLASS=gevent ./loadtest/run_loadtest.sh
#
# Compare runs by saving Locust's "Download Data > Report" between configs.
#
# Then in a second terminal:
#   cd GymHubBackend/loadtest
#   source ../venv/bin/activate
#   locust -f locustfile.py --host http://127.0.0.1:8000
# and open http://127.0.0.1:8089.
#
# Stops gunicorn + celery on Ctrl-C.

set -euo pipefail

cd "$(dirname "$0")/.."   # cd to GymHubBackend/

# ---- config ----
export DJANGO_DB_NAME="${DJANGO_DB_NAME:-gymhub_loadtest}"
export LOAD_TEST_MODE="${LOAD_TEST_MODE:-1}"
export DJANGO_SETTINGS_MODULE=core.settings
WORKERS="${GUNICORN_WORKERS:-4}"                       # M1 Air: 4 sync, 8 if pushing it
WORKER_CLASS="${GUNICORN_WORKER_CLASS:-sync}"          # sync | gevent
WORKER_CONNECTIONS="${GUNICORN_WORKER_CONNECTIONS:-1000}"  # gevent only — concurrent greenlets per worker
PORT="${PORT:-8000}"
PG_USER="${PG_USER:-postgres}"
USE_PGBOUNCER="${USE_PGBOUNCER:-False}"

# gevent monkey-patches the stdlib at import; gunicorn handles the patching when
# you select the worker class, but the worker process still needs the package available.
if [[ "$WORKER_CLASS" == "gevent" ]]; then
    if ! python -c "import gevent" 2>/dev/null; then
        echo "ERROR: --worker-class gevent requested but gevent isn't installed in venv." >&2
        exit 1
    fi
fi

if [[ "$USE_PGBOUNCER" == "True" ]]; then
    if ! command -v pgbouncer >/dev/null 2>&1; then
        echo "ERROR: USE_PGBOUNCER=True but pgbouncer is not on PATH. Install it first: brew install pgbouncer" >&2
        exit 1
    fi
    if lsof -ti:6432 >/dev/null 2>&1; then
        echo "ERROR: Port 6432 already in use by:" >&2
        lsof -i:6432 >&2
        echo "" >&2
        echo "Kill it first:  lsof -ti:6432 | xargs kill -9" >&2
        exit 1
    fi
fi

DO_SEED=1
DO_RESET=0
for arg in "$@"; do
    case "$arg" in
        --no-seed) DO_SEED=0 ;;
        --reset) DO_RESET=1 ;;
    esac
done

# ---- preconditions ----
if [[ ! -d venv ]]; then
    echo "ERROR: venv/ not found in $(pwd). Create it first: python -m venv venv && pip install -r requirements.txt" >&2
    exit 1
fi
# shellcheck source=/dev/null
source venv/bin/activate

if ! pg_isready -h localhost -p 5432 -q; then
    echo "ERROR: Postgres is not reachable on localhost:5432" >&2
    exit 1
fi
if ! redis-cli ping >/dev/null 2>&1; then
    echo "ERROR: Redis is not reachable (redis-cli ping failed)" >&2
    exit 1
fi
# If something else is already on the port, gunicorn would silently fail to bind
# and the script would hand traffic to whatever zombie is squatting there.
if lsof -ti:"$PORT" >/dev/null 2>&1; then
    echo "ERROR: Port $PORT is already in use by:" >&2
    lsof -i:"$PORT" >&2
    echo "" >&2
    echo "Kill it first:  lsof -ti:$PORT | xargs kill -9" >&2
    exit 1
fi

# ---- database ----
if [[ "$DO_RESET" == "1" ]]; then
    echo "Dropping and recreating $DJANGO_DB_NAME..."
    psql -h localhost -U "$PG_USER" -d postgres -c "DROP DATABASE IF EXISTS $DJANGO_DB_NAME;" >/dev/null
fi
psql -h localhost -U "$PG_USER" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='$DJANGO_DB_NAME'" \
    | grep -q 1 || psql -h localhost -U "$PG_USER" -d postgres -c "CREATE DATABASE $DJANGO_DB_NAME;"

# pg_trgm is required by workouts.0007_add_trigram_indexes.
psql -h localhost -U "$PG_USER" -d "$DJANGO_DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" >/dev/null

echo "Running migrations against $DJANGO_DB_NAME..."
python manage.py migrate --noinput

if [[ "$DO_SEED" == "1" ]]; then
    echo "Seeding load test fixtures..."
    python manage.py seed_loadtest
fi

# ---- processes ----
mkdir -p loadtest/logs
PIDS=()

cleanup() {
    echo
    echo "Stopping background processes..."
    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ "$USE_PGBOUNCER" == "True" ]]; then
    echo "Generating loadtest/pgbouncer/userlist.txt from .env..."
    python - >loadtest/pgbouncer/userlist.txt <<'PY'
import os, hashlib
from dotenv import load_dotenv
load_dotenv(".env")
pwd = os.environ["DB_PASSWORD"]
user = "postgres"
print(f'"{user}" "md5{hashlib.md5((pwd + user).encode()).hexdigest()}"')
PY
    chmod 600 loadtest/pgbouncer/userlist.txt

    echo "Starting pgbouncer on :6432 (logs: loadtest/logs/pgbouncer.log)..."
    pgbouncer loadtest/pgbouncer/pgbouncer.ini &
    PIDS+=($!)

    for _ in {1..20}; do
        if pg_isready -h 127.0.0.1 -p 6432 -q 2>/dev/null; then
            break
        fi
        sleep 0.2
    done
    if ! pg_isready -h 127.0.0.1 -p 6432 -q 2>/dev/null; then
        echo "ERROR: pgbouncer failed to come up on :6432. See loadtest/logs/pgbouncer.log" >&2
        exit 1
    fi

    # App processes (gunicorn, celery) talk to pgbouncer; migrations + seed already
    # ran direct to :5432 above, which is what we want — admin work goes direct.
    export DB_PORT=6432
    export USE_PGBOUNCER=True
fi

echo "Starting celery worker (logs: loadtest/logs/celery.log)..."
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-2}"
celery -A core worker -l warning -Q default,media,maintenance,moderation --concurrency="$CELERY_CONCURRENCY" \
    >loadtest/logs/celery.log 2>&1 &
PIDS+=($!)

GUNICORN_ARGS=(
    core.wsgi:application
    --workers "$WORKERS"
    --worker-class "$WORKER_CLASS"
    --bind "0.0.0.0:$PORT"
    --access-logfile loadtest/logs/gunicorn-access.log
    --access-logformat '%(t)s %(s)s %(L)s "%(r)s"'
    --error-logfile loadtest/logs/gunicorn.log
    --log-level warning
)
if [[ "$WORKER_CLASS" == "gevent" ]]; then
    GUNICORN_ARGS+=(--worker-connections "$WORKER_CONNECTIONS")
fi

echo "Starting gunicorn ($WORKERS x $WORKER_CLASS workers) on :$PORT (logs: loadtest/logs/gunicorn.log)..."
gunicorn "${GUNICORN_ARGS[@]}" >>loadtest/logs/gunicorn.log 2>&1 &
PIDS+=($!)

# Wait for gunicorn to bind.
for _ in {1..20}; do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/v1/" 2>/dev/null \
        || curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/v1/" 2>/dev/null | grep -qE "^(200|301|302|401|404)$"; then
        break
    fi
    sleep 0.5
done

cat <<EOF

===================================================================
Server is up.
  DB:       $DJANGO_DB_NAME$([ "$USE_PGBOUNCER" = "True" ] && echo " via pgbouncer :6432 → :5432 (transaction pool)")
  Workers:  $WORKERS x $WORKER_CLASS$([ "$WORKER_CLASS" = "gevent" ] && echo " (conns/worker: $WORKER_CONNECTIONS)")
  Throttle: LOAD_TEST_MODE=$LOAD_TEST_MODE (rates bumped ~100x)
  URL:      http://127.0.0.1:$PORT

In another terminal, start Locust:
  cd $(pwd)/loadtest
  source ../venv/bin/activate
  locust -f locustfile.py --host http://127.0.0.1:$PORT

Then open http://127.0.0.1:8089. Suggested first run:
  Users: 200, Spawn rate: 1/s, Run time: 15m

Watch for the breaking point: p95 latency climbing past ~500ms,
failure rate > 1%, or gunicorn workers saturated (top -pid <pid>).

Ctrl-C here to stop the server.
===================================================================
EOF

wait
