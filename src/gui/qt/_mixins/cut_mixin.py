"""Mixin for managing cut/trim regions in AppController.
"""

from __future__ import annotations


class CutMixin:
    def add_cut_region(self, start_s: float, end_s: float) -> None:
        """Dodaj fragment do wycięcia."""
        if end_s <= start_s:
            return
        # Wytnij tylko część, która nie koliduje z istniejącymi cięciami
        new_regions: list[tuple[float, float]] = [(start_s, end_s)]
        for existing in self._cut_regions:
            # Jeżeli nachodzi na istniejące cięcie — scal (poszerz)
            a, b = existing
            merged = False
            for i, (ns, ne) in enumerate(new_regions):
                if ns <= b and ne >= a:
                    new_regions[i] = (min(ns, a), max(ne, b))
                    merged = True
                    break
            if not merged:
                new_regions.append(existing)
        # Posortuj
        new_regions.sort(key=lambda x: x[0])
        self._cut_regions = new_regions
        self.signals.sig_cut_region_added.emit(start_s, end_s)
        self._render_preview()

    def undo_cut_region(self) -> None:
        """Cofnij ostatnie cięcie."""
        if not self._cut_regions:
            return
        idx = len(self._cut_regions) - 1
        removed = self._cut_regions.pop()
        self.signals.sig_cut_region_removed.emit(idx)

    def remove_cut_region(self, start_s: float, end_s: float) -> None:
        """Usuń dokładnie pasujący fragment wycięcia (np. granicę zakresu IN/OUT).

        Dodatkowa, nieinwazyjna pomocnik dla GUI — usuwa region (start_s, end_s),
        jeżeli istnieje w liście, i emituje aktualizację osi czasu.
        """
        target = (float(start_s), float(end_s))
        if target not in self._cut_regions:
            return
        idx = self._cut_regions.index(target)
        self._cut_regions.pop(idx)
        self.signals.sig_cut_region_removed.emit(idx)
        self._render_preview()

    def clear_cut_regions(self) -> None:
        """Przywróć wszystkie wycięte fragmenty."""
        if not self._cut_regions:
            return
        self._cut_regions.clear()
        self.signals.sig_cut_regions_cleared.emit()

    def is_in_cut_region(self, seconds: float) -> bool:
        """Sprawdź czy dany czas znajduje się w wyciętym fragmencie."""
        for start_s, end_s in self._cut_regions:
            if start_s <= seconds < end_s:
                return True
        return False

    def _skip_cut_regions(self, seconds: float, forward: bool = True) -> float:
        """Przeskocz do przodu/tyłu poza wycięty fragment."""
        if not self._cut_regions:
            return seconds
        for start_s, end_s in self._cut_regions:
            margin = 0.1  # 100ms marginesu poza cięciem
            if forward and start_s - margin <= seconds <= end_s:
                return end_s + margin
            if not forward and start_s <= seconds <= end_s + margin:
                return max(0.0, start_s - margin)
        return seconds
