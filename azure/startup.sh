#!/usr/bin/env bash
# Azure App Service startup command.
# Set in: App Service → Configuration → General Settings → Startup Command:
#   bash azure/startup.sh
#
# Azure provides $PORT; default to 8000 for local runs.
set -euo pipefail

APP_ROOT="${APP_ROOT:-/home/site/wwwroot}"
cd "$APP_ROOT"

python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

cd backend
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"

