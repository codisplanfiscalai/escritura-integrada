"""Entrada do container. A interface é servida pela mesma API usada no desktop."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api import create_app
import uvicorn


def main():
    application = create_app(
        data_dir=os.environ.get("ESCRITURA_DATA_DIR", "/data"),
        demo=os.environ.get("ESCRITURA_DEMO", "0") == "1",
    )
    uvicorn.run(application, host="0.0.0.0", port=8000, workers=1,
                # The updater uses Docker stop?t=-1 and waits for a clean exit.
                # Do not cancel admitted writes halfway through the drain.
                access_log=False, timeout_graceful_shutdown=None)


if __name__ == "__main__":
    main()
