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
        probe = mock.patch.object(storage, "probe_app_image", return_value={"permissions_ok": True, "identity": {"uid": 10001, "gid": 10001}})
        self.probe = probe.start()
        self.addCleanup(probe.stop)
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

    def test_incompatible_app_permissions_abort_without_publishing_or_chowning_source(self):
        self.probe.return_value = {"permissions_ok": False, "identity": {"uid": 10001, "gid": 10001}}
        with mock.patch.object(storage, "assert_stopped"), mock.patch.object(storage, "worker", side_effect=self.worker), \
                self.assertRaisesRegex(storage.StorageError, "Pré-validação app UID/GID 10001:10001 recusada"):
            storage.execute(self.plan)
        self.assertFalse(self.target.exists())
        self.assertEqual(list((self.project / "data").iterdir()), [])
        self.assert_originals()

    def test_probe_directory_mtime_is_restored(self):
        def probe(image, source, **kwargs):
            path = Path(source) / ".probe"
            path.mkdir(); path.rmdir()
            return {"permissions_ok": True, "identity": {"uid": 10001, "gid": 10001}}
        self.probe.side_effect = probe
        with mock.patch.object(storage, "assert_stopped"), mock.patch.object(storage, "worker", side_effect=self.worker):
            result = storage.execute(self.plan)
        self.assertTrue(result["app_permissions_verified"])
        self.assertFalse(result["runtime_health_verified"])
        self.assertEqual(storage.inventory(self.target / "app"), self.before["app"])
        self.assert_originals()

    def test_probe_content_change_aborts_without_hiding_it_as_directory_mtime(self):
        def probe(image, source, **kwargs):
            (Path(source) / 'unexpected-file').write_bytes(b'synthetic unexpected mutation')
            return {'permissions_ok': True, 'identity': {'uid': 10001, 'gid': 10001}}
        self.probe.side_effect = probe
        with mock.patch.object(storage, 'assert_stopped'), mock.patch.object(storage, 'worker', side_effect=self.worker), \
                self.assertRaisesRegex(storage.StorageError, 'além de mtimes'):
            storage.execute(self.plan)
        self.assertFalse(self.target.exists())
        self.assertEqual(list((self.project / 'data').iterdir()), [])
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
    def test_existing_bind_is_refused_with_preservation_route_without_copying_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compose = root / "compose.current.yaml"
            compose.write_text("synthetic")
            config = {"name": "develop", "services": {name: {} for name in storage.TARGETS}}
            config["services"]["app"]["volumes"] = [{"type": "bind", "source": str(root / "data/app"), "target": "/data"}]
            with mock.patch.object(storage, "image_id", return_value="sha256:" + "a" * 64), \
                    mock.patch.object(storage, "docker", return_value=json.dumps(config)), \
                    mock.patch.object(storage, "volume_info") as volumes, mock.patch.object(storage, "worker") as worker, \
                    self.assertRaisesRegex(storage.StorageError, "compose.existing-bind.yaml"):
                storage.make_plan(root, "develop", "synthetic", compose)
            volumes.assert_not_called()
            worker.assert_not_called()
            self.assertFalse((root / "data").exists())

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

    def test_init_refuses_custom_bind_instead_of_preparing_wrong_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'compose.yaml').write_text('synthetic')
            def docker(*args, **kwargs):
                if args[0] in {'ps', 'volume'}: return ''
                return json.dumps({'services': {'app': {'volumes': [{'type': 'bind', 'source': str(root / 'data/app'), 'target': '/data'}]}}})
            with mock.patch.object(storage, 'image_id', return_value='sha256:' + 'a'*64), \
                    mock.patch.object(storage, 'docker', side_effect=docker), self.assertRaisesRegex(storage.StorageError, 'layout padrão novo'):
                storage.make_plan(root, 'synthetic', 'synthetic')
            self.assertFalse((root / 'data').exists())

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


@unittest.skipUnless(os.name == "posix", "Permission worker runs inside Linux containers.")
class AppPermissionTests(unittest.TestCase):
    def test_root_identity_is_refused_without_privileged_permission_probe(self):
        with mock.patch.object(storage.os, "geteuid", return_value=0), mock.patch.object(Path, "mkdir") as mkdir:
            result = storage.app_permissions(Path("/nonexistent-fixture"))
        self.assertFalse(result["permissions_ok"])
        self.assertEqual(result["identity_error"], "root_runtime_refused")
        mkdir.assert_not_called()

    def test_missing_database_blocks_existing_bind_but_not_new_install_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            self.assertFalse(storage.app_permissions(path)["permissions_ok"])
            self.assertTrue(storage.app_permissions(path, database_required=False)["permissions_ok"])
            self.assertEqual(list(path.iterdir()), [])

    def test_wal_and_backup_denials_are_reported_without_writing_database_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "backups").mkdir()
            files = [path / "escritura.sqlite3", path / "escritura.sqlite3-wal", path / "escritura.sqlite3-shm", path / "backups/old.sqlite3"]
            for file in files:
                file.write_bytes(b"synthetic-bytes")
            real_open = storage.os.open
            def denied(file, flags, *args, **kwargs):
                if str(file).endswith(("-wal", "old.sqlite3")):
                    raise PermissionError(13, "synthetic permission denial")
                return real_open(file, flags, *args, **kwargs)
            with mock.patch.object(storage.os, "open", side_effect=denied):
                result = storage.app_permissions(path)
            self.assertFalse(result["permissions_ok"])
            self.assertTrue(result["checks"]["database"]["read"])
            self.assertFalse(result["checks"]["wal"]["read"])
            self.assertFalse(result["checks"]["wal"]["write"])
            self.assertIn("old.sqlite3", result["checks"]["backups"]["unreadable_entries"])
            for file in files:
                self.assertEqual(file.read_bytes(), b"synthetic-bytes")
            self.assertFalse(any(p.name.startswith(".escritura-preflight-") for p in path.rglob("*")))


class AppCheckProtocolTests(unittest.TestCase):
    def test_probe_uses_exact_image_user_without_root_override_or_added_capabilities(self):
        value = {"permissions_ok": False, "identity": {"uid": 10001, "gid": 10001}}
        with mock.patch.object(storage, "image_id", return_value="sha256:" + "a" * 64), \
                mock.patch.object(storage, "docker", return_value=json.dumps(value)) as docker:
            self.assertEqual(storage.probe_app_image("synthetic", "/stack/data/app"), value)
        command = docker.call_args.args
        self.assertNotIn("--user", command)
        self.assertNotIn("--cap-add", command)
        self.assertIn("--cap-drop", command)
        self.assertIn("sha256:" + "a" * 64, command)
        self.assertIn('_app_check', command)
        self.assertIn('def app_permissions(', docker.call_args.kwargs['stdin'])
        self.assertNotIn('/tool/storage.py', command)  # A private host script need not be readable by UID 10001.

    def test_permissions_success_is_not_started_or_recovery_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            compose = Path(temporary) / "compose.yaml"
            compose.write_text("synthetic")
            image = "sha256:" + "a" * 64
            state = {"Status": "exited", "Running": False, "Health": {"Status": "unhealthy"}}
            configured_user = ["10001:10001"]
            def docker(*args, **kwargs):
                if args[0] == "compose":
                    return json.dumps({"services": {"app": {"volumes": [{"type": "bind", "source": "/stack/data/app", "target": "/data"}]}}})
                if args[0] == "ps": return "container"
                if args[0] == "inspect":
                    return json.dumps([{"Image": image, "Config": {"User": configured_user[0]},
                                        "Mounts": [{"Type": "bind", "Source": "/stack/data/app", "Destination": "/data", "RW": True}], "State": state}])
                if args[0] == "image": return json.dumps([{"Id": image, "Os": "linux", "Config": {"User": "10001:10001"}}])
                if args[0] == "exec": return "ok"
                self.fail("Unexpected mutation")
            with mock.patch.object(storage, "docker", side_effect=docker), \
                    mock.patch.object(storage, "probe_app_image", return_value={"permissions_ok": True, "identity": {"uid": 10001, "gid": 10001}}):
                before = storage.check_app(compose, "synthetic")
                self.assertEqual(before["status"], "permissions_passed")
                self.assertFalse(before["health_checked"])
                self.assertFalse(before["recovery_complete"])
                self.assertEqual(storage.check_app(compose, "synthetic", True)["status"], "runtime_not_ready")
                state.update(Status="running", Running=True, Health={"Status": "healthy"})
                after = storage.check_app(compose, "synthetic", True)
                self.assertEqual(after["status"], "runtime_healthy")
                self.assertFalse(after["recovery_complete"])
                self.assertEqual(after["interface_validation"], "pending")
                configured_user[0] = "0:0"
                with self.assertRaisesRegex(storage.StorageError, "sobrescreve USER"):
                    storage.check_app(compose, "synthetic")


if __name__ == "__main__":
    unittest.main()
