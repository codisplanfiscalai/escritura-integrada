"""Prévia de aceitação exclusivamente com dados fictícios e diretório separado."""
from pathlib import Path
import os
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["ESCRITURA_DEMO"] = "1"
os.environ.setdefault("ESCRITURA_DATA_DIR", str(ROOT / ".preview-data"))

import uvicorn
from app.api import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "3000")))
    parser.add_argument("--strictPort", action="store_true")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, workers=1)
