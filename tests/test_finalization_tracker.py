import os
import sys
import time
import tempfile
import threading
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.ffmpeg.finalization_tracker import FinalizationTracker
from src.render_progress import RenderProgressTracker


class TestFinalizationTracker(unittest.TestCase):
    def test_stage_names_and_lifecycle(self):
        progress_calls = []
        def on_prog(percent, label):
            progress_calls.append((percent, label))

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.mp4")
            tracker = FinalizationTracker(
                output_paths=[test_file],
                on_progress=on_prog,
                poll_interval_s=0.05,
                stall_threshold_s=0.2,
            )

            # 1. Drain stage
            tracker.mark_drain_start(queued_count=10, frames_written=90, total_frames=100)
            self.assertEqual(tracker.stage, FinalizationTracker.STAGE_DRAIN)
            self.assertIn("opróżnianie klatek", tracker.current_stage_label())

            # 2. Update queue
            tracker.update_queue_status(pending=5, written=95, total_frames=100)
            self.assertEqual(tracker.queue_pending, 5)

            # 3. Writer done
            tracker.mark_writer_done()
            self.assertIsNotNone(tracker.t_writer_join_end)

            # 4. Encoder stage & stdin close
            tracker.set_stage(FinalizationTracker.STAGE_ENCODER)
            self.assertEqual(tracker.stage, FinalizationTracker.STAGE_ENCODER)
            self.assertIn("zamykanie enkodera", tracker.current_stage_label())
            tracker.mark_stdin_closed()
            self.assertIsNotNone(tracker.t_stdin_close_end)

            # 5. Mux stage
            tracker.mark_ffmpeg_wait_start()
            self.assertEqual(tracker.stage, FinalizationTracker.STAGE_MUX)
            self.assertIn("zapis MP4 / mux", tracker.current_stage_label())

            # 6. Simulate file writes to test MB/s
            tracker.start()
            with open(test_file, "wb") as f:
                f.write(b"0" * (1024 * 1024 * 5))  # 5 MB
            time.sleep(0.12)
            tracker.sample_now()

            state = tracker.get_state()
            self.assertGreaterEqual(state.bytes_written, 1024 * 1024 * 5)
            self.assertGreaterEqual(state.rolling_mb_s, 0.0)

            tracker.mark_ffmpeg_wait_end()

            # 7. Postprocess stage
            tracker.mark_postprocess_start()
            self.assertEqual(tracker.stage, FinalizationTracker.STAGE_POSTPROCESS)
            self.assertIn("postprocess", tracker.current_stage_label())
            tracker.mark_postprocess_end()

            tracker.stop()

            # Summary timings
            timings = tracker.get_timings()
            self.assertGreaterEqual(timings["finalize_total_ms"], 0.0)
            self.assertIn("queue_drain_ms", timings)
            self.assertIn("writer_join_ms", timings)
            self.assertIn("stdin_close_ms", timings)
            self.assertIn("ffmpeg_exit_wait_ms", timings)
            self.assertIn("postprocess_ms", timings)

    def test_stall_warning_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test_stall.mp4")
            # Create file
            with open(test_file, "wb") as f:
                f.write(b"0" * 1024)

            tracker = FinalizationTracker(
                output_paths=[test_file],
                stall_threshold_s=0.1,  # short for test
            )
            tracker.set_stage(FinalizationTracker.STAGE_MUX)
            tracker.sample_now()

            # Sleep longer than stall threshold without file size change
            time.sleep(0.15)
            tracker.sample_now()

            state = tracker.get_state()
            self.assertTrue(state.is_stalled)
            self.assertGreaterEqual(state.stall_sec, 0)

            formatted = tracker.format_gui_status()
            self.assertIn("brak przyrostu", formatted)

    def test_timer_increments_and_formatting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "timer_test.mp4")
            tracker = FinalizationTracker(output_paths=[test_file])
            status0 = tracker.format_gui_status()
            self.assertIn("00:00", status0)
            
            # Artificial sleep to advance timer
            time.sleep(1.05)
            status = tracker.format_gui_status()
            # Should show at least 00:01
            self.assertTrue("00:01" in status or "00:02" in status, f"Unexpected timer status: {status}")

    def test_drain_progress_calculation(self):
        emitted = []
        def on_prog(done, total, elapsed, fps, state):
            emitted.append(state)

        rpt = RenderProgressTracker(total_frames=100, callback=on_prog)
        tracker = FinalizationTracker()
        
        # 10 queued at start, 90 written out of 100 total
        tracker.mark_drain_start(queued_count=10, frames_written=90, total_frames=100)
        self.assertEqual(tracker.stage, FinalizationTracker.STAGE_DRAIN)
        self.assertAlmostEqual(tracker._drain_pct, 0.0, places=1)
        
        # Test RenderProgressTracker mapping for drain: 95..98%
        rpt._emit(phase="finalize", internal=0.0, label="Drain 0%", drain_pct=0.0)
        self.assertAlmostEqual(emitted[-1]["global_pct"], 95.0, places=1)

        # 5 remaining (half drained) -> drain_pct = 50% -> 96.5%
        tracker.set_stage(FinalizationTracker.STAGE_DRAIN, queue_size=5, frames_written=95, total_frames=100)
        self.assertAlmostEqual(tracker._drain_pct, 50.0, places=1)
        rpt._emit(phase="finalize", internal=0.5, label="Drain 50%", drain_pct=50.0)
        self.assertAlmostEqual(emitted[-1]["global_pct"], 96.5, places=1)

        # 0 remaining -> drain_pct = 100% -> 98.0%
        tracker.set_stage(FinalizationTracker.STAGE_DRAIN, queue_size=0, frames_written=100, total_frames=100)
        self.assertAlmostEqual(tracker._drain_pct, 100.0, places=1)
        rpt._emit(phase="finalize", internal=1.0, label="Drain 100%", drain_pct=100.0)
        self.assertAlmostEqual(emitted[-1]["global_pct"], 98.0, places=1)

        # Finished -> 100%
        rpt.complete(elapsed=10.0)
        self.assertAlmostEqual(emitted[-1]["global_pct"], 100.0, places=1)
        self.assertEqual(emitted[-1]["label"], "Zakończono")

    def test_file_growth_and_mbs_calculation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "growth_test.mp4")
            tracker = FinalizationTracker(output_paths=[test_file])
            tracker.sample_now()
            self.assertEqual(tracker.get_state().current_bytes, 0)

            # Write 2 MB
            with open(test_file, "wb") as f:
                f.write(b"X" * (2 * 1024 * 1024))
            
            time.sleep(0.1)
            tracker.sample_now()
            state = tracker.get_state()
            self.assertEqual(state.current_bytes, 2 * 1024 * 1024)
            self.assertEqual(state.bytes_written, 2 * 1024 * 1024)
            self.assertGreater(state.rolling_mb_s, 0.0)
            
            # Status during MUX stage should include size and speed
            tracker.set_stage(FinalizationTracker.STAGE_MUX)
            status = tracker.format_gui_status()
            self.assertIn("Finalizacja: zapis MP4", status)
            self.assertIn("GB", status)
            self.assertIn("MB/s", status)

    def test_cancel_during_finalization_is_non_blocking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "cancel_test.mp4")
            tracker = FinalizationTracker(output_paths=[test_file], poll_interval_s=0.05)
            tracker.start()
            self.assertTrue(tracker._monitor_thread.is_alive())

            # Simulate cancel calling stop()
            t0 = time.perf_counter()
            tracker.stop()
            elapsed = time.perf_counter() - t0

            # Stop must join bounded and fast (< 0.2s)
            self.assertFalse(tracker._monitor_thread.is_alive())
            self.assertLess(elapsed, 0.2)


if __name__ == "__main__":
    unittest.main()

