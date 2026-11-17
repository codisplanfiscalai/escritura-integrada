# Single Compose deployment and persistent A1 vault

Root, production and develop Compose templates now include the private,
project-scoped reception_vault volume. Its logical name and target are unchanged
from the legacy optional override, so the same project reuses the existing key.
The application remains UID 10001 with read-only root. No key rotation, reset,
credential read-back, migration of key bytes or fallback was added.

New deploy ZIPs contain one compose.yaml. Release/offline pins use image variables
in .env and --pull never for offline startup. Migration plans retain installed
image IDs in JSON instead of generating another Compose. Legacy plans retain
lock validation. Existing vault mounts are verified and preserved, not copied.

Validation on develop c0b9784 (dev.57):
- 41 vault/persistence/probe/infrastructure cases: 40 passed, 1 platform skip.
- 39 deployment-storage tests passed.
- Template synchronizer --check: no changes. Syntax and diff-check passed.
- Process restart, missing/wrong keys, rollback, recovery and identity preservation
  use synthetic fixtures. Real Docker daemon/CLI unavailable locally; required CI
  container recreation and storage smoke remain to be run. No production deploy.

Before replacing an existing Compose, preserve project name, .env and storage.
A key in a custom/ephemeral location requires explicit protected migration before
container recreation. An absent old key remains a closed failure, never a new key.
