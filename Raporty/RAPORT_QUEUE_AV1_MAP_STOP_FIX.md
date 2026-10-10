# Raport: Naprawa Regresji Export Queue (Intel AV1 Mapa, STOP Cancellation, Watchdog False-Error)

Data: 2026-09-28
Środowisko: Intel Core Ultra 7 155H / Intel Arc Graphics / Windows 11
Katalog roboczy: C:\_DEV\SportCamHUD-main (branch: main, commit bazowy: 4641dcb)

---

## 1. Cel i zidentyfikowane problemy

W zadaniu rozwiązano trzy kluczowe regresje Export Queue w odniesieniu do kanonicznej ścieżki bezpośredniej (EKSPORTUJ):
1. **Intel AV1 export z kolejki tracił mapę**:
   - _on_add_to_queue() budowało opcje ręcznie, gubiąc specyficzne dla Intela klucze (intel_codec, encoder_profile, _gui_hud_preview_checkbox).
   - _restore_job_snapshot_onto_controller() pomijało ładowanie FIT, gdy na kontrolerze znajdowały się już próbki GPMF (paths_changed=False), przez co ctrl.telemetry.fit_gps_track pozostawał pusty, a 
esolve_gps_track('auto') zwracało 0 punktów, wyłączając mapę.
   - Brak wywołania ctrl._ensure_map_context() i ctrl._trigger_map_background_prefetch().
2. **Przycisk STOP w kolejce nie anulował aktywnego renderu**:
   - RenderTab._on_queue_stop() wywoływało nieistniejącą metodę self._on_cancel_clicked().
   - Przedwcześnie wywoływało 
otify_render_done(success=False) w wątku GUI zanim worker zdążył się zatrzymać, generując błąd i podwójne przejście terminalne.
3. **Kolejka raportowała status=error podczas gdy render trwał i rósł postęp**:
   - Watchdog startu (10s) w ExportQueue._scheduler_loop() sprawdzał 
ender_status == 'running' and render_progress == 0.0. Inicjalizacja D3D11 / kompilacja shaderów AV1 na GPU Intela trwa ~15-25s do klatki 1, co powodowało fałszywy timeout i błąd Render worker did not start.
   - 
otify_render_progress() aktualizowało status na 
unning tylko z fazy preparing, ignorując fakt, że status był już błędnie ustawiony na error.

---

## 2. Zastosowane poprawki w kodzie

### src/gui/export_queue.py
- Rozszerzono 
otify_render_done o parametr cancelled: bool = False. Gdy cancelled=True, zadanie przyjmuje stan job.render_status = 'cancelled', a nie 'error'.
- Zabezpieczono watchdog startowy: sprawdza wyłącznie zadania w stanie preparing (zapobiega fałszywym błędom podczas długiej inicjalizacji AV1).
- W 
otify_render_progress() dodano automatyczne przywracanie statusu 
unning oraz czyszczenie fałszywego komunikatu Render worker did not start, gdy zarejestrowano faktyczny postęp renderera (clamped > 0.0).

### src/gui/qt/tabs/render_tab.py
- Zastąpiono błędne self._on_cancel_clicked() kanonicznym wywołaniem self._on_cancel().
- Usunięto przedwczesne 
otify_render_done() z _on_queue_stop(). Zakończenie zadania obsługiwane jest czysto przez cykl życia _on_stopped() -> _end_render().
- W _end_render() przekazywany jest parametr cancelled=is_cancelled (ool(self._render_state and self._render_state.cancelled) or self._cancelling).
- W _on_add_to_queue() zastosowano kanoniczny generator opcji: options = self._build_options_from_gui(), zachowując kompletne parametry Intela i podglądu.
- Zabezpieczono pobieranie it_path (ctrl.fit_path or ctrl.telemetry.fit_path).
- W _restore_job_snapshot_onto_controller() dodano wymuszone wczytanie pliku FIT, inicjalizację kontekstu mapy oraz prefetch kafelków.

### src/gui/qt/_mixins/render_mixin.py
- W _notify_queue dodano przekazywanie cancelled=bool(self.render_cancel_event.is_set()).

---

## 3. Wyniki walidacji

| Test / Kryterium | Status | Wynik / Metryki |
|---|---|---|
| **Pikselowa parzystość Direct vs Queue AV1 (300 klatek)** | **PASS** | Full frame: max_diff=0.0, MAE=0.0<br>Map region: max_diff=0.0, MAE=0.0, diff_px=0 |
| **Pętla STOP & Cancellation (Phase 3)** | **PASS** | Zadanie 1 -> cancelled (error=Anulowano), Zadanie 2 -> queued, Kolejka -> paused=True, 0 sierocych procesów |
| **Wznowienie po STOP (Phase 14 Restart)** | **PASS** | Po kliknięciu Start zadanie 2 natychmiast wystartowało i renderowało poprawnie |
| **Watchdog False-Error Fix** | **PASS** | Zero fałszywych błędów startu; postęp > 0 natychmiast uzdrawia stan do 
unning |
| **Pytest Suite (Queue Lifecycle & Basic)** | **PASS** | 39 passed in 5.34s (w tym 2 nowe testy regresyjne cyklu anulowania i uzdrawiania) |
| **NTFY Notification** | **PASS** | Powiadomienie pomyślnie wysłane do https://ntfy.sh/MalcerzPOP |

---

## 4. Izolacja backendów
Wszystkie zmiany zostały ograniczone do warstwy zarządzania kolejką eksportu (export_queue.py), widoku GUI (
ender_tab.py) i mixinu wykonawczego (
ender_mixin.py). Nie zmodyfikowano specyficznych backendów AMD ani NVIDIA.

---

## 5. Git Closeout Status

- FIX_COMMIT=07c677a68d66f47b1190b97ba0aba7f49545d8ed
- REMOTE_MAIN_HEAD=07c677a68d66f47b1190b97ba0aba7f49545d8ed
- FOCUSED_TESTS_PASS=YES
- PUSH_RESULT=PASS
- FINAL_STATUS=QUEUE_AV1_MAP_STOP_FIXED_AND_PUBLISHED
