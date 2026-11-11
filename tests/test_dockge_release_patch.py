"""Contratos locais do suplemento Dockge: nenhum download, Docker ou upload."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

from scripts.ci import dockge_release_patch as patch


VERSION = "0.8.0-dev.19"
SOURCE = "a" * 40
TOOL = "b" * 40
REPOSITORY = "ghcr.io/codisplanfiscalai/escritura-integrada"


def fixture(environment="develop", version=VERSION):
    images = {}
    for name in ("base", "app", "redis", "postgres", "mysql", "minio"):
        repository = REPOSITORY + ("" if name == "app" else "-" + name)
        tag = version if name == "app" else "synthetic-1"
        images[name] = {"repository": repository, "tag": tag,
                        "reference": repository + ":" + tag,
                        "digest": "sha256:" + "1" * 64,
                        "image_id": "sha256:" + "2" * 64}
    manifest = {"schema_version": 1, "version": version, "channel": "develop",
                "platform": "linux/amd64", "source_sha": SOURCE,
                "status": "published", "images": images}
    port = "8001" if environment == "develop" else "8000"
    compose = {
        "name": "${COMPOSE_PROJECT_NAME:-escritura-" + environment + "}",
        "services": {"app": {"image": patch.APP_IMAGE,
                             "ports": [{"target": 8000, "published": "${ESCRITURA_PORT:-" + port + "}",
                                        "host_ip": "${ESCRITURA_BIND:-127.0.0.1}", "protocol": "tcp"}],
                             "volumes": ["app-data:/data"], "networks": ["internal"]},
                     "redis": {"profiles": ["redis"], "networks": ["internal"]}},
        "volumes": {"app-data": {}}, "networks": {"internal": {"internal": True}},
        "x-preserve": {"text": "síntese", "list": [1, True, None]},
    }
    env = ("# Synthetic only\nCOMPOSE_PROJECT_NAME=escritura-" + environment
           + "\nESCRITURA_BIND=127.0.0.1\nESCRITURA_PORT=" + port
           + "\nESCRITURA_IMAGE=" + images["app"]["reference"] + "\n").encode()
    return {
        "compose.yaml": json.dumps(compose, ensure_ascii=False, indent=4).encode(),
        "images.json": json.dumps(manifest, indent=2).encode(),
        ".env": env, ".env.example": env.replace(b"\n", b"\r\n"),
        "LEIA-ME.txt": b"Synthetic readme\r\n", "DEPLOY.md": b"# Synthetic\n\n",
        "THIRD-PARTY.md": b"Exact binary preservation: \x00\xff\n",
    }


class DockgeReleasePatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input = self.root / "download.zip"
        self.output = self.root / "output"

    def archive(self, files=None, *, environment="develop", entries=None, mutate_info=None):
        files = fixture(environment) if files is None else files
        prefix = "EscrituraIntegrada-" + VERSION + "-" + environment + "-deploy/"
        entries = list(files.items()) if entries is None else entries
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.input, "w") as bundle:
                bundle.comment = b"preserve archive comment"
                for name, data in entries:
                    info = zipfile.ZipInfo(prefix + name, (2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (stat.S_IFREG | (0o600 if name == ".env" else 0o644)) << 16
                    info.comment = b"preserve entry comment"
                    if mutate_info:
                        mutate_info(info)
                    bundle.writestr(info, data)
        return files

    def run_patch(self, **kwargs):
        options = dict(expected_sha256=patch.digest(self.input.read_bytes()), version=VERSION,
                       environment="develop", output_dir=self.output,
                       tool_commit=TOOL, expected_source_sha=SOURCE)
        options.update(kwargs)
        return patch.patch_archive(self.input, **options)

    def test_preserves_six_files_prefix_metadata_and_original_for_both_environments(self):
        for environment in ("develop", "production"):
            with self.subTest(environment=environment):
                before = self.archive(environment=environment)
                original_bytes = self.input.read_bytes()
                report = self.run_patch(environment=environment)
                target = self.output / report["patched"]["file"]
                self.assertTrue(target.name.endswith("-dockge-r1.zip"))
                with zipfile.ZipFile(self.input) as original, zipfile.ZipFile(target) as result:
                    self.assertEqual(original.namelist(), result.namelist())
                    self.assertEqual(original.comment, result.comment)
                    for old, new in zip(original.infolist(), result.infolist()):
                        self.assertEqual((old.date_time, old.external_attr, old.comment),
                                         (new.date_time, new.external_attr, new.comment))
                        name = old.filename.rsplit("/", 1)[-1]
                        if name != "compose.yaml":
                            self.assertEqual(result.read(new), before[name])
                    changed = json.loads(result.read(report["internal_prefix"] + "compose.yaml"))
                source = json.loads(before["compose.yaml"])
                ports = changed["services"]["app"].pop("ports")
                long_ports = source["services"]["app"].pop("ports")
                self.assertEqual(source, changed)
                for bind in ("127.0.0.1", "192.0.2.3"):
                    for port in ("8001" if environment == "develop" else "8000", "48001"):
                        short = ports[0].replace(long_ports[0]["host_ip"], bind).replace(long_ports[0]["published"], port)
                        address, protocol = short.split("/")
                        host, published, target_port = address.split(":")
                        self.assertEqual((host, published, int(target_port), protocol), (bind, port, 8000, "tcp"))
                self.assertEqual(self.input.read_bytes(), original_bytes)
                self.assertEqual(report["source_sha"], SOURCE)
                self.assertEqual(report["tool_commit"], TOOL)
                self.assertEqual(len(report["files"]), 7)
                self.assertEqual([row["path"] for row in report["files"] if row["changed"]],
                                 [report["internal_prefix"] + "compose.yaml"])
                self.assertEqual(target.with_suffix(".zip.sha256").read_text(),
                                 patch.digest(target.read_bytes()) + "  " + target.name + "\n")
                self.assertEqual(json.loads(target.with_suffix(".zip.report.json").read_bytes()), report)

    def test_rejects_wrong_or_missing_digest_and_source(self):
        self.archive()
        for options in ({"expected_sha256": "0" * 64}, {"expected_sha256": ""},
                        {"expected_source_sha": "c" * 40}, {"tool_commit": "main"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_patch(**options)
        self.assertFalse(self.output.exists())

    def test_rejects_unexpected_missing_traversal_nested_and_duplicate_members(self):
        files = fixture()
        cases = [list(files.items()) + [("extra.txt", b"extra")], list(files.items())[1:],
                 list(files.items()) + [("compose.yaml", files["compose.yaml"])]]
        for bad_name in ("../compose.yaml", "/compose.yaml", "nested/compose.yaml", "..\\compose.yaml"):
            cases.append([(bad_name, files["compose.yaml"]), *list(files.items())[1:]])
        for entries in cases:
            with self.subTest(names=[name for name, _ in entries]):
                self.archive(entries=entries)
                with self.assertRaisesRegex(ValueError, "allowlist|duplicados"):
                    self.run_patch()
        self.assertFalse(self.output.exists())

    def test_rejects_symlink_entries_encryption_and_unsupported_compression(self):
        def symlink(info):
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.archive(mutate_info=symlink)
        with self.assertRaisesRegex(ValueError, "não regular"):
            self.run_patch()
        self.archive()
        raw = bytearray(self.input.read_bytes())
        for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            position = raw.index(signature) + offset
            struct.pack_into("<H", raw, position, struct.unpack_from("<H", raw, position)[0] | 1)
        self.input.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "criptografado"):
            self.run_patch()
        self.archive(mutate_info=lambda info: setattr(info, "compress_type", zipfile.ZIP_BZIP2))
        with self.assertRaisesRegex(ValueError, "compressão ZIP"):
            self.run_patch()

    def test_rejects_oversized_archives_members_totals_and_compression_bombs(self):
        self.archive()
        for limit in ("MAX_ARCHIVE_BYTES", "MAX_FILE_BYTES", "MAX_TOTAL_BYTES"):
            with self.subTest(limit=limit), mock.patch.object(patch, limit, 10):
                with self.assertRaises(ValueError):
                    self.run_patch()
        files = fixture()
        files["DEPLOY.md"] = b"a" * 100000
        self.archive(files)
        with self.assertRaisesRegex(ValueError, "razão de compressão"):
            self.run_patch()

    def test_rejects_wrong_version_image_reference_source_and_environment(self):
        for field, value in (("version", "0.7.3"), ("source_sha", "c" * 40)):
            files = fixture()
            manifest = json.loads(files["images.json"])
            manifest[field] = value
            files["images.json"] = json.dumps(manifest).encode()
            self.archive(files)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_patch()
        for filename in (".env", ".env.example"):
            files = fixture()
            files[filename] = files[filename].replace(VERSION.encode(), b"wrong")
            self.archive(files)
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, "identidade"):
                self.run_patch()
        self.archive()
        with self.assertRaises(ValueError):
            self.run_patch(environment="production")

    def test_rejects_unexpected_ports_and_duplicate_json_keys(self):
        for mutation in (lambda port: port.update(protocol="udp"), lambda port: port.update(target=8000.0),
                         lambda port: port.update(mode="host"), lambda port: port.update(host_ip="0.0.0.0")):
            files = fixture()
            compose = json.loads(files["compose.yaml"])
            mutation(compose["services"]["app"]["ports"][0])
            files["compose.yaml"] = json.dumps(compose).encode()
            self.archive(files)
            with self.assertRaisesRegex(ValueError, "ports"):
                self.run_patch()
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}', b'[]', b'not json'):
            files = fixture()
            files["compose.yaml"] = data
            self.archive(files)
            with self.assertRaises(ValueError):
                self.run_patch()

    def test_refuses_repatch_overwrite_and_symlink_input(self):
        self.archive()
        report = self.run_patch()
        saved = {path.name: path.read_bytes() for path in self.output.iterdir()}
        with self.assertRaisesRegex(ValueError, "Destino já existe"):
            self.run_patch()
        self.assertEqual(saved, {path.name: path.read_bytes() for path in self.output.iterdir()})
        target = self.output / report["patched"]["file"]
        self.input.write_bytes(target.read_bytes())
        with self.assertRaisesRegex(ValueError, "ports"):
            self.run_patch(output_dir=self.root / "second-output")
        self.input.unlink()
        self.input.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "não link"):
            self.run_patch()

    def test_rejects_corrupt_zip_before_writing(self):
        self.input.write_bytes(b"not a ZIP")
        with self.assertRaisesRegex(ValueError, "ZIP inválido"):
            self.run_patch()
        self.assertFalse(self.output.exists())

    def test_cli_requires_expected_hash_and_writes_local_outputs(self):
        self.archive()
        command = [sys.executable, "-m", "scripts.ci.dockge_release_patch", "--zip", str(self.input),
                   "--version", VERSION, "--environment", "develop", "--output-dir", str(self.output),
                   "--tool-commit", TOOL, "--expected-source-sha", SOURCE]
        missing = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("--expected-sha256", missing.stderr)
        result = subprocess.run(command + ["--expected-sha256", patch.digest(self.input.read_bytes())],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["version"], VERSION)
        self.assertEqual(len(list(self.output.iterdir())), 3)


if __name__ == "__main__":
    unittest.main()
