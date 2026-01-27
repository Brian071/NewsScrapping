#!/bin/bash
set -e

# Cleanup function (standard practice)
cleanup() {
    echo "Stopping processes..."
    kill -- -$$ 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT

# Install Playwright dependencies (Essential for Crawl4AI)
echo "Installing Playwright Chromium..."
playwright install chromium

echo "Starting Frontend (Streamlit) in Direct Mode..."

# Run Streamlit. If this dies, the script exits.
streamlit run frontend.py --server.headless true
