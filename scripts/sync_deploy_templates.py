#!/usr/bin/env python3
"""Sincroniza a política online do app e as referências opcionais dos exemplos."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from image_tools import ROOT, OPTIONAL_NAMES, image_plan
from deploy_storage import TARGETS


def sync(root=ROOT, check=False):
    root = Path(root)
    plan = image_plan((root / "VERSION").read_text().strip(), "develop", "0" * 40, root)
    changed = []
    for environment in ("production", "develop"):
        folder = root / "deploy" / environment
        path = folder / "compose.yaml"
        data = json.loads(path.read_text())
        # ESCRITURA_IMAGE pode apontar para os aliases mutáveis develop/latest.
        # Referências fixadas no .env e --pull never preservam o fluxo offline.
        data["services"]["app"]["pull_policy"] = "always"
        for name, target in TARGETS.items():
            if name in {"app", "postgres"}:
                continue
            source = "./data/${COMPOSE_PROJECT_NAME:-escritura-" + environment + "}/" + name
            if name == "app":
                source = "${ESCRITURA_APP_DATA_BIND:?Execute deploy_storage.py prepare-app antes de atualizar; init prepara instalacao nova}"
            data["services"][name]["volumes"] = [{
                "type": "bind",
                "source": source,
                "target": target,
                "bind": {"create_host_path": False},
            }]
        # Shared with the former A1 override: same project + source + target
        # preserves an existing vault on upgrades, without rotating its key.
        data["services"]["app"]["environment"]["ESCRITURA_RECEPTION_VAULT_DIR"] = "/run/escritura/reception-vault"
        data["services"]["app"]["volumes"] = [data["services"]["app"]["volumes"][0], {
            "type": "volume", "source": "reception_vault",
            "target": "/run/escritura/reception-vault",
        }]
        data["volumes"] = {"reception_vault": {}, "app_data": {}, "postgres_data": {}}
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
