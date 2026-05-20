#!/usr/bin/env bash
# Set up the venv + deps from scratch. Idempotent.
# Usage: ./bootstrap.sh && source env/bin/activate

set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d env ]; then
  echo ">> creating venv in ./env"
  python3 -m venv env
fi

# shellcheck disable=SC1091
source env/bin/activate

echo ">> installing dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
# pydantic v1 on python >=3.12 needs this for EmailStr fields to import.
pip install --quiet email-validator

echo
echo ">> done. activate the venv with:"
echo "     source env/bin/activate"
echo ">> next steps:"
echo "     python verify_galaxy_creds.py   # confirm API creds"
echo "     python run_cal_update.py        # sync loop + digest"
echo "     python run_web.py               # web viewer (needs WEB_PASSWORD in .env)"
