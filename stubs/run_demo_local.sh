#!/bin/bash
# Run demo mode locally without Docker
# Usage: bash stubs/run_demo_local.sh

set -e
cd "$(dirname "$0")/.."

# Activate venv
source homescreen_hero/.venv/Scripts/activate

# Export demo env vars
export HOMESCREEN_HERO_CONFIG=stubs/config.demo.yaml
export HSH_PLEX_URL=http://localhost:32400
export HSH_PLEX_TOKEN=demo-token
export HSH_AUTH_PASSWORD=demo
export HSH_AUTH_SECRET_KEY=demo-secret-key-not-for-production
export HSH_TRAKT_CLIENT_ID=demo-trakt-id
export HSH_MDBLIST_API_KEY=demo-mdblist-key
export HSH_TMDB_API_KEY=demo-tmdb-key
export HSH_TAUTULLI_API_KEY=demo-tautulli-key
export HSH_TAUTULLI_BASE_URL=http://localhost:9000/tautulli
export HSH_SEERR_API_KEY=demo-seerr-key
export HSH_SEERR_BASE_URL=http://localhost:9000/seerr
export HSH_MAL_CLIENT_ID=demo-mal-id
export VITE_DEMO_MODE=true

cleanup() {
    echo "Shutting down..."
    kill $PLEX_PID $API_PID $APP_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM

# Start stubs
echo "Starting Plex stub on :32400..."
uvicorn stubs.plex_stub.app:app --port 32400 --log-level warning &
PLEX_PID=$!

echo "Starting API stubs on :9000..."
uvicorn stubs.api_stubs.app:app --port 9000 --log-level warning &
API_PID=$!

sleep 2

# Start main app with reload
echo "Starting main app on :8000 (with --reload)..."
uvicorn homescreen_hero.web.app:app --port 8000 --reload &
APP_PID=$!

echo ""
echo "Demo running!"
echo "  Backend:  http://localhost:8000"
echo "  Login:    admin / demo"
echo ""
echo "Now start the frontend in another terminal:"
echo "  cd homescreen-hero-ui && VITE_DEMO_MODE=true npm run dev"
echo ""
echo "Press Ctrl+C to stop all processes"

wait
