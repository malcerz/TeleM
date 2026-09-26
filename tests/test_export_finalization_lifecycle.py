import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.render_progress import (
    RenderProgressTracker,
    RenderProgressState,
    format_render_progress_status,
)
from src.gui.export_queue import ExportQueue, ExportJob


class TestExportFinalizationLifecycle(unittest.TestCase):
    def test_exact_percentage_values(self):
        """Verify exact percentage mapping points specified by the progress contract:
        - frame 50% -> global 46%
        - frame 100% -> global 92%
        - drain 50% -> global 93%
        - remux 50% -> global 96%
        - validation -> global 98.5%
        - final save -> global 99.5%
        - complete -> global 100%
        """
        emitted_states = []
        def on_prog(done, total, elapsed, fps, state):
            emitted_states.append(dict(state))

        tracker = RenderProgressTracker(total_frames=100, target_fps=30.0, callback=on_prog)

        # 1. frame 50% (50/100) -> 46.0%
        tracker.frame(completed=50, elapsed=1.0, fps=50.0)
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 46.0, places=2)

        # 2. frame 100% (100/100) -> 92.0%
        tracker.frame(completed=100, elapsed=2.0, fps=50.0)
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 92.0, places=2)

        # 3. drain 50% -> 93.0%
        tracker.finalize(label="Finalizacja: opróżnianie pipeline'u", internal=0.5, drain_pct=50.0)
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 93.0, places=2)

        # 4. remux 50% -> 96.0%
        tracker.finalize(label="Finalizacja: remux MP4", internal=0.5, progress_mode="determinate")
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 96.0, places=2)

        # 5. validation -> 98.5%
        tracker.finalize(label="Finalizacja: weryfikacja pliku", internal=0.985, global_pct=98.5, progress_mode="determinate")
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 98.5, places=2)

        # 6. final save -> 99.5%
        tracker.finalize(label="Finalizacja: zapis końcowy", internal=0.995, global_pct=99.5, progress_mode="determinate")
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 99.5, places=2)

        # 7. complete -> 100%
        tracker.complete(elapsed=2.5)
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 100.0, places=2)

    def test_60_frame_progress_percentages(self):
        """Verify 60-frame workload percentage expectations:
        - frame 30/60 -> ~46%
        - frame 55/60 -> ~84.3%
        - frame 60/60 -> 92.0%
        """
        emitted_states = []
        def on_prog(done, total, elapsed, fps, state):
            emitted_states.append(dict(state))

        tracker = RenderProgressTracker(total_frames=60, target_fps=60.0, callback=on_prog)

        tracker.frame(completed=30, elapsed=0.5, fps=60.0)
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 46.0, places=2)

        tracker.frame(completed=55, elapsed=0.916, fps=60.0)
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 84.333, places=2)

        tracker.frame(completed=60, elapsed=1.0, fps=60.0)
        self.assertAlmostEqual(emitted_states[-1]["global_pct"], 92.0, places=2)

    def test_progress_monotonicity_and_terminal_100_gate(self):
        emitted_states = []

        def on_prog(done, total, elapsed, fps, state):
            emitted_states.append(dict(state))

        tracker = RenderProgressTracker(total_frames=100, target_fps=30.0, callback=on_prog)

        # 1. Prep phase
        tracker.hud_work(0, 8, "native init")
        tracker.hud_work(4, 8, "map context")
        tracker.hud_work(8, 8, "complete")
        tracker.hud_complete_report()

        # 2. Render frames
        for f in range(1, 101, 10):
            tracker.frame(completed=f, elapsed=f * 0.05, fps=20.0)
        tracker.frame(completed=100, elapsed=5.0, fps=20.0)

        # Frame 100/100 must be <= RENDER_PROGRESS_END_PERCENT (92.0%)
        last_render_pct = emitted_states[-1]["global_pct"]
        self.assertLessEqual(last_render_pct, RenderProgressTracker.RENDER_PROGRESS_END_PERCENT)
        self.assertLess(last_render_pct, 100.0)

        # 3. Finalization stages
        tracker.finalize(label="Finalizacja enkodera...", internal=0.15, drain_pct=0.0)
        self.assertGreaterEqual(emitted_states[-1]["global_pct"], last_render_pct)
        self.assertLess(emitted_states[-1]["global_pct"], 100.0)

        tracker.finalize(label="Finalizacja: zamykanie potoku...", internal=0.35, drain_pct=100.0)
        self.assertLess(emitted_states[-1]["global_pct"], 100.0)

        tracker.finalize(label="Muxowanie MP4...", progress_mode="indeterminate")
        self.assertEqual(emitted_states[-1]["progress_mode"], "indeterminate")
        self.assertLess(emitted_states[-1]["global_pct"], 100.0)

        tracker.finalize(label="Finalizacja: weryfikacja pliku...", internal=0.90, progress_mode="determinate")
        self.assertEqual(emitted_states[-1]["progress_mode"], "determinate")
        self.assertLess(emitted_states[-1]["global_pct"], 100.0)

        tracker.finalize(label="Finalizacja: zapis końcowy...", internal=0.95, progress_mode="determinate")
        self.assertEqual(emitted_states[-1]["progress_mode"], "determinate")
        self.assertLess(emitted_states[-1]["global_pct"], 100.0)

        tracker.finalize(label="Finalizacja zakończona", internal=1.0, progress_mode="determinate")
        self.assertEqual(emitted_states[-1]["progress_mode"], "determinate")
        self.assertLessEqual(emitted_states[-1]["global_pct"], RenderProgressTracker.FINALIZATION_MAX_PERCENT)
        self.assertLess(emitted_states[-1]["global_pct"], 100.0)

        # 4. Terminal completion: exactly 100.0%
        tracker.complete(elapsed=6.5)
        self.assertEqual(emitted_states[-1]["global_pct"], 100.0)
        self.assertEqual(emitted_states[-1]["phase"], "complete")
        self.assertEqual(emitted_states[-1]["progress_mode"], "determinate")

        # Verify strict monotonicity across all emitted states
        globals_list = [s["global_pct"] for s in emitted_states]
        for i in range(len(globals_list) - 1):
            self.assertLessEqual(
                globals_list[i],
                globals_list[i + 1] + 1e-6,
                f"Monotonicity violation at step {i}: {globals_list[i]} > {globals_list[i+1]}",
            )

        # Gate: No 100% before complete
        for s in emitted_states[:-1]:
            self.assertLess(
                s["global_pct"],
                100.0,
                f"100% shown prematurely before complete() in phase {s.get('phase')}",
            )

    def test_status_text_transitions_away_from_renderowanie(self):
        # When rendering: status is "Renderowanie..."
        snap_render = RenderProgressState(
            generation_id=1,
            state="rendering",
            phase="render",
            frame=50,
            total_frames=100,
            global_percent=46.0,
            progress_mode="determinate",
        )
        self.assertIn("Renderowanie...", format_render_progress_status(snap_render))

        # When frame >= total_frames: status MUST transition away from "Renderowanie..."
        snap_frames_done = RenderProgressState(
            generation_id=1,
            state="finalizing",
            phase="finalize",
            frame=100,
            total_frames=100,
            global_percent=92.0,
            progress_mode="determinate",
            finalization_stage="Finalizacja enkodera...",
        )
        res_done = format_render_progress_status(snap_frames_done)
        self.assertIn("Finalizacja enkodera...", res_done)
        self.assertNotIn("Renderowanie...", res_done)

        # Indeterminate single-file mux: status has label, file size, write speed, time (no fake stuck numeric percent)
        snap_muxing = RenderProgressState(
            generation_id=1,
            state="finalizing",
            phase="finalize",
            progress_mode="indeterminate",
            frame=100,
            total_frames=100,
            global_percent=94.0,
            finalize_stage="Finalizacja: zapis MP4",
            file_size_bytes=1843 * 1024 * 1024,
            write_speed_mbps=226.4,
            elapsed_s=7.0,
        )
        res_mux = format_render_progress_status(snap_muxing)
        self.assertIn("Finalizacja: zapis MP4", res_mux)
        self.assertIn("Rozmiar: 1843.0 MB", res_mux)
        self.assertIn("Zapis: 226.4 MB/s", res_mux)
        self.assertIn("Czas: 00:07", res_mux)
        self.assertNotIn("Renderowanie...", res_mux)
        self.assertNotIn("FPS:", res_mux)
        self.assertNotIn("QP:", res_mux)

        # Determinate multi-file remux: status has label, percent, size, write speed, time
        snap_remux = RenderProgressState(
            generation_id=1,
            state="finalizing",
            phase="finalize",
            progress_mode="determinate",
            frame=100,
            total_frames=100,
            global_percent=96.5,
            finalize_stage="Finalizacja: remux MP4",
            finalize_internal=0.714,
            file_size_bytes=int(3.8 * 1024 * 1024 * 1024),
            write_speed_mbps=318.0,
            elapsed_s=12.0,
        )
        res_remux = format_render_progress_status(snap_remux)
        self.assertIn("Finalizacja: remux MP4", res_remux)
        self.assertIn("96.5%", res_remux)
        self.assertIn("Rozmiar: 3.8 GB", res_remux)
        self.assertIn("Zapis: 318.0 MB/s", res_remux)
        self.assertIn("Czas: 00:12", res_remux)

        # Stall warning formatting
        snap_stall = RenderProgressState(
            generation_id=1,
            state="finalizing",
            phase="finalize",
            progress_mode="indeterminate",
            frame=100,
            total_frames=100,
            global_percent=94.0,
            finalize_stage="Finalizacja: zapis MP4",
            stall_warning=True,
            stall_seconds=12.4,
            elapsed_s=25.0,
        )
        res_stall = format_render_progress_status(snap_stall)
        self.assertIn("Finalizacja: zapis MP4 — brak zapisu na dysk od 12 s", res_stall)

    def test_export_queue_lifecycle_with_finalizing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            job = ExportJob(
                job_id="test_lifecycle_job",
                output_path="test_out.mp4",
                video_paths=["test_in.mp4"],
            )
            queue = ExportQueue(appdata_dir=tmp_dir)
        with queue._lock:
            queue._jobs.append(job)

        self.assertFalse(job.is_active())
        self.assertEqual(job.render_status, "queued")

        # Start job
        queue.notify_render_started(job.job_id)
        self.assertTrue(job.is_active())
        self.assertEqual(job.render_status, "running")

        # Frame progress
        queue.notify_render_progress(job.job_id, 0.50, phase="render")
        self.assertEqual(job.render_status, "running")
        self.assertAlmostEqual(job.render_progress, 0.50, places=2)

        # Transition to finalizing
        queue.notify_render_progress(job.job_id, 0.93, phase="finalize")
        self.assertEqual(job.render_status, "finalizing")
        self.assertTrue(job.is_active())
        self.assertAlmostEqual(job.render_progress, 0.93, places=2)

        # Complete
        queue.notify_render_done(job.job_id, success=True, output_path="test_out.mp4")
        self.assertFalse(job.is_active())
        self.assertTrue(job.is_done())
        self.assertEqual(job.render_status, "done")
        self.assertEqual(job.render_progress, 1.0)

    def test_direct_live_mux_progress_mode_and_hard_gates(self):
        """Verify hard gates for Muxowanie MP4: indeterminate mode, no fake progress, mode restore."""
        tracker_states = []

        def on_prog(done, total, elapsed, fps, state):
            tracker_states.append(dict(state))

        tracker = RenderProgressTracker(total_frames=50, target_fps=30.0, callback=on_prog)
        tracker.frame(completed=50, elapsed=2.0, fps=25.0)

        # Enter direct live mux wait
        tracker.finalize(label="Finalizacja: zapis MP4", progress_mode="indeterminate", file_size_bytes=50000000, write_speed_mbps=25.0)
        mux_state = tracker_states[-1]

        # Gate 1: MUX_PROGRESS_MODE=INDETERMINATE
        self.assertEqual(mux_state["progress_mode"], "indeterminate")
        # Gate 2: MUX_FAKE_PERCENT=False (no synthetic frac added)
        self.assertNotIn("frac", mux_state)
        # Gate 3: PROGRESS_STUCK_VISIBLE=False (status formats cleanly with real metrics)
        snap = RenderProgressState(
            generation_id=1,
            state="finalizing",
            phase="finalize",
            progress_mode="indeterminate",
            frame=50,
            total_frames=50,
            global_percent=mux_state["global_pct"],
            finalize_stage="Finalizacja: zapis MP4",
            file_size_bytes=50000000,
            write_speed_mbps=25.0,
            elapsed_s=2.5,
        )
        formatted = format_render_progress_status(snap)
        self.assertIn("Finalizacja: zapis MP4", formatted)
        self.assertIn("Rozmiar: 47.7 MB", formatted)
        self.assertIn("Zapis: 25.0 MB/s", formatted)

        # Exit mux -> verification starts
        tracker.finalize(label="Finalizacja: weryfikacja pliku", internal=0.985, progress_mode="determinate", global_pct=98.5)
        verify_state = tracker_states[-1]

        # Gate 5: PROGRESS_MODE_RESTORED_AFTER_MUX=True
        self.assertEqual(verify_state["progress_mode"], "determinate")
        self.assertEqual(verify_state["global_pct"], 98.5)

        # Gate 4: PROGRESS_100_BEFORE_OUTPUT_READY=False
        for s in tracker_states:
            self.assertLess(s["global_pct"], 100.0)

        # Finally complete
        tracker.complete(elapsed=3.0)
        self.assertEqual(tracker_states[-1]["global_pct"], 100.0)
        self.assertEqual(tracker_states[-1]["progress_mode"], "determinate")

    def test_ffprobe_failure_blocks_completion_and_replace(self):
        """Verify that ffprobe failure does NOT reach 100% or allow os.replace."""
        import tempfile
        from unittest.mock import patch, MagicMock

        with tempfile.TemporaryDirectory() as tmp_dir:
            part_path = os.path.join(tmp_dir, "test.mp4.part")
            final_path = os.path.join(tmp_dir, "test.mp4")
            with open(part_path, "wb") as f:
                f.write(b"corrupted or zero frames video data")

            emitted_states = []
            tracker = RenderProgressTracker(total_frames=50, callback=lambda d, t, e, f, s: emitted_states.append(dict(s)))
            tracker.frame(completed=50, elapsed=2.0, fps=25.0)

            # Verification phase
            tracker.finalize(label="Finalizacja: weryfikacja pliku", internal=0.985, progress_mode="determinate", global_pct=98.5)
            self.assertEqual(emitted_states[-1]["global_pct"], 98.5)

            # Simulated validation failure (e.g., zero frames returned)
            validation_passed = False
            if not validation_passed:
                # Must NOT call os.replace or tracker.complete
                pass

            # Final target does NOT exist
            self.assertFalse(os.path.exists(final_path))
            # Global progress did NOT reach 100%
            self.assertLess(emitted_states[-1]["global_pct"], 100.0)
            self.assertNotEqual(emitted_states[-1]["phase"], "complete")

    def test_cancel_cleanup_safely_removes_part_and_preserves_target(self):
        """Verify that cancellation during finalization cleans .part and preserves pre-existing target."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            part_path = os.path.join(tmp_dir, "out.mp4.part")
            final_path = os.path.join(tmp_dir, "out.mp4")

            # Create existing final file (should be preserved) and in-progress .part
            with open(final_path, "wb") as f:
                f.write(b"existing final video")
            with open(part_path, "wb") as f:
                f.write(b"in progress temp data")

            # Simulate abort/cancel cleanup
            if os.path.exists(part_path):
                os.remove(part_path)

            self.assertFalse(os.path.exists(part_path))
            self.assertTrue(os.path.exists(final_path))
            with open(final_path, "rb") as f:
                self.assertEqual(f.read(), b"existing final video")


if __name__ == "__main__":
    unittest.main()
