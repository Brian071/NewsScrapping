import requests
import time
import subprocess
import sys
import os

def run_backend():
    print("Starting backend...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return proc

def test_crash():
    # Clear proxy env vars just in case
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)

    proc = run_backend()
    time.sleep(10) # Wait for startup

    try:
        if proc.poll() is not None:
             print("Backend DIED immediately.")
             return

        print("Checking health on 127.0.0.1...")
        r = requests.get("http://127.0.0.1:8000/health")
        print(f"Health: {r.status_code}")

        print("Backend is working on 127.0.0.1.")

    except Exception as e:
        print(f"Error: {e}")
        subprocess.run(["lsof", "-i", ":8000"])

    finally:
        if proc.poll() is None:
            proc.terminate()
            time.sleep(1)
            print("STDERR:", proc.stderr.read().decode())

if __name__ == "__main__":
    test_crash()
