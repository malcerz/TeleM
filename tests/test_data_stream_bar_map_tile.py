"""Regression: the "Mapa" tile must keep its compact flow-layout size after the
indicator tiles are rebuilt while the bar is visible (e.g. "Wczytaj preset")."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui.qt.models import DataStream  # noqa: E402
from src.gui.qt.widgets.data_stream_bar import DataStreamBar  # noqa: E402


def _streams():
    s = [DataStream(key=f"g{i}", display_name=f"GPMF {i}", source="gpmf", category="camera") for i in range(8)]
    s += [DataStream(key=f"f{i}", display_name=f"Garmin field {i} (FIT)", source="fit", category="sensor")
          for i in range(6)]
    s.append(DataStream(key="track_map", display_name="Mapa", source="gpmf", category="gps", suggested_form="map"))
    return s


def _settle(app):
    for _ in range(5):
        app.processEvents()


def test_map_tile_stays_compact_after_rebuild_while_visible():
    app = QApplication.instance() or QApplication([])
    bar = DataStreamBar()
    bar.resize(1300, 400)
    bar.show()
    bar.on_streams_ready(_streams())
    _settle(app)
    first = bar._buttons["track_map"].geometry()
    for _ in range(2):                        # preset loaded twice while the bar is visible
        bar.on_streams_ready(_streams())
        _settle(app)
    bar.resize(900, 400)
    _settle(app)
    btn = bar._buttons["track_map"]
    g = btn.geometry()
    others = [b.geometry() for k, b in bar._buttons.items() if k != "track_map"]
    assert g.height() == max(btn.sizeHint().height(), btn.minimumHeight())      # what the flow layout assigns
    assert (g.width(), g.height()) == (first.width(), first.height())
    assert g.height() <= max(o.height() for o in others)       # no uncontrolled stretch (was 640x480)
    assert g.width() < 200
    bar.close()
