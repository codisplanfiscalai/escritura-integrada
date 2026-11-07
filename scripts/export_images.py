#!/usr/bin/env python3
"""Exporta seis imagens GHCR publicadas para docker save+gzip; load verificável no CI."""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from image_tools import IMAGE_NAMES, read_json, run, sha256_file, validate_manifest, write_json


def image_id(reference):
    return run(["docker", "image", "inspect", "--format", "{{.Id}}", reference], capture=True).stdout.strip()


def assert_ids(manifest):
    for name in IMAGE_NAMES:
        item = manifest["images"][name]
        if image_id(item["reference"]) != item["image_id"]:
            raise RuntimeError("ID local diverge do publicado: " + item["reference"])


def save_gzip(references, output):
    """Streaming: não mantém tar ou imagens inteiras em RAM/disco temporário."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    command = ["docker", "image", "save", *references]
    print("+ " + " ".join(command) + " | gzip -> " + str(output), flush=True)
    try:
        with tempfile.TemporaryFile() as errors, partial.open("wb") as target:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            try:
                with gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0, compresslevel=6) as packed:
                    for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
                        packed.write(chunk)
                code = process.wait()
                if code:
                    errors.seek(0)
                    raise RuntimeError("docker save falhou: " + errors.read(3000).decode(errors="replace"))
            except BaseException:
                process.kill()
                process.wait()
                raise
            finally:
                process.stdout.close()
        partial.replace(output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def verify_load(manifest, archive, manifest_path):
    references = [manifest["images"][name]["reference"] for name in IMAGE_NAMES]
    for reference in references:
        used = run(["docker", "ps", "--all", "--filter", "ancestor=" + reference, "--format", "{{.ID}}"], capture=True).stdout.strip()
        if used:
            raise RuntimeError("A verificação de carga exige runner isolado, sem containers usando " + reference)
    # Sem --force: só remove as tags exatas deste manifesto; nunca faz prune global.
    run(["docker", "image", "rm", *references])
    for reference in references:
        found = run(["docker", "image", "inspect", reference], capture=True, check=False)
        if found.returncode == 0:
            raise RuntimeError("A tag ainda estava presente antes da carga; teste offline inconclusivo.")
    run(["docker", "image", "load", "--input", str(archive.resolve())])
    assert_ids(manifest)
    smoke = archive.with_suffix(".load-smoke.json")
    run([sys.executable, "scripts/smoke_images.py", "--images-manifest", manifest_path, "--output", smoke])
    return read_json(smoke)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-load", action="store_true", help="Runner isolado: remove tags deste bundle, recarrega e testa com --pull never.")
    args = parser.parse_args()
    manifest = validate_manifest(read_json(args.images_manifest))
    assert_ids(manifest)
    references = [manifest["images"][name]["reference"] for name in IMAGE_NAMES]
    save_gzip(references, args.output)
    digest = sha256_file(args.output)
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(digest + "  " + args.output.name + "\n")
    result = {"version": manifest["version"], "source_sha": manifest["source_sha"], "platform": manifest["platform"],
              "file": args.output.name, "sha256": digest, "bytes": args.output.stat().st_size,
              "images": manifest["images"], "offline_load_verified": False}
    manifest_output = args.output.with_suffix(args.output.suffix + ".manifest.json")
    write_json(manifest_output, result)
    if args.verify_load:
        result["load_smoke"] = verify_load(manifest, args.output, args.images_manifest)
        result["offline_load_verified"] = result["load_smoke"].get("status") == "passed"
        write_json(manifest_output, result)
    print(json.dumps({"file": args.output.name, "sha256": digest, "offline_load_verified": result["offline_load_verified"]}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print("ERRO: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
