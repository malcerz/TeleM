"""Centralne definicje sygnałów Qt dla komunikacji GUI ↔ kontroler.

GUI NIE zawiera logiki biznesowej — jedynie emituje sygnały i reaguje na sygnały
zwrotne z kontrolera.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    """Wszystkie sygnały aplikacji w jednym miejscu."""

    # ── GUI → Kontroler ──────────────────────────────────────────────────

    # Zakładka Wczytywanie: użytkownik wybrał pliki
    sig_files_selected = Signal(list, str, str)
    # (video_paths: list[str], gpx_path: str, fit_path: str)

    # Zakładka Projekt: kliknięto przycisk strumienia danych
    sig_stream_clicked = Signal(str)
    # (stream_key: str)

    # Zakładka Projekt: reset układu (usuń wszystkie wskaźniki)
    sig_reset_layout = Signal()

    # Zakładka Projekt: zapisz / wczytaj preset układu
    sig_save_preset = Signal()
    sig_load_preset = Signal()

    # Zakładka Projekt: zmieniono właściwość wskaźnika
    sig_property_changed = Signal(str, str, object)
    # (stream_key: str, field_name: str, value: Any)

    # Zakładka Projekt: usuń wskaźnik
    sig_delete_indicator = Signal(str)
    # (stream_key: str)

    # Zakładka Rendering: żądanie eksportu
    sig_render_requested = Signal(dict)
    # (render_options: dict)

    # Zakładka Rendering: anulowanie renderowania
    sig_render_cancelled = Signal()

    # Zakładka Ustawienia: zmiana ustawień
    sig_settings_changed = Signal(str, object)
    # (setting_name: str, value: Any)

    # Oś czasu: zmiana pozycji seek
    sig_seek_changed = Signal(float)
    # (seconds: float)

    # Playback: start / stop
    sig_playback_start = Signal()
    sig_playback_stop = Signal()

    # ── Kontroler → GUI ──────────────────────────────────────────────────

    # Dostępne strumienie danych po analizie
    sig_data_streams_ready = Signal(list)
    # (streams: list[DataStream])

    # Schemat i wartości właściwości dla wybranego wskaźnika
    sig_properties_ready = Signal(str, list, dict)
    # (stream_key: str, schema: list[FieldSchema], values: dict)

    # Nowa klatka podglądu gotowa
    sig_preview_frame_ready = Signal(object)
    # (qpixmap: QPixmap)

    # Aktualizacja czasu trwania wideo (do suwaka)
    sig_video_duration_ready = Signal(float)
    # (duration_seconds: float)

    # Aktualizacja informacji o wideo
    sig_video_info_ready = Signal(str)
    # (info_text: str)

    # Ramki bounding boxów wskaźników (do wykrywania kliknięć na podglądzie)
    sig_bboxes_ready = Signal(dict, int, int)
    # (bboxes: dict, orig_w: int, orig_h: int)

    # Kliknięcie / przeciągnięcie wskaźnika na podglądzie
    sig_indicator_clicked = Signal(str)
    # (stream_key: str)
    sig_indicator_moved = Signal(str, float, float)
    # (stream_key: str, x_norm: float, y_norm: float)

    # Postęp operacji (ładowanie / renderowanie)
    sig_progress = Signal(int, str)
    # (percent: int, status_text: str)

    # Błąd
    sig_error = Signal(str)
    # (error_message: str)

    # Renderowanie zakończone
    sig_render_finished = Signal(dict, str)
    # (stats: dict, output_path: str)


# Singleton dla całej aplikacji
_signals: AppSignals | None = None


def get_signals() -> AppSignals:
    """Zwraca globalną instancję sygnałów."""
    global _signals
    if _signals is None:
        _signals = AppSignals()
    return _signals
