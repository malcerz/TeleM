"""Tests for the widget classes (NumericRow, BoolRow, ChoiceRow, etc.)."""

from __future__ import annotations

from src.gui.widgets import (
    FIELD_LABELS,
    BoolRow,
    ChoiceRow,
    ColorRow,
    NumericRow,
    ScrollableFrame,
    TextRow,
)

# ── Module-level tests ──────────────────────────────────────────────────────


class TestFieldLabels:
    """Tests for the FIELD_LABELS dictionary."""

    def test_required_keys(self) -> None:
        """FIELD_LABELS should contain all keys used by widgets."""
        required = [
            "enabled",
            "label",
            "x",
            "y",
            "rotation",
            "font_size",
            "size",
            "thickness",
            "min_val",
            "max_val",
            "source",
            "text",
            "color",
        ]
        for key in required:
            assert key in FIELD_LABELS, f"Missing FIELD_LABELS key: {key}"

    def test_english_values(self) -> None:
        """Labels should be in English."""
        assert FIELD_LABELS["enabled"] == "enabled"
        assert FIELD_LABELS["color"] == "text colour"
        assert FIELD_LABELS["size"] == "size"


# ── Widget construction tests (no Tkinter root needed for static checks) ────


class TestNumericRow:
    """Static tests for NumericRow (construction not tested without Tk root)."""

    def test_class_attributes(self) -> None:
        """NumericRow should have expected methods."""
        attrs = ["format_value", "clamp", "get", "on_scale", "on_entry"]
        for attr in attrs:
            assert hasattr(NumericRow, attr), f"Missing NumericRow.{attr}"

    def test_format_value_int(self) -> None:
        """format_value with is_int=True should return integer string."""
        row = object.__new__(NumericRow)
        row.is_int = True
        row.step = 1
        assert NumericRow.format_value(row, 42.7) == "43"

    def test_format_value_float(self) -> None:
        """format_value with is_int=False should return decimal string."""
        row = object.__new__(NumericRow)
        row.is_int = False
        row.step = 0.001
        assert NumericRow.format_value(row, 0.5) == "0.5"

    def test_clamp(self) -> None:
        """clamp should restrict values to [mn, mx]."""
        row = object.__new__(NumericRow)
        row.mn, row.mx = 0, 10
        assert NumericRow.clamp(row, 5) == 5
        assert NumericRow.clamp(row, -5) == 0
        assert NumericRow.clamp(row, 15) == 10


class TestBoolRow:
    """Static tests for BoolRow."""

    def test_class_attributes(self) -> None:
        assert hasattr(BoolRow, "get")


class TestChoiceRow:
    """Static tests for ChoiceRow."""

    def test_class_attributes(self) -> None:
        assert hasattr(ChoiceRow, "get")

    def test_get_int(self) -> None:
        """get() should return int when possible."""
        row = object.__new__(ChoiceRow)
        row.var = _StringVarMock("42")
        assert ChoiceRow.get(row) == 42

    def test_get_str(self) -> None:
        """get() should return str when not an int."""
        row = object.__new__(ChoiceRow)
        row.var = _StringVarMock("gpmf")
        assert ChoiceRow.get(row) == "gpmf"


class TestTextRow:
    """Static tests for TextRow."""

    def test_class_attributes(self) -> None:
        assert hasattr(TextRow, "get")


class TestColorRow:
    """Static tests for ColorRow."""

    def test_class_attributes(self) -> None:
        assert hasattr(ColorRow, "get")

    def test_get_ensures_hash(self) -> None:
        """get() should ensure the value starts with #."""
        row = object.__new__(ColorRow)
        row.var = _StringVarMock("FF3232")
        assert ColorRow.get(row) == "#FF3232"

    def test_get_with_hash(self) -> None:
        """get() should keep value with #."""
        row = object.__new__(ColorRow)
        row.var = _StringVarMock("#FF3232")
        assert ColorRow.get(row) == "#FF3232"


class TestScrollableFrame:
    """Static tests for ScrollableFrame."""

    def test_class_attributes(self) -> None:
        attrs = ["_on_frame_configure", "_on_canvas_configure"]
        for attr in attrs:
            assert hasattr(ScrollableFrame, attr)


# ── Helper mocks ────────────────────────────────────────────────────────────


class _StringVarMock:
    """Minimal mock for tk.StringVar used in static tests."""

    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value
