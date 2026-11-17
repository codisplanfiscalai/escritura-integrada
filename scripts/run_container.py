"""Entrada do container. A interface é servida pela mesma API usada no desktop."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api import create_app
from app.reverse_proxy import forwarded_allow_ips
import uvicorn


def main():
    trusted_proxies = forwarded_allow_ips()
    application = create_app(
        data_dir=os.environ.get("ESCRITURA_DATA_DIR", "/data"),
        demo=os.environ.get("ESCRITURA_DEMO", "0") == "1",
    )
    uvicorn.run(application, host="0.0.0.0", port=8000, workers=1,
                access_log=False, proxy_headers=True, forwarded_allow_ips=trusted_proxies, ws_max_size=2048, ws_max_queue=4, ws_per_message_deflate=False, timeout_graceful_shutdown=20)


if __name__ == "__main__":
    main()
