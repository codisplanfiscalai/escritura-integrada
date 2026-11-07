#!/usr/bin/env python3
"""Atualiza referências opcionais dos exemplos após mudança do catálogo/Dockerfiles."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from image_tools import ROOT, OPTIONAL_NAMES, image_plan


def sync(root=ROOT, check=False):
    root = Path(root)
    plan = image_plan((root / "VERSION").read_text().strip(), "develop", "0" * 40, root)
    changed = []
    for environment in ("production", "develop"):
        folder = root / "deploy" / environment
        path = folder / "compose.yaml"
        data = json.loads(path.read_text())
        for name in OPTIONAL_NAMES:
            data["services"][name]["image"] = "${" + name.upper() + "_IMAGE:-" + plan["images"][name]["reference"] + "}"
        wanted = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if path.read_text() != wanted:
            changed.append(str(path.relative_to(root)))
            if not check:
                path.write_text(wanted)
        env_path = folder / ".env.example"
        lines = env_path.read_text().splitlines()
        for name in OPTIONAL_NAMES:
            key = name.upper() + "_IMAGE="
            lines = [key + plan["images"][name]["reference"] if line.startswith(key) else line for line in lines]
        wanted_env = "\n".join(lines) + "\n"
        if env_path.read_text() != wanted_env:
            changed.append(str(env_path.relative_to(root)))
            if not check:
                env_path.write_text(wanted_env)
        if environment == "production" and (root / "compose.yaml").read_text() != wanted:
            changed.append("compose.yaml")
            if not check:
                (root / "compose.yaml").write_text(wanted)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed = sync(check=args.check)
    print(json.dumps({"check_only": args.check, "changed": changed}, ensure_ascii=False))
    raise SystemExit(1 if args.check and changed else 0)
