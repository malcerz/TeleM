# TeleM — ALT BAR: naprawa orientacji po obrocie ETAP 1

## 1. Reprodukcja błędu

Presety `cycling_dashboard_v7/v8/v9/v10` oraz domyślny layout używają dla `alt_visual` konfiguracji w rodzaju:

```text
form=bar
bar_style=ruler
rotation=90
brak orientation
```

Ruler bez `orientation` jest renderowany jako poziomy. Następnie compositor obraca cały raster o 90°, więc pionowa staje się również etykieta, wartość i jednostka.

## 2. Gdzie powstawał błędny obrót

Geometria i tekst są tworzone w `src/indicators/bar.py`. Wspólna pionowa ścieżka `_render_ruler_vertical()` poprawnie rysuje tekst poziomo.

Błąd powstawał później w `src/indicators/compositor.py`, gdzie `rotated_paste()` stosował `cfg.rotation=90` do całego poziomego rasteru legacy.

## 3. Preview vs final

Main Preview i Export Preview wywołują `render_preview()` → `compose_overlay()`. Final Render również wywołuje `compose_overlay()` w workerze. Pierwsza rozbieżność nie była w rendererze preview/final, tylko w wspólnej interpretacji konfiguracji `alt_visual`.

Finalny globalny obrót obrazu pozostaje osobnym etapem pipeline’u i nie został zmieniony.

## 4. Root cause

Legacy layout używał rotacji widgetu jako sposobu uzyskania pionowego bara. Po wprowadzeniu wspólnego kontraktu `orientation=vertical` ten zapis stał się semantycznie błędny: lokalna rotacja obracała także tekst.

## 5. Minimalna poprawka

Dodano runtime-only `_effective_indicator_cfg()`:

```text
alt_visual + bar/segment_bar + brak orientation + rotation 90/270
    -> orientation=vertical
    -> rotation=0
```

Layout użytkownika nie jest mutowany ani przepisywany do pliku. Jawnie ustawione `orientation` i `rotation` pozostają bez zmian.

## 6. Zakres problemu

Problem dotyczył legacy `alt_visual`, nie wspólnej geometrii pionowego ruler’a. Wspólna logika vertical gauge już ma poprawny kontrakt poziomych napisów. Inne vertical gauges nie zostały zmienione.

## 7. Testy

- legacy altitude config → `orientation=vertical`, `rotation=0`,
- explicit vertical config → brak nadpisania rotacji,
- compositor bbox legacy altitude → wysokość większa od szerokości,
- istniejące testy orientation/bar/slope/altitude.

Wynik: `35 passed`.

## 8. Runtime verification

Nie wykonano fizycznego testu wizualnego na materiale z obrotem ani finalnego eksportu. Nie należy przedstawiać tej zmiany jako zweryfikowanej wizualnie na realnym wideo.

## 9. Zmienione pliki

- `src/indicators/compositor.py`
- `tests/test_altitude_bar_rotation.py`
- `Raporty/RAPORT_ALTITUDE_BAR_ROTATION_FIX_ETAP_1.md`

## 10. Deferred issues

- Realny test `auto/90/180/270` na materiale użytkownika.
- Osobna weryfikacja końcowego globalnego obrotu całego HUD dla materiałów portrait.
- Brak zmian w mapie, telemetry, cancel/partial MP4, GPU backendach, HUD Resolution i HUD Frequency.
