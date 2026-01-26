#!/bin/bash
set -e

# Function to cleanup background processes on exit
cleanup() {
    echo "Stopping background processes..."
    # Kill the process group to ensure all children (watchdog, uvicorn, streamlit) die
    kill -- -$$ 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT

# Watchdog function for Backend
run_backend() {
    while true; do
        echo "[Watchdog] Starting Backend (Uvicorn)..."
        # Run uvicorn. If it crashes, the loop continues.
        uvicorn api:app --host 0.0.0.0 --port 8000 --loop asyncio > api.log 2>&1
        EXIT_CODE=$?
        echo "[Watchdog] Backend crashed with exit code $EXIT_CODE. Restarting in 3 seconds..."
        sleep 3
    done
}

# Start Backend Watchdog in background
run_backend &
BACKEND_WATCHDOG_PID=$!

echo "Waiting for Backend to respond at http://localhost:8000..."
# Wait up to 60 seconds (increased from 30) for initial startup
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
    echo "❌ Backend failed to start initially. Check api.log:"
    tail -n 20 api.log
    # We don't exit here anymore because the watchdog might eventually succeed,
    # but we should warn. Streamlit will just fail to connect until it's up.
fi

echo "Starting Frontend (Streamlit)..."
# Run Streamlit. If this dies, the script exits (because of set -e? No, streamlit is the main process now)
streamlit run frontend.py --server.headless true
