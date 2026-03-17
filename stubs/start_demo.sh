#!/bin/bash
set -e

echo "Starting HomeScreen Hero Demo..."

# Create data directories
mkdir -p /data/logs

# Copy demo config if not present
if [ ! -f /data/config.yaml ]; then
    cp /app/stubs/config.demo.yaml /data/config.yaml
    echo "Demo config created at /data/config.yaml"
fi

# Start plex-stub in background
echo "Starting Plex stub on port 32400..."
python -m uvicorn stubs.plex_stub.app:app --host 0.0.0.0 --port 32400 --log-level warning &
PLEX_PID=$!

# Start api-stubs in background
echo "Starting API stubs on port 9000..."
python -m uvicorn stubs.api_stubs.app:app --host 0.0.0.0 --port 9000 --log-level warning &
API_PID=$!

# Wait for stubs to be ready
echo "Waiting for stubs to start..."
sleep 3

# Verify stubs are running
if ! kill -0 $PLEX_PID 2>/dev/null; then
    echo "ERROR: Plex stub failed to start"
    exit 1
fi
if ! kill -0 $API_PID 2>/dev/null; then
    echo "ERROR: API stubs failed to start"
    exit 1
fi

echo "Seeding demo data..."
python -m stubs.seed_demo_db

echo "Stubs ready. Starting main app on port 8000..."

# Start main app (foreground - this is what Render monitors)
exec python -m uvicorn homescreen_hero.web.app:app --host 0.0.0.0 --port 8000 --workers 1
