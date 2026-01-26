#!/bin/bash
set -e

# Function to cleanup background processes on exit
cleanup() {
    echo "Stopping background processes..."
    kill -- -$$ 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT

# Install Playwright dependencies (Essential for Crawl4AI)
echo "Installing Playwright Chromium..."
playwright install chromium

# Watchdog function for Worker
run_worker() {
    while true; do
        echo "[Watchdog] Starting Background Worker..."
        python3 worker.py >> worker.log 2>&1
        EXIT_CODE=$?
        echo "[Watchdog] Worker crashed/exited with code $EXIT_CODE. Restarting in 3 seconds..."
        sleep 3
    done
}

# Start Worker Watchdog in background
run_worker &
WORKER_PID=$!

echo "Worker started in background (PID $WORKER_PID)."
echo "Starting Frontend (Streamlit)..."

# Run Streamlit. If this dies, the script exits.
streamlit run frontend.py --server.headless true
