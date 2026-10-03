"""One bounded, deduplicated worker for interactive map viewport requests."""
from collections import OrderedDict
import threading
import time


class PreviewViewportPrefetch:
    def __init__(self, retry_delay=10.0):
        self._condition = threading.Condition()
        self._pending = OrderedDict()
        self._active = None
        self._recent = OrderedDict()
        self._thread = None
        self._revision = 0
        self._retry_delay = retry_delay
        self.threads_started = 0

    @property
    def revision(self):
        with self._condition:
            return self._revision

    def schedule(self, key, task):
        with self._condition:
            if key == self._active or key in self._pending:
                return False
            if time.monotonic() - self._recent.get(key, float("-inf")) < self._retry_delay:
                return False
            self._pending[key] = task
            while len(self._pending) > 8:
                self._pending.popitem(last=False)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="TeleM-PreviewTiles", daemon=True)
                self.threads_started += 1
                self._thread.start()
            self._condition.notify()
            return True

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: bool(self._pending))
                key, task = self._pending.popitem(last=True)
                self._active = key
            try:
                task()
            except Exception:
                pass  # Preview retains its route and marker while offline.
            finally:
                with self._condition:
                    self._revision += 1
                    self._recent[key] = time.monotonic()
                    while len(self._recent) > 128:
                        self._recent.popitem(last=False)
                    self._active = None


preview_viewport_prefetch = PreviewViewportPrefetch()
