"""Smoke-test a staged agent package through a real local HTTP process."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import requests


def check(source: Path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = dict(os.environ)
    environment.pop("DATABRICKS_APP_NAME", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "research_app.agent_server:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=source.resolve(), env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(process.stderr.read().decode("utf-8", errors="replace"))
            try:
                response = requests.get(base + "/health", timeout=1)
                if response.status_code == 200:
                    break
            except requests.ConnectionError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Packaged server did not become healthy.")
        assert response.json()["status"] == "ok"
        assert requests.post(base + "/research", json={"provider": "Unknown"}, timeout=2).status_code == 422
        assert requests.post(base + "/research", json={}, timeout=2).status_code == 503
        print("Packaged HTTP server: health, request validation, and hosted identity requirement passed.")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stderr.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    check(parser.parse_args().source)
