#!/bin/bash

echo "Starting GitHub Stars Dashboard..."

# Wait for database to be ready
echo "Waiting for database to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if python -c "import sqlite3; conn = sqlite3.connect('/app/data/github_stars.db'); conn.close(); exit(0)" 2>/dev/null; then
        echo "Database is ready!"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Database not ready, retrying... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "ERROR: Database failed to initialize after $MAX_RETRIES retries"
    exit 1
fi

# Start the application
echo "Starting uvicorn..."
exec uvicorn github_stars.api:app --host 0.0.0.0 --port 8000
