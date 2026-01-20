#!/bin/sh
# Startup script for Render demo deployment

# Use Render's PORT if set, otherwise default to 8000
PORT=${PORT:-8000}

# Initialize/reset demo database
echo "Initializing demo database..."
python3 /app/reset_demo.py || echo "Warning: Database init had issues, continuing..."

echo "Starting uvicorn on port $PORT"

# Start uvicorn (single worker for APScheduler)
exec uvicorn homescreen_hero.web.app:app --host 0.0.0.0 --port "$PORT" --workers 1
