"""Contratos de distribuição sem daemon Docker; smoke real pertence ao CI."""
from __future__ import annotations

import copy
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_images import assert_identity, remote_exists
from export_images import save_gzip, verify_load
from image_tools import GHCR_PREFIX, IMAGE_NAMES, OPTIONAL_NAMES, image_plan, load_catalog, validate_manifest, validate_version
from package_deploy import deployment_env, package
from sync_deploy_templates import sync


def published_fixture():
    """Manifesto inteiramente fictício; não representa publicação realizada."""
    data = image_plan("0.4.0-test.1", "develop", "a" * 40)
    data["status"] = "published"
    for index, item in enumerate(data["images"].values(), 1):
        item["digest"] = "sha256:" + str(index) * 64
        item["image_id"] = "sha256:" + str(index + 1) * 64
        item["public_pullable"] = False
    return data


class InfrastructureTests(unittest.TestCase):
    def test_upstream_catalog_has_verified_pins_and_only_expected_images(self):
        catalog = load_catalog()
        self.assertEqual(set(catalog["images"]), set(IMAGE_NAMES))
        for item in catalog["upstreams"].values():
            self.assertNotIn("latest", item["reference"])
            self.assertIn("@sha256:", item["reference"])
            self.assertIn({"architecture": "amd64", "os": "linux"}, item["platforms"])
        self.assertEqual(catalog["minio_source"]["version"], "RELEASE.2025-10-15T17-29-55Z")
        self.assertEqual(len(catalog["minio_source"]["sha256"]), 64)

    def test_runtime_lock_pins_all_runtime_packages_and_windows_marker(self):
        text = (ROOT / "docker/runtime.lock").read_text()
        blocks = [b for b in text.split("\n\n") if re.search(r"(?m)^[a-z][\w-]*==", b)]
        self.assertEqual(len(blocks), 15)
        for block in blocks:
            self.assertRegex(block, r"--hash=sha256:[0-9a-f]{64}")
        self.assertIn('colorama==0.4.6 ; sys_platform == "win32"', text)
        self.assertNotIn("--extra-index-url", text)

    def test_distribution_names_are_safe_and_semver_plus_maps_to_oci(self):
        self.assertEqual(validate_version("1.2.3-dev.4+build.5"), "1.2.3-dev.4_build.5")
        for invalid in ("latest", "../1.2.3", "1.2.3\nTOKEN=bad", "1.2.3;rm", "1.2"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_version(invalid)

    def test_base_and_mirror_identity_stable_app_identity_tracks_source(self):
        first = image_plan("0.4.0-test.1", "develop", "a" * 40)
        second = image_plan("0.4.0-test.1", "develop", "b" * 40)
        for name in ("base", *OPTIONAL_NAMES):
            self.assertEqual(first["images"][name]["tag"], second["images"][name]["tag"])
        self.assertNotEqual(first["images"]["app"]["content_id"], second["images"]["app"]["content_id"])
        self.assertEqual(first["images"]["app"]["tag"], second["images"]["app"]["tag"])

    def test_existing_tag_with_different_content_or_commit_is_rejected(self):
        wanted = image_plan("0.4.0-test.1", "develop", "a" * 40)["images"]["app"]
        actual = {"labels": {"io.escritura.content-id": wanted["content_id"], "org.opencontainers.image.revision": "a" * 40}}
        assert_identity("app", wanted, actual, "a" * 40)
        with self.assertRaisesRegex(RuntimeError, "outro commit"):
            assert_identity("app", wanted, actual, "b" * 40)
        actual["labels"]["io.escritura.content-id"] = "b" * 64
        with self.assertRaisesRegex(RuntimeError, "outro conteúdo"):
            assert_identity("app", wanted, actual, "a" * 40)

    def test_registry_authorization_failure_is_not_treated_as_free_tag(self):
        denied = subprocess.CompletedProcess([], 1, "", "unauthorized: authentication required")
        missing = subprocess.CompletedProcess([], 1, "", "manifest unknown")
        with mock.patch("build_images.run", return_value=denied), self.assertRaises(RuntimeError):
            remote_exists(GHCR_PREFIX + ":0.4.0")
        with mock.patch("build_images.run", return_value=missing):
            self.assertFalse(remote_exists(GHCR_PREFIX + ":0.4.0"))

    def test_compose_only_publishes_one_app_port_without_build_or_source_mount(self):
        for environment in ("production", "develop"):
            path = ROOT / "deploy" / environment / "compose.yaml"
            data = json.loads(path.read_text())
            self.assertEqual(set(data["services"]), {"app", *OPTIONAL_NAMES})
            self.assertTrue(data["networks"]["internal"]["internal"])
            self.assertEqual(data["services"]["app"]["networks"], ["application", "internal"])
            count = 0
            for name, service in data["services"].items():
                self.assertNotIn("build", service)
                self.assertNotIn("network_mode", service)
                self.assertNotIn("privileged", service)
                self.assertEqual(service["pull_policy"], "missing")
                self.assertIn("healthcheck", service)
                for mount in service.get("volumes", []):
                    self.assertIn(mount.split(":")[0], data["volumes"])
                count += len(service.get("ports", []))
                if name != "app":
                    self.assertEqual(service["profiles"], [name])
                    self.assertEqual(service["networks"], ["internal"])
                    self.assertNotIn("ports", service)
            self.assertEqual(count, 1)
            self.assertIn("127.0.0.1", data["services"]["app"]["ports"][0]["host_ip"])
            self.assertTrue(data["services"]["app"]["read_only"])

    def test_stage_projects_and_ports_differ_and_volumes_are_not_global(self):
        prod = json.loads((ROOT / "deploy/production/compose.yaml").read_text())
        dev = json.loads((ROOT / "deploy/develop/compose.yaml").read_text())
        self.assertNotEqual(prod["name"], dev["name"])
        self.assertNotEqual(prod["services"]["app"]["ports"], dev["services"]["app"]["ports"])
        for data in (prod, dev):
            for volume in data["volumes"].values():
                self.assertNotIn("name", volume)
                self.assertNotIn("external", volume)
        self.assertEqual((ROOT / "compose.yaml").read_bytes(), (ROOT / "deploy/production/compose.yaml").read_bytes())

    def test_optional_credentials_do_not_block_compose_interpolation(self):
        for environment in ("production", "develop"):
            text = (ROOT / "deploy" / environment / "compose.yaml").read_text()
            required = re.findall(r"\$\{([A-Z_]+):?\?", text)
            self.assertEqual(required, ["ESCRITURA_IMAGE"])
            for name in ("REDIS_PASSWORD", "POSTGRES_PASSWORD", "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
                self.assertIn("${" + name + ":-}", text)

    def test_deploy_examples_follow_current_content_tags(self):
        self.assertEqual(sync(check=True), [])

    def test_generated_env_is_ready_for_app_and_has_no_fixed_password(self):
        data = published_fixture()
        for environment, port in (("production", "8000"), ("develop", "8001")):
            value = deployment_env(data, environment)
            pairs = dict(line.split("=", 1) for line in value.splitlines() if "=" in line and not line.startswith("#"))
            self.assertEqual(pairs["ESCRITURA_PORT"], port)
            self.assertEqual(pairs["COMPOSE_PROJECT_NAME"], "escritura-" + environment)
            self.assertNotIn("@sha256", value)
            for key, content in pairs.items():
                if "PASSWORD" in key:
                    self.assertEqual(content, "")
                if key.endswith("_IMAGE"):
                    self.assertTrue(content.startswith(GHCR_PREFIX))
            self.assertEqual(pairs["MINIO_ROOT_USER"], "")

    def test_manifest_rejects_plan_foreign_images_missing_digests_and_env_injection(self):
        data = published_fixture()
        for mutation in (lambda x: x.update(status="planned"),
                         lambda x: x["images"]["redis"].update(repository="docker.io/library/redis"),
                         lambda x: x["images"]["app"].update(digest=None),
                         lambda x: x["images"]["app"].update(tag="1.2.3\nPASSWORD=injected")):
            candidate = copy.deepcopy(data)
            mutation(candidate)
            with self.assertRaises(ValueError):
                validate_manifest(candidate)

    def test_deploy_zip_allowlist_excludes_local_source_data_and_secrets(self):
        data = published_fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "source"
            shutil.copytree(ROOT / "deploy", root / "deploy")
            (root / "docs").mkdir()
            (root / "docker").mkdir()
            shutil.copy2(ROOT / "docs/DEPLOY.md", root / "docs/DEPLOY.md")
            shutil.copy2(ROOT / "docker/THIRD-PARTY.md", root / "docker/THIRD-PARTY.md")
            poison = b"SYNTHETIC_SECRET_MUST_NEVER_BE_PACKAGED"
            for name in (".env", "escritura.sqlite3", "recovered.exe", "private-source.py"):
                (root / name).write_bytes(poison)
            output = Path(temp) / "output"
            result = package(data, output, root=root)
            self.assertEqual(len(result["packages"]), 2)
            for entry in result["packages"]:
                with zipfile.ZipFile(output / entry["file"]) as archive:
                    self.assertEqual({Path(n).name for n in archive.namelist()},
                                     {"compose.yaml", ".env", ".env.example", "images.json", "LEIA-ME.txt", "DEPLOY.md", "THIRD-PARTY.md"})
                    for name in archive.namelist():
                        self.assertNotIn(poison, archive.read(name))
                self.assertTrue((output / (entry["file"] + ".sha256")).is_file())

    def test_save_stream_is_valid_gzip_and_failure_removes_partial(self):
        payload = b"synthetic docker-save stream\n" * 1000
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "images.tar.gz"
            process = mock.Mock(stdout=io.BytesIO(payload))
            process.wait.return_value = 0
            with mock.patch("export_images.subprocess.Popen", return_value=process):
                save_gzip([GHCR_PREFIX + ":0.4.0-test"], target)
            self.assertEqual(gzip.decompress(target.read_bytes()), payload)
            target.unlink()
            failed = mock.Mock(stdout=io.BytesIO(payload))
            failed.wait.return_value = 1
            with mock.patch("export_images.subprocess.Popen", return_value=failed), self.assertRaises(RuntimeError):
                save_gzip([GHCR_PREFIX + ":0.4.0-test"], target)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix(".gz.part").exists())

    def test_load_verification_refuses_images_in_use_before_removing_tags(self):
        calls = []
        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "container-in-use\n", "")
        with mock.patch("export_images.run", side_effect=fake_run), self.assertRaisesRegex(RuntimeError, "runner isolado"):
            verify_load(published_fixture(), Path("unused.tar.gz"), Path("unused.json"))
        self.assertFalse(any("rm" in command for command in calls))

    @unittest.skipUnless(os.name == "posix", "Guards sh são executados nos containers Linux e no CI Linux.")
    def test_real_entrypoint_guards_fail_clearly_for_missing_and_short_secrets(self):
        paths = {
            "redis": ("docker/mirrors/redis-entrypoint.sh", {"REDIS_PASSWORD": "short"}),
            "postgres": ("docker/mirrors/postgres-entrypoint.sh", {"POSTGRES_PASSWORD": "short"}),
            "mysql": ("docker/mirrors/mysql-entrypoint.sh", {"MYSQL_ROOT_PASSWORD": "short", "MYSQL_PASSWORD": "short"}),
            "minio": ("docker/minio-entrypoint.sh", {"MINIO_ROOT_USER": "ad", "MINIO_ROOT_PASSWORD": "short"}),
        }
        for name, (path, short_values) in paths.items():
            for extra in ({}, short_values):
                result = subprocess.run(["sh", str(ROOT / path)], env={"PATH": os.defpath, **extra}, text=True, capture_output=True)
                with self.subTest(name=name, missing=not extra):
                    self.assertEqual(result.returncode, 64)
                    self.assertIn("Perfil " + name, result.stderr)
                    self.assertNotIn("short", result.stderr)


if __name__ == "__main__":
    unittest.main()
