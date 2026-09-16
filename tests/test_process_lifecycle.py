"""Unit tests for process lifecycle, Job Object guard, and process registry."""

import os
import sys
import time
import subprocess
import unittest

from src.process_lifecycle import RenderJobGuard, RenderProcessRegistry, _IS_WINDOWS


class TestProcessLifecycle(unittest.TestCase):
    def test_job_guard_singleton(self):
        guard1 = RenderJobGuard.get_instance()
        guard2 = RenderJobGuard.get_instance()
        self.assertIs(guard1, guard2)
        if _IS_WINDOWS:
            self.assertIsNotNone(guard1.job_handle)

    def test_registry_registration_and_termination(self):
        registry = RenderProcessRegistry.get_instance()

        # Spawn a dummy child process that sleeps
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
        )
        pid = proc.pid
        try:
            registered_pid = registry.register(proc, proc_type="test_worker")
            self.assertEqual(registered_pid, pid)
            self.assertIn(pid, registry.get_active_pids())

            # Verify termination via registry
            registry.terminate_all_render_children(timeout=2.0)
            self.assertNotIn(pid, registry.get_active_pids())

            # Process should be terminated
            proc.wait(timeout=2.0)
            self.assertIsNotNone(proc.poll())
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_registry_unregister(self):
        registry = RenderProcessRegistry.get_instance()
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(1)"],
        )
        pid = proc.pid
        try:
            registry.register(proc, proc_type="test_worker")
            self.assertIn(pid, registry.get_active_pids())
            registry.unregister(pid)
            self.assertNotIn(pid, registry.get_active_pids())
        finally:
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    unittest.main()
