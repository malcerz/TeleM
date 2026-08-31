from src.load_progress import LoadProgressTracker


def test_load_progress_is_monotonic_and_weighted():
    events = []
    tracker = LoadProgressTracker(lambda pct, text: events.append((pct, text)))

    tracker.fixed(45, "GPMF: metadata")
    tracker.update("track_extract", 1, 10, "GPMF: GPS/track")
    tracker.update("track_extract", 10, 10, "GPMF: GPS/track")
    tracker.update("iso_extract", 1, 10, "GPMF: ISO")
    tracker.finish("iso_extract", "GPMF: ISO")

    values = [pct for pct, _ in events]
    assert values == sorted(values)
    assert values[-1] > 45
    assert any("GPS/track" in text for _, text in events)
    assert any("ISO" in text for _, text in events)

