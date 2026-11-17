"""Own a disposable preview server inside its data/log directory lifetime."""
from contextlib import contextmanager
import subprocess


@contextmanager
def managed_process(*args, **kwargs):
    process = subprocess.Popen(*args, **kwargs)
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            # Reap before the caller removes data. Forced shutdown still fails
            # the acceptance run: it is not a successful cleanup or a retry.
            process.kill()
            process.wait(timeout=15)
            raise
