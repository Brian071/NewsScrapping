#!/bin/bash
set -e

# Function to cleanup background processes on exit
cleanup() {
    echo "Stopping background processes..."
    kill $(jobs -p) 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT

echo "Starting Backend (Uvicorn)..."
# Use nohup or just background, but we want it to die when this script dies (handled by trap)
uvicorn api:app --host 0.0.0.0 --port 8000 --loop asyncio > api.log 2>&1 &
BACKEND_PID=$!

echo "Waiting for Backend to respond at http://localhost:8000..."
# Wait up to 60 seconds
for i in {1..60}; do
    if curl -s http://localhost:8000/health > /dev/null; then
        echo "✅ Backend is UP!"
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

if ! curl -s http://localhost:8000/health > /dev/null; then
    echo "❌ Backend failed to start. Check api.log:"
    cat api.log
    exit 1
fi

echo "Starting Frontend (Streamlit)..."
streamlit run frontend.py --server.headless true
