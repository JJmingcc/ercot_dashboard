#!/usr/bin/env bash
# Create the project virtual environment and install dependencies.
# Run this on your machine (macOS) from the project root:  ./setup.sh
#
# The env is named dash_env (not the generic "venv") so it is unambiguous which
# environment the project uses. Always work inside it: `source dash_env/bin/activate`.
set -euo pipefail

cd "$(dirname "$0")"

ENV_DIR="dash_env"

# Prefer python3.13 (the version dash_env was built and tested with) so that
# everyone ends up on the SAME interpreter; fall back to python3 otherwise.
if command -v python3.13 >/dev/null 2>&1; then
  PYTHON_BIN="python3.13"
else
  PYTHON_BIN="python3"
fi
echo "Building $ENV_DIR with: $($PYTHON_BIN --version)"

"$PYTHON_BIN" -m venv "$ENV_DIR"
# shellcheck disable=SC1091
source "$ENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "Done. Python in dash_env: $(python --version)"
echo "Activate with:  source dash_env/bin/activate"
echo "Smoke-test credentials with:  python -m src.meteologica_client"
echo "Live login check with:        python -m src.meteologica_client --login"
