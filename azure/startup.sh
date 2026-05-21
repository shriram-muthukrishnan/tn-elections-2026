#!/usr/bin/env bash
# Azure App Service startup command.
# Set in: App Service → Configuration → General Settings → Startup Command:
#   bash azure/startup.sh
#
# Dependencies are installed by Oryx at deploy time (SCM_DO_BUILD_DURING_DEPLOYMENT=true),
# which activates antenv before invoking this script. Do NOT pip install here — that
# would re-run on every cold start and trip App Service's 230s startup probe.
set -euo pipefail

cd "${APP_ROOT:-/home/site/wwwroot}/backend"
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"

