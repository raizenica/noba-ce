#!/bin/bash
set -e
cd "$(dirname "$0")/../share/noba-web/frontend"
echo "[build] Installing dependencies..."
npm ci --silent
echo "[build] Building Vue frontend..."
npm run build
echo "[build] Done. Output in share/noba-web/static/dist/"
