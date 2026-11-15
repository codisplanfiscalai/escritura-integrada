"""Safe storage preparation/cold-copy contracts; real Compose is smoke_storage.py."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deploy_storage as storage


@unittest.skipUnless(os.name == "posix", "Filesystem worker runs inside Linux Docker, not on the Windows host.")
class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = root / "stack"
        self.project.mkdir()
        self.source = root / "source"
        self.plan = {"schema": storage.SCHEMA, "project": "synthetic-develop", "directory": str(self.project),
                     "helper_image": "sha256:" + "a" * 64, "compose_file": str(self.project / "compose.named.yaml"),
                     "sources": {name: {"name": "synthetic-" + name, "logical": name + "-data", "created_at": "synthetic"}
                                 for name in storage.TARGETS}}
        for name in storage.TARGETS:
            folder = self.source / name
            (folder / "nested").mkdir(parents=True)
            (folder / "nested/document.xml").write_bytes(b"<NFe>ficticia\x00\xff</NFe>\r\n")
            (folder / "empty").write_bytes(b"")
            os.chmod(folder / "nested/document.xml", 0o640)
            os.utime(folder / "nested/document.xml", ns=(1700000000123456789, 1700000000123456789))
        os.link(self.source / "app/nested/document.xml", self.source / "app/hardlink.xml")
        self.before = {name: storage.inventory(self.source / name) for name in storage.TARGETS}
        self.target = self.project / "data/synthetic-develop"

    def worker(self, plan, action, stage=None):
        return storage.filesystem_action(self.project, {"plan": plan, "action": action, "stage": stage}, self.source)

    def assert_originals(self):
        for name, expected in self.before.items():
            self.assertEqual(storage.inventory(self.source / name), expected)

    def test_copy_verify_preserves_all_bytes_metadata_and_hardlinks(self):
        with mock.patch.object(storage, "assert_stopped"), mock.patch.object(storage, "worker", side_effect=self.worker):
            self.assertTrue(storage.execute(self.plan)["verified"])
            self.assertTrue(storage.execute(self.plan, verify=True)["original_volumes_preserved"])
        self.assert_originals()
        for name, expected in self.before.items():
            self.assertEqual(storage.inventory(self.target / name), expected)
        self.assertEqual((self.target / "app/hardlink.xml").stat().st_ino,
                         (self.target / "app/nested/document.xml").stat().st_ino)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.target / ".storage-manifest.json").stat().st_mode), 0o600)

    def test_existing_empty_destination_and_file_are_never_replaced(self):
        self.target.mkdir(parents=True)
        inode = self.target.stat().st_ino
        with self.assertRaisesRegex(storage.StorageError, "Destino já existe"):
            self.worker(self.plan, "stage")
        self.assertEqual(self.target.stat().st_ino, inode)
        self.target.rmdir()
        self.target.write_bytes(b"do-not-touch")
        with self.assertRaises(storage.StorageError):
            self.worker(self.plan, "stage")
        self.assertEqual(self.target.read_bytes(), b"do-not-touch")
        self.assert_originals()

    def test_copy_failure_rolls_back_only_staging(self):
        real = storage.copy_tree
        def fail(source, target):
            if source.name == "postgres":
                raise OSError("Synthetic full disk after two copied services")
            return real(source, target)
        with mock.patch.object(storage, "copy_tree", side_effect=fail), self.assertRaises(OSError):
            self.worker(self.plan, "stage")
        self.assertFalse(self.target.exists())
        self.assertEqual(list((self.project / "data").iterdir()), [])
        self.assert_originals()

    def test_late_writer_aborts_staging_without_publishing(self):
        with mock.patch.object(storage, "assert_stopped", side_effect=[None, storage.StorageError("writer")]), \
                mock.patch.object(storage, "worker", side_effect=self.worker), self.assertRaisesRegex(storage.StorageError, "writer"):
            storage.execute(self.plan)
        self.assertFalse(self.target.exists())
        self.assertEqual(list((self.project / "data").iterdir()), [])
        self.assert_originals()

    def test_corrupted_copy_prevents_commit_and_execute_cleans_staging(self):
        def corrupt(plan, action, stage=None):
            if action == "commit":
                (self.project / "data" / stage / "app/empty").write_bytes(b"corrupt")
            return self.worker(plan, action, stage)
        with mock.patch.object(storage, "assert_stopped"), mock.patch.object(storage, "worker", side_effect=corrupt), \
                self.assertRaisesRegex(storage.StorageError, "Destino divergiu"):
            storage.execute(self.plan)
        self.assertFalse(self.target.exists())
        self.assertEqual(list((self.project / "data").iterdir()), [])
        self.assert_originals()

    def test_exclusive_publish_refuses_destination_created_after_staging(self):
        stage = self.worker(self.plan, "stage")["stage"]
        self.target.mkdir()
        marker = self.target / "existing"
        marker.write_bytes(b"keep")
        with self.assertRaisesRegex(storage.StorageError, "Destino já existe"):
            self.worker(self.plan, "commit", stage)
        self.assertEqual(marker.read_bytes(), b"keep")
        self.worker(self.plan, "abort", stage)
        self.assert_originals()

    def test_source_change_after_copy_is_detected_without_publishing(self):
        stage = self.worker(self.plan, "stage")["stage"]
        (self.source / "redis/empty").write_bytes(b"new-write")
        with self.assertRaisesRegex(storage.StorageError, "Origem mudou"):
            self.worker(self.plan, "commit", stage)
        self.assertFalse(self.target.exists())
        self.worker(self.plan, "abort", stage)
        self.assertEqual((self.source / "redis/empty").read_bytes(), b"new-write")

    def test_symlinks_special_files_and_symlink_parent_are_refused(self):
        link = self.source / "app/external"
        link.symlink_to(self.source / "redis", target_is_directory=True)
        with self.assertRaisesRegex(storage.StorageError, "Link simbólico"):
            self.worker(self.plan, "stage")
        link.unlink()
        fifo = self.source / "app/fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(storage.StorageError, "arquivo especial"):
            self.worker(self.plan, "stage")
        fifo.unlink()
        (self.project / "data").rmdir()
        (self.project / "data").symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(storage.StorageError, "link simbólico"):
            self.worker(self.plan, "stage")
        self.assertFalse((self.source / "synthetic-develop").exists())

    def test_verify_refuses_other_project_and_changed_destination(self):
        self.worker(self.plan, "commit", self.worker(self.plan, "stage")["stage"])
        other = copy.deepcopy(self.plan)
        other["helper_image"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(storage.StorageError, "outro plano"):
            self.worker(other, "verify")
        (self.target / "mysql/empty").write_bytes(b"changed")
        with self.assertRaisesRegex(storage.StorageError, "Destino divergiu"):
            self.worker(self.plan, "verify")
        self.assert_originals()

    def test_only_known_mysql_runtime_socket_link_is_copied_without_following(self):
        link = self.source / "mysql/mysql.sock"
        link.symlink_to("/var/run/mysqld/mysqld.sock")
        before = storage.inventory(self.source / "mysql")
        self.worker(self.plan, "commit", self.worker(self.plan, "stage")["stage"])
        self.assertTrue((self.target / "mysql/mysql.sock").is_symlink())
        self.assertEqual(os.readlink(self.target / "mysql/mysql.sock"), "/var/run/mysqld/mysqld.sock")
        self.assertEqual(storage.inventory(self.target / "mysql"), before)
        link.unlink()
        link.symlink_to("/etc/shadow")
        with self.assertRaises(storage.StorageError):
            storage.inventory(self.source / "mysql")


class PlanTests(unittest.TestCase):
    def test_project_traversal_and_remote_daemon_are_refused(self):
        for name in ("../production", "", "/tmp/stack", "UPPER", "a/b", "a,b"):
            with self.subTest(name=name), self.assertRaises(storage.StorageError):
                storage.project_name(name)
        with mock.patch.dict(os.environ, {"DOCKER_HOST": "ssh://host"}, clear=True), \
                mock.patch.object(storage, "docker") as docker, self.assertRaises(storage.StorageError):
            storage.local_daemon()
        docker.assert_not_called()

    def test_init_refuses_existing_stack(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(storage, "image_id", return_value="sha256:" + "a" * 64), \
                mock.patch.object(storage, "docker", return_value="existing-container\n"), self.assertRaisesRegex(storage.StorageError, "já tem"):
            storage.make_plan(root, "existing", "synthetic")

    def test_foreign_or_nonlocal_volumes_are_refused(self):
        value = {"Driver": "local", "Options": None, "CreatedAt": "test",
                 "Labels": {"com.docker.compose.project": "develop", "com.docker.compose.volume": "app-data"}}
        for mutation in ({"Driver": "nfs"}, {"Options": {"device": "/other"}}, {"Labels": {"com.docker.compose.project": "production"}}):
            with mock.patch.object(storage, "docker", return_value=json.dumps([{**value, **mutation}])), self.assertRaises(storage.StorageError):
                storage.volume_info("original", "develop", "app-data")

    def test_plan_resolves_actual_volume_names_and_omits_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compose = root / "compose.named.yaml"
            compose.write_text("synthetic")
            config = {"name": "develop", "services": {}, "volumes": {}}
            for name, target in storage.TARGETS.items():
                logical = name + "-data"
                config["services"][name] = {"image": "registry.invalid/tag-that-moved", "environment": {"PASSWORD": "SYNTHETIC_SECRET"},
                                             "volumes": [{"type": "volume", "source": logical, "target": target}]}
                config["volumes"][logical] = {"name": "actual-prefix_" + logical}
            selected = []
            def docker(*args, **kwargs):
                if args[0] == "compose": return json.dumps(config)
                if args[0] == "ps":
                    selected[:] = [args[-1].split("=")[-1]]
                    return "existing"
                name = selected[0]
                return json.dumps([{"Image": "sha256:" + "b" * 64,
                                    "Mounts": [{"Type": "volume", "Destination": storage.TARGETS[name], "Name": "actual-prefix_" + name + "-data"}]}])
            with mock.patch.object(storage, "image_id", side_effect=lambda value: value if storage.IMAGE_ID.fullmatch(value) else "sha256:" + "a" * 64) as images, \
                    mock.patch.object(storage, "docker", side_effect=docker), \
                    mock.patch.object(storage, "volume_info", side_effect=lambda n, p, l: {"name": n, "logical": l, "created_at": "test"}):
                plan = storage.make_plan(root, "develop", "synthetic", compose)
            self.assertEqual(plan["sources"]["app"]["name"], "actual-prefix_app-data")
            self.assertNotIn("SYNTHETIC_SECRET", json.dumps(plan))
            self.assertNotIn("environment", json.dumps(plan))
            lock = storage.image_lock(plan)
            self.assertEqual(set(lock), {"services"})
            self.assertTrue(all(value == {"image": "sha256:" + "b" * 64, "pull_policy": "never"}
                                for value in lock["services"].values()))
            self.assertFalse(any(call.args[0] == "registry.invalid/tag-that-moved" for call in images.call_args_list))
            # The right project label alone does not permit swapping app and Redis volumes.
            config["services"]["app"]["volumes"][0]["source"] = "redis-data"
            with mock.patch.object(storage, "image_id", return_value="sha256:" + "a" * 64), \
                    mock.patch.object(storage, "docker", return_value=json.dumps(config)), self.assertRaisesRegex(storage.StorageError, "entre serviços"):
                storage.make_plan(root, "develop", "synthetic", compose)

    def test_plan_refuses_compose_that_disagrees_with_existing_container_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compose = root / "compose.named.yaml"
            compose.write_text("synthetic")
            config = {"name": "develop", "services": {
                name: {"volumes": [{"type": "volume", "source": name + "-data", "target": target}]}
                for name, target in storage.TARGETS.items()}, "volumes": {"app-data": {"name": "expected"}}}
            def docker(*args, **kwargs):
                if args[0] == "compose": return json.dumps(config)
                if args[0] == "ps": return "existing"
                return json.dumps([{"Mounts": [{"Type": "volume", "Destination": "/data", "Name": "other-data"}]}])
            with mock.patch.object(storage, "image_id", return_value="sha256:" + "a" * 64), \
                    mock.patch.object(storage, "docker", side_effect=docker), \
                    mock.patch.object(storage, "volume_info", return_value={"name": "expected"}), self.assertRaisesRegex(storage.StorageError, "diverge do mount"):
                storage.make_plan(root, "develop", "synthetic", compose)

    def test_running_paused_and_restarting_writers_and_volume_replacement_are_refused(self):
        plan = {"project": "develop", "sources": {"app": {"name": "original", "logical": "app-data", "created_at": "old"}}}
        for state in ("running", "paused", "restarting"):
            with mock.patch.object(storage, "docker", side_effect=["container", json.dumps([{"State": {"Status": state}}])]), \
                    self.assertRaisesRegex(storage.StorageError, "ativo"):
                storage.assert_stopped(plan)
        with mock.patch.object(storage, "docker", return_value=""), \
                mock.patch.object(storage, "volume_info", return_value={"created_at": "new"}), self.assertRaisesRegex(storage.StorageError, "identidade"):
            storage.assert_stopped(plan)


if __name__ == "__main__":
    unittest.main()
