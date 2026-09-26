"""Avvio: python -m app  → http://127.0.0.1:8000"""
import os
import threading
import webbrowser

import uvicorn

from .main import create_app


def main() -> None:
    port = int(os.environ.get("FBM_PORT", "8000"))
    # Solo 127.0.0.1: l'app non ha password, quindi non va esposta in rete.
    url = f"http://127.0.0.1:{port}"
    print(f"\n  Monitor gruppi Facebook → {url}\n")
    if os.environ.get("FBM_NO_OPEN") != "1":
        # Apre l'interfaccia appena il server è pronto.
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
