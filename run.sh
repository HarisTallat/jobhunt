#!/usr/bin/env bash
# Monolith — ek server (API + UI). Python 3.12 venv se chalao (jobspy + sab deps yahan hain).
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "venv nahi mila. Bana raha hoon (uv se)..."
  "$HOME/.local/bin/uv" venv --python 3.12 .venv
  "$HOME/.local/bin/uv" pip install --python .venv/bin/python -r requirements.txt
fi
.venv/bin/python app.py
