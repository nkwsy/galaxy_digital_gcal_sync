#!/usr/bin/env bash
# Set up the venv + deps from scratch. Idempotent.
# Usage: ./bootstrap.sh && source env/bin/activate
#
# Override which interpreter to use:
#     PYTHON=python3.11 ./bootstrap.sh

set -euo pipefail
cd "$(dirname "$0")"

# --- Python version preflight --------------------------------------------
# The codebase uses PEP 604 (`X | None`) union annotations widely. Although
# every file that uses them has `from __future__ import annotations` to make
# them parse on 3.9, several upstream deps (fastapi, google-auth) have
# already dropped 3.9 and 3.10 is approaching EOL. Require 3.11+ here so a
# fresh deploy can't silently land on a too-old interpreter and then
# crashloop systemd at runtime.
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "ERR: $PYTHON not on PATH. Install Python 3.11+, or set PYTHON=<path>." >&2
  exit 1
fi
ver=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
major=${ver%.*}
minor=${ver#*.}
if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 11 ]; }; then
  cat >&2 <<MSG
ERR: Python $ver detected, need 3.11 or newer.

Debian 12 (bookworm):
    sudo apt install python3.11 python3.11-venv

Debian 11 (bullseye), via pyenv:
    sudo apt install -y build-essential libssl-dev zlib1g-dev libbz2-dev \\
        libreadline-dev libsqlite3-dev libffi-dev liblzma-dev curl git
    curl https://pyenv.run | bash
    # then add pyenv to ~/.bashrc per the installer message, exec bash,
    # pyenv install 3.11.9 && pyenv local 3.11.9
    # then re-run ./bootstrap.sh

Re-run with an explicit interpreter:
    PYTHON=/path/to/python3.11 ./bootstrap.sh
MSG
  exit 1
fi
echo ">> python $ver  (OK)"

# --- venv ----------------------------------------------------------------
if [ ! -d env ]; then
  echo ">> creating venv in ./env (using $PYTHON)"
  "$PYTHON" -m venv env
fi

# shellcheck disable=SC1091
source env/bin/activate

echo ">> installing dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
# pydantic v1 needs this for any EmailStr fields to import cleanly on
# modern Python; harmless to install even if unused.
pip install --quiet email-validator

echo
echo ">> done. activate the venv with:"
echo "     source env/bin/activate"
echo ">> next steps:"
echo "     python verify_galaxy_creds.py   # confirm API creds"
echo "     python run_cal_update.py        # sync loop + digest"
echo "     python run_web.py               # web viewer (needs WEB_PASSWORD in .env)"
