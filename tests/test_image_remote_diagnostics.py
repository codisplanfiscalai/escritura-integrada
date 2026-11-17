"""Synthetic read-only registry command failures; no Docker, network or publish."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_images as images


REF = 'ghcr.io/codisplanfiscalai/escritura-integrada-minio:synthetic-test'


def result(code=0, out='', error=''):
    return subprocess.CompletedProcess(['synthetic-read-only-inspect'], code, out, error)


class RemoteDiagnosticsTests(unittest.TestCase):
    def test_reported_categories_and_stages_are_evidence_not_recovery(self):
        examples = [('HTTP 401 Unauthorized', 'authorization-reported', ['401']),
                    ('HTTP/1.1 403 Forbidden', 'authorization-reported', ['403']),
                    ('unexpected status code: 429 Too Many Requests', 'rate-limit-reported', ['429']),
                    ('HTTP 503 Service Unavailable', 'server-error-reported', ['503']),
                    ('net/http: TLS handshake timeout', 'transport-reported', []),
                    ('manifest unknown', 'not-found-reported', []),
                    ('unexpected response', 'unclassified', [])]
        for output, category, statuses in examples:
            with self.subTest(output=output):
                diagnostic = json.loads(images.remote_failure_diagnostic('resolve-manifest', result(1, error=output)))
                self.assertEqual(category, diagnostic['category'])
                self.assertEqual(statuses, diagnostic['reported_http_statuses'])
                self.assertEqual('resolve-manifest', diagnostic['stage'])
                self.assertEqual(1, diagnostic['returncode'])
                self.assertEqual(hashlib.sha256(('\n' + output).encode()).hexdigest(), diagnostic['output_sha256'])

    def test_no_stdout_stderr_credentials_paths_or_control_bytes_are_logged(self):
        secrets = ['synthetic-private-password', 'synthetic-private-token', 'private-user', '/private/example']
        output = 'HTTP 401 Unauthorized\x1b[31m\nAuthorization: Bearer ' + secrets[1] + '\n' + ' '.join(secrets)
        diagnostic = images.remote_failure_diagnostic('resolve-manifest', result(1, out=output, error=output))
        for value in secrets + ['Authorization', '\x1b', 'Bearer']:
            self.assertNotIn(value, diagnostic)
        self.assertLess(len(diagnostic), 400)

    def test_classification_is_bounded_but_digest_identifies_whole_output(self):
        a = result(1, out='x' * 16384, error='HTTP 401 Unauthorized')
        b = result(1, out='x' * 16384, error='HTTP 503 Service Unavailable')
        da = json.loads(images.remote_failure_diagnostic('resolve-manifest', a))
        db = json.loads(images.remote_failure_diagnostic('resolve-manifest', b))
        self.assertEqual('unclassified', da['category'])
        self.assertNotEqual(da['output_sha256'], db['output_sha256'])

    def test_immutable_probe_unknown_errors_fail_closed_once(self):
        for output in ['HTTP 401 Unauthorized', 'HTTP 503 Unavailable', 'TLS handshake timeout', 'unknown failure']:
            with self.subTest(output=output), patch.object(images, 'run', return_value=result(1, error=output)) as run:
                with self.assertRaisesRegex(RuntimeError, 'check-immutable-tag'):
                    images.remote_exists(REF)
                self.assertEqual(1, run.call_count)
                self.assertEqual(['docker', 'manifest', 'inspect', REF], run.call_args.args[0])

    def test_existing_and_missing_probe_behavior_is_preserved(self):
        with patch.object(images, 'run', return_value=result(0)):
            self.assertTrue(images.remote_exists(REF))
        with patch.object(images, 'run', return_value=result(1, error='manifest unknown')):
            self.assertFalse(images.remote_exists(REF))

    def test_required_manifest_failure_has_diagnostic_no_retry_or_write(self):
        with patch.object(images, 'run', return_value=result(1, error='HTTP 503 Unavailable')) as run:
            with self.assertRaisesRegex(RuntimeError, 'resolve-manifest'):
                images.pinned_remote(REF)
            self.assertEqual(1, run.call_count)
            self.assertEqual(['docker', 'buildx', 'imagetools', 'inspect', '--raw', REF], run.call_args.args[0])

    def test_optional_cache_failure_preserves_non_attestation(self):
        with patch.object(images, 'run', return_value=result(1, error='synthetic-private-token')) as run, redirect_stdout(io.StringIO()) as out:
            self.assertIsNone(images.pinned_remote(REF, optional=True))
            self.assertNotIn('synthetic-private-token', out.getvalue())
            self.assertEqual(1, run.call_count)

    def test_descriptor_failure_stays_closed_with_specific_stage(self):
        manifest = json.dumps({'mediaType': 'application/vnd.oci.image.manifest.v1+json'})
        with patch.object(images, 'run', side_effect=[result(out=manifest), result(1, error='HTTP 403 Forbidden')]) as run:
            with self.assertRaisesRegex(RuntimeError, 'resolve-descriptor'):
                images.pinned_remote(REF)
            self.assertEqual(2, run.call_count)
            self.assertTrue(all(call.args[0][:4] == ['docker', 'buildx', 'imagetools', 'inspect'] for call in run.call_args_list))

    def test_valid_digest_and_original_bytes_are_preserved(self):
        for ending in ['', '\n']:
            raw = json.dumps({'mediaType': 'application/vnd.oci.image.manifest.v1+json'}) + ending
            digest = 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()
            with self.subTest(ending=ending), patch.object(images, 'run', side_effect=[result(out=raw), result(out=json.dumps({'digest': digest}))]) as run:
                self.assertEqual(digest, images.pinned_remote(REF))
                self.assertEqual(2, run.call_count)

    def test_malformed_index_and_changed_digest_never_return_pinned_reference(self):
        for raw in ['not-json', json.dumps({'mediaType': 'application/vnd.oci.image.index.v1+json'}), json.dumps({'mediaType': 'application/vnd.oci.image.manifest.v1+json'})]:
            with self.subTest(raw=raw), patch.object(images, 'run', side_effect=[result(out=raw), result(out=json.dumps({'digest': 'sha256:' + 'f' * 64}))]) as run:
                with self.assertRaises(ValueError):
                    images.pinned_remote(REF)
                self.assertLessEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
