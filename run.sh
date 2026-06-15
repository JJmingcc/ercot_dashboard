#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# One-click setup + launch for the ERCOT Weather-Driven Fundamentals Monitor.
#
#   ./run.sh                 # set up (once) and start the Streamlit dashboard
#   PORT=8600 ./run.sh       # use a different port (default 8501)
#
# Idempotent: creates the dash_env virtualenv only if missing, installs/updates
# the app dependencies, bootstraps .env from .env.example on first run, then
# launches the dashboard. Safe to re-run.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

ENV_DIR="dash_env"
PORT="${PORT:-8501}"

# 1. Pick a Python interpreter — prefer 3.13 (what the project was built/tested on).
if command -v python3.13 >/dev/null 2>&1; then
  PYBOOT="python3.13"
elif command -v python3 >/dev/null 2>&1; then
  PYBOOT="python3"
else
  echo "❌ Python 3 not found. Install Python 3.11+ and re-run." >&2
  exit 1
fi

# 2. Virtualenv — create once, reuse after.
if [ ! -x "$ENV_DIR/bin/python" ]; then
  echo "▸ Creating $ENV_DIR with $("$PYBOOT" --version)…"
  "$PYBOOT" -m venv "$ENV_DIR"
fi
PY="$ENV_DIR/bin/python"

# 3. Dependencies (app set = base + streamlit/plotly/shapely). pip skips satisfied ones.
echo "▸ Installing/updating app dependencies…"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r requirements-app.txt

# 4. Secrets — bootstrap .env from the template on first run (never overwrite a real one).
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠ Created .env from .env.example — open it and add your real credentials."
  echo "  Meteologica is required (net-load / demand); StormVista & EIA are optional."
  echo "  Streamlit auto-reloads when you save .env, so you can fill it after it starts."
fi

# 5. Launch the dashboard (Ctrl-C to stop).
echo "▸ Starting the dashboard → http://localhost:${PORT}"
exec "$ENV_DIR/bin/streamlit" run app/app.py --server.port "$PORT"
