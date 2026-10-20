# AMD compass / BAR value placement — 2026-10-20

**Uzupełnienie po odpowiedzi użytkownika:** wskazano `GX010380.MP4` z
`F:\GoPro\2026-10-16`. Szczegółowa weryfikacja znajduje się na końcu raportu.

## Stan początkowy i zakres

Repozytorium `C:\_DEV\SportCamHUD`, `main`, HEAD `16cab38`.
Zachowano istniejące zmiany użytkownika w `def_layout.json` oraz wszystkie
zastane pliki nieśledzone. Bez branch/worktree/stash/push. Przeczytano
AGENTS.md i BENCHMARKS.md. Produkcyjna DLL AMD ma SHA-256
`BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F`.

## A. Diagnoza i minimalna poprawka

**Nie odtworzono zgłoszonego zamrożenia dla aktualnego ustawienia GPMF.**
Eksport sprzed zmian kodu na istniejącym materiale użytkownika pokazuje
058° → 062° → 061° → 059° (klatki 0/30/60/119).
Nie można uczciwie przypisać temu konkretnemu zgłoszeniu potwierdzonej przyczyny.
Użytkownik następnie wskazał GX010380.MP4; czas występowania nie został podany.

Potwierdzono osobny, rzeczywisty błąd ścieżki AMD final przy budowaniu cache:
`amd_native_exporter.py` przekazywał `heading_samples` GPMF, następnie GPX,
następnie kurs wyliczony z przekazanego tracka, **ignorując `compass.source`**.
Argument `compass_heading_samples` nadpisywał poprawny wybór w builderze.
Dla ustawienia FIT, stałego GPMF=90° i zmiennego FIT=350°→20° stary blok
zwracał stałe 90°. Preview używa `telemetry.resolve_samples` i wybranego źródła.
To potwierdzona przyczyna zamrożenia dla takiej kombinacji danych, nie dowód
na przyczynę pierwotnego zgłoszenia z GPMF.

Drugi problem: builder przy pustej liście ponownie wybierał FIT/GPMF/GPX,
a ostatecznie także `heading_samples` z ogólnej ścieżki (potencjalnie dystans).
Mógł też sięgać do WORKER_CACHE mimo jawnie przekazanych danych nowego projektu.

Zmiany:

- `src/ffmpeg/amd_native_exporter.py`: `_amd_compass_samples` korzysta z
  kanonicznego `resolve_samples_from_sources`, zgodnie z ustawionym źródłem;
  wywołanie raz podczas przygotowania eksportu, bez pracy dodatkowej per-frame.
- `src/render_preparation.py`: `build_telemetry_cache_vectorized` respektuje
  jawnie pusty stream, nie zastępuje go innym źródłem ani dystansem; przy
  przekazanym `field_samples` używa danych tego projektu. Przygotowanie w GUI
  również nie zastępuje brakującego wybranego streamu GPMF-em.
- `compute_cache_key`: kontrakt kompasu podniesiono do
  `selected_source_cog_v2_no_fallback`; stare cache tego kompasu nie są używane.
  Dotychczasowe fingerprinty plików, źródło, czas startu, FPS i timeline nadal
  należą do klucza. Nie zmieniano formatu serializacji kolumn.
- `worker_cache.py`, `frame_data.py`, `frame_renderer.py` i compositor:
  prześledzone, bez zmian. `heading_compass[frame_idx]` trafia przez
  `extra_indicators["compass"]` do istniejącego renderera tarczy. Cache rastra
  kompasu już uwzględnia heading i formatowany tekst. Wygląd bez zmian.

Dowód: `tests/test_amd_compass_selected_source.py` sprawdza FIT/GPMF/GPX/auto,
61 kolejnych klatek przy 30 FPS, interpolację przez północ, zapis/odczyt mmap
oraz brak przejęcia danych poprzedniego projektu przy pustym streamie.
Wraz z istniejącymi testami source/parity: **12 passed**.

## B. BAR

Wdrożono **moving / top / bottom**. Trybu `both` nie dodawano.
`moving` jest domyślny i zachowuje poprzedni raster; dla Segments oznacza
dotychczasowy sposób prezentacji tego stylu (jego tekst nie podążał za markerem).
Nowe ustawienia są wyłącznie w schemacie właściwości BAR, w zakładce Text:

- `Pozycja wartości`: Ruchoma (dotychczasowa), Statyczna u góry, Statyczna u dołu.
- Ruler i legacy Slope: `Rozmiar wartości (mnożnik)`, istniejący
  `value_font_scale` 0.5–5.0, domyślnie 1.0.
- Segments: zachowany istniejący `value_font_size`, własny font, kolor,
  `value_align`, `value_show_unit`, `value_unit`.

Zmiany plików i funkcji:

- `src/gui/qt/models.py`: `bar_indicator_fields`, `_bar_ruler_fields`.
- `src/indicators/bar.py`: `_render_bar_indicator_borrowed` wyłącza poprzedni
  odczyt tylko w top/bottom; `_add_static_value_band` dodaje osobny przezroczysty
  pas z tekstem. Poziomy i pionowy ruler oraz Segments korzystają z tego samego
  rozwiązania. Margines i raster rosną do wymiarów rzeczywistych glifów; nie ma
  nakładania tekstu na skalę lub tytuł. Zachowano ścieżkę efektów compositora,
  outline i kolor. Nie dodawano osobnego systemu offsetów.
- Klucz statycznego cache pionowego rulera uwzględnia teraz `show_value`, aby
  przełączenie moving → top/bottom nie przywracało tekstu ruchomego ze starej bazy.
- `_draw_text_bounded`: dla tekstu z `°` dodano pozycję rysowania do bbox
  zwracanego względem (0,0). Bez tego clamp BAR mógł ucinać jednostkę na brzegu.
  Zmiana dotyczy tylko BAR z graficznym stopniem; zwykły tekst nie zmienia się.
- `tests/test_bar_value_placement.py`: nowe testy opcji, obu orientacji i stylów,
  jednostek, części dziesiętnych, rozmiaru fonta, ukrytego odczytu, przełączeń
  cache i geometrii pasów. Test bazowy potwierdza identyczność moving z poprzednim
  ustawieniem bez `value_position`.

### Temperatura i stopnie

Kanoniczne jednostki telemetrii temperatury to `°C` (m.in. FIT_UNIT_HINTS i
domyślne wartości compositora). Zarówno text, jak i BAR respektują jednak jawne
`cfg.unit`. Użytkownik ma w `fit_temperature_text` zapisane **`unit: "C"`**,
podobnie w `temp_text`. Dlatego widoczne `10.5 C` nie oznacza zgubienia stopnia
przez BAR: to zapisany override. Nie zmieniano globalnie jednostek ani presetu
użytkownika. Wybranie `°C` w istniejącym polu jednostki daje `10.5 °C` także
z fontem bez glifu stopnia, dzięki istniejącemu graficznemu rysowaniu symbolu.
Wspólna ścieżka compositora przekazuje ten sam sformatowany tekst do text/BAR;
BAR zachowuje część dziesiętną, jednostkę i opcje ukrywania/własnej jednostki.

### Preview / Final i geometria

Test `test_temperature_preview_final_pixel_parity` porównuje scalar Preview
`resolve_current_presentation` z rzeczywistą kolumną Final i raster compositora:
moving/top/bottom × horizontal/vertical × 540p/1080p/4K × 2 czasy.
Wyniki dla każdej pary: **max_diff=0, MAE=0, different_pixels=0**.
Istniejący test kompasu sprawdza obie tarcze, jasne tło i te same 3 rozdzielczości.
Testy nie zastępują sprzętowego harnessu: wyniki sprzętowe poniżej.

Przejrzano wygenerowane rastry i klatki MP4. Fixture eksportu pionowego top
umieszczono x=85%, y=70%, poziomego bottom x=75%, y=80%, żeby cała skala mieściła
się na ekranie. Nie zmieniano pozycji w `def_layout.json`. Przełączanie orientacji
przy oryginalnym x=94.4% mogłoby umieścić część poziomej skali poza ekranem,
tak jak przy innych zbyt blisko krawędzi położonych widgetach.

Podgląd wszystkich trybów: [bar_modes.png](amd_compass_bar_20261020/bar_modes.png).

## Testy sprzętowe i ograniczenia

Kanoniczne pliki `Video/GX020079.MP4` i `.fit` są nieobecne w checkoutcie.
Przed użyciem zgłoszono parę zastępczą istniejącego materiału użytkownika:
`F:\GoPro\2026-10-12\GX010368.MP4` + `Afternoon_Ride.fit`.
Użyto istniejącego harnessu `SportCamHUD.py --test-amd-export`, bez zmiany
kodowania, muxowania lub DLL. To materiał 8K → 4K, QUALITY/HEVC/40M/HLG,
start 60 s. Nie jest kanonicznym benchmarkiem 1131 klatek.

Wyniki, logi, profile, MP4 i zrzuty: `Raporty/amd_compass_bar_20261020/`.
Pierwszy start harnessu zablokował własny plik loga, ponieważ stdout skierowano
do tej samej nazwy co log eksportera; poprawiono uruchomienie na `.stdout.log`.
Nie zmieniano storage preflight.

Druga para, zgłoszona przed użyciem: `F:\GoPro\2026-10-16\GX010380.MP4`
+ `2026-10-16_06-22-14.fit`, start 60 s, oryginalny layout użytkownika.

| Przebieg | Tryb | Klatki | Źródło kompasu | true_fps z profilu | Efektywne FPS harnessu |
|---|---|---:|---|---:|---:|
| before | direct | 120 | GPMF | 13.853 | 8.07 |
| after_moving | direct | 120 | GPMF | 14.103 | 7.07 |
| top_fit | queue | 180 | FIT | 15.429 | 10.11 |
| bottom_fit | queue | 180 | FIT | 15.450 | 10.14 |
| night_gpmf | direct | 120 | GPMF | 27.667 | 8.22 |

Każdy wynik harnessu ma `success=true`. ffprobe z `-count_frames` potwierdził
720/720 klatek wideo łącznie i strumień AAC w każdym MP4. Wszystkie wideo HEVC,
3840×2160, HLG. AMD nadal używa VBR 40/60 Mb/s i live mux; logi zawierają sprzętowe
QP (np. 180 próbek dla eksportu 180 klatek), finalizacja zakończona.
Nie zmieniano QP/VBR/VBV/HRD, audio pipeline, finalizatora ani ustawień profili.
Nie dodawano ekstrakcji audio lub końcowego muxu. Testy kontraktów QP i muxu
wchodzą do zestawu poniżej. Nie jest to pełna macierz profili/bitrate/HDR.

Dowód aktualizacji kompasu:

- `before` i `after_moving`: heading 56.99115–62.49794°, **119/119** zmian między
  sąsiednimi klatkami; w MP4 odczyty i tarcza zmieniają się.
- `top_fit` i `bottom_fit`: heading 56.52432–68.17220°, **179/179** zmian między
  sąsiednimi klatkami. MP4 pokazuje m.in. 057° → 068°, obrót róży jest widoczny.
  Tekst stopni jest zaokrąglany do liczby całkowitej zgodnie ze starym wyglądem;
  brak zmiany cyfry w sąsiedniej klatce nie oznacza braku aktualizacji heading.
- `night_gpmf`: wszystkie 120 wartości to brak kursu (`None`), MP4 pokazuje
  `--°` i nieruchomą tarczę. To **nie jest PASS testu ruchu kompasu**. Nie wolno
  podstawiać kursu FIT w miejsce wybranego GPMF, aby ukryć brak danych. Preview
  tego nocnego fragmentu w rzeczywistej sesji GUI nie zostało osobno nagrane.

Surowe wartości każdej klatki, ścieżki cache, ustawienia profili i dane ffprobe:
[export_evidence.json](amd_compass_bar_20261020/export_evidence.json).
Klatki MP4: `before_inspection.png`, `after_moving_inspection.png`,
`top_fit_inspection.png`, `bottom_fit_inspection.png`, `night_gpmf_inspection.png`.
Skrypty odtwarzania i analizy: `run_exports.py`, `inspect_exports.py` w tym samym
katalogu; używają istniejącego harnessu, nie zastępują go testem ad-hoc.

### Wydajność

Porównywalna para before/after_moving ma te same wejścia, czas, 120 klatek,
rozdzielczość, layout i parametry enkodera. true_fps 13.853 → 14.103 (+1.81%).
Efektywne FPS obejmuje koszt przygotowania, GUI i preview i spadło 8.07 → 7.07.
Tak krótki pojedynczy pomiar nie dowodzi ani poprawy, ani braku regresji
długiego eksportu. Top/bottom zmieniają workload i nie są bazą porównania FPS.
Materiał dzienny to 8K → 4K QUALITY, nie workload deklarowanych ok. 40 FPS.
**40 FPS oraz długi benchmark 1131 klatek: NOT TESTED / NOT PROVEN.**
Zmiana kompasu działa raz w przygotowaniu; top/bottom dodaje raster/tekst do
istniejącego cache BAR. Nie zmieniano algorytmów mapy, chartów lub GPU compositora.

## Końcowy zestaw testów

**201 passed in 11.25s**, `Raporty/amd_compass_bar_20261020/pytest_final.log`.
18 plików testowych: nowy AMD selected-source i BAR placement, istniejące
compass source/rendering/migration, bar orientation/integration/cache/ruler
ticks/size/rasterizer parity/distance, AMD final temperature, common render
preparation, AMD live mux/audio finalization/direct MP4/VBR-QP/QP governance.
`git diff --check`: PASS. Testy geom./obrazu uzupełniono ręczną oceną wygenerowanych
rastrów i wybranych klatek MP4; nie wykonano osobnej interaktywnej sesji GUI
przeklikiwania wszystkich nowych ustawień. Harness używa normalnego GUI,
zarówno direct, jak i queue, z `--preview-hud`.

## Backend isolation, ryzyka i stan końcowy

DLL AMD po testach: SHA-256 dokładnie jak na początku. Nie przebudowywano i nie
podmieniano DLL. Kod natywny, Intel, NVIDIA, mapa, SmartSync, storage preflight,
audio, QP i profile nie zostały edytowane. Wspólna zmiana przygotowania jest
ograniczona do kontraktu źródła kompasu; brakującego streamu nie zastępuje już
innym źródłem. Wspólny renderer BAR celowo udostępnia opcję Preview/Final.

PASS: BAR moving/top/bottom, font, jednostki, geometria rastra, testy Preview/Final,
krótkie eksporty AMD direct/queue, QP feedback, AAC i finalizacja, hash DLL.
NOT PROVEN: pierwotne zamrożenie z ustawieniem GPMF; po wskazaniu GX010380.MP4
potwierdzono brak kursu do 79.317 s i poprawny ruch kompasu w późniejszym eksporcie
(szczegóły poniżej). NOT PROVEN: brak regresji długookresowej
wydajności i wymagany poziom ok. 40 FPS. **Nie oznaczono całego zadania COMPLETE.**

`def_layout.json` zachowano byte-for-byte: Git blob
`a13f79c0fbcd92be18c5705a112f07343e73ae50` (ten sam skrót w początkowym diffie),
SHA-256 `86EC156A0D4EE062719F6D8D2BF34CB1B5CD6F174CBA5DA8794C01ABB31266B2`.
Nie dodano go do commitów. Wszystkie zastane pliki nieśledzone pozostawiono.
Surowe logi, MP4 i zrzuty tego zadania pozostają lokalnymi artefaktami w katalogu
raportu; do commitu dołączono skrypty, fixture layoutów, zbiorcze evidence i test log.

## Commity i git status

- A: `3af3c47` — `fix(amd): honor selected compass source in final telemetry cache`.
- B: `f6c3ffe` — `feat(bar): add static value placement and preserve unit formatting`.
- Gałąź `main`; brak push. Końcowy status ma zachowane `M def_layout.json`,
  zastane pliki nieśledzone oraz lokalne surowe artefakty testów. Nie jest czysty
  z powodu zachowanych danych użytkownika, nie z powodu niezacommitowanego kodu.

## Uzupełnienie: GX010380.MP4 wskazany przez użytkownika

### Obserwacja rzeczywistego managera Preview

Uruchomiono normalny harness AMD przez `diagnose_night.py`. Skrypt tylko w procesie
testowym obserwuje `RenderPreparationService.prepare`, zachowując oryginalne
wywołanie. Odczytuje realny `TelemetryDataManager` po normalnym załadowaniu filmu
i FIT. Nie zmienia jego danych, eksportera, runtime ani DLL.
Materiały: dokładnie `F:\GoPro\2026-10-16\GX010380.MP4` i wcześniej jawnie
wskazany `2026-10-16_06-22-14.fit` z tego samego katalogu.

- Początek filmu w managerze: `2026-10-16 04:22:16.182130` UTC.
- GPMF: 21 142 próbki kursu, z czego 20 633 poprawne.
- Pierwsza próbka GPMF: `04:22:47.100000`, kurs `None` (brak).
- **Pierwszy poprawny kurs GPMF: `04:23:35.499000`, czyli 79.316870 s filmu.**
- FIT ma poprawny kurs wcześniej, od `04:22:24`, ale preset użytkownika wybiera
  `gpmf`. Nie zmieniano źródła w jego presecie ani nie podstawiano FIT.

Dodatkowy eksport 60–63 s (90 klatek) potwierdza: `TelemetryDataManager.resolve_value`
używany przez Preview i Final zwracają `None` w każdej klatce. To rzeczywisty brak
kursu w wybranym streamie, a nie utrwalenie pierwszej liczby w Final. Istniejący
kompas w tym stanie pokazuje `--°` i nieruchomą tarczę. Takiego braku danych nie
naprawiano przez wymyślanie kierunku lub zmianę źródła użytkownika.

### Sprzętowy eksport obejmujący przejście do poprawnego kursu

`--start-seconds 75 --frames 900 --quality QUALITY --codec hevc --bitrate 40M
--preview-hud --layout def_layout.json`, tryb direct, 3840×2160, HLG.
Eksport obejmuje około 75–105 s filmu. `night_transition75.json`: `success=true`.

- W klatkach 0–129 kurs jest nieobecny.
- Pierwszy kurs w klatce 130: czas filmu 79.337667 s,
  Preview `113.35252905635714°`, Final `113.35253143310547°`.
- Zgodność managera Preview i Final sprawdzono we **wszystkich 900 klatkach**:
  rozbieżności dostępności = 0; maks. błąd kąta `0.0000073772°` (float32).
- W tym oknie jest 728 klatek z kursem, zakres 27.24560–189.61752°; pozostałe
  zawierają brak kursu, w tym kolejne krótkie luki w samym źródle.
- Rzeczywisty MP4 po przejściu pokazuje 113°, 091°, 117°, 058°, 061° i obrót róży.
  Przejrzano klatki 0/130/150/300/600/899; dowód:
  [night_transition75_compass.png](amd_compass_bar_20261020/night_transition75_compass.png).
- ffprobe: **900 klatek HEVC**, 3840×2160, obecny AAC (1408 ramek audio).
- Hardware QP: avg=21.3, min=14, max=26, 900 próbek; VBR 40/60 Mb/s,
  `live_mux=yes`; Finalize=0.001 s.
- true_fps=35.26856, efektywne FPS harnessu=24.91. Nadal nie jest to dowód
  40 FPS ani porównanie before/after na kanonicznym workloadzie.

Podsumowanie i próbki:
[night_transition75_summary.json](amd_compass_bar_20261020/night_transition75_summary.json).
Pełny zrzut wszystkich 900 wartości managera i cache, surowe próbki, MP4 i logi
zostawiono lokalnie w `night_transition75.*`. Jest to dowód zarówno wartości
per-frame, jak i zmiany widocznej w finalnym MP4.

### Kontrola zastanego cache całego projektu

Porównano również zastany przed zmianami cache
`2b69b500cd63e2668e274b962f4551f75c4d4c4945e060c70361f35f8811a2bc`
z bieżącym streamem GPMF i kanonicznym scalar resolverem Preview:
**64 288 klatek, 0 rozbieżności** przy tolerancji float32, maks. błąd kąta
`0.0000152572°`. 2453 klatki mają brak kursu zgodny ze źródłem.
Zastany cache nie zamraża pierwszej próbki i nie zawiera kursu innego projektu
w tej sprawdzonej sesji. Dowód:
[night_original_cache_comparison.json](amd_compass_bar_20261020/night_original_cache_comparison.json).

Dodano przenośny test regresji początkowej luki GPMF z pierwszym kursem po
79.316870 s: pierwsza poprawna klatka eksportu od 75 s to 130, potem kurs zmienia
się zgodnie z rzeczywistym managerem Preview. Zestaw compass follow-up:
**13 passed in 1.90s** (`pytest_night_followup.log`). Poprzedni pełny zestaw:
201 passed; dodatkowo jeden nowy test, bez kolejnej zmiany kodu produkcyjnego.

### Wniosek i ograniczenie

**Dla wskazanego GX010380.MP4 nie potwierdzono zamrożenia Final po pojawieniu się
poprawnych danych.** Potwierdzono brak wybranego kursu GPMF do ok. 1:19.317,
zgodny między Preview i Final, oraz poprawny obrót kompasu później. Nie zmieniano
produkcji, aby maskować brak danych. Jeżeli zgłoszenie dotyczy nieruchomego
kompasu także po 1:20, potrzebny jest dokładny czas i ustawienia tego eksportu;
nie deklarujemy, że taki inny przypadek został odtworzony lub naprawiony.

Po uzupełnieniu DLL i `def_layout.json` nadal mają identyczne skróty jak powyżej.
Follow-up: `test(amd): verify GX010380 compass GPS gap and final parity` (lokalny
commit testu, skryptu i dowodów; bez push). Nie dodano kolejnej poprawki produkcyjnej.
