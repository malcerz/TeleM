# FFmpeg Integration Module

Ten pakiet zawiera zrefaktoryzowaną architekturę integracji z FFmpeg i sprzętowej akceleracji w aplikacji TeleM. 
Logika została podzielona na logiczne podmoduły w celu ułatwienia konserwacji kodu i testowania.

## Struktura pakietu

*   `detection.py`: Odpowiedzialny za wykrywanie sprzętowego przyspieszenia (GPU) i enkoderów (NVIDIA NVENC, AMD AMF, Intel QSV).
*   `worker_cache.py`: Zarządza globalnym słownikiem `WORKER_CACHE` używanym do uniknięcia serializacji IPC przez multiprocessing.
*   `frame_renderer.py`: Renderowanie pojedynczych klatek w procesach roboczych (ProcessPoolExecutor).
*   `shared_memory.py`: Zarządza pamięcią współdzieloną (`SharedFramePool`) dla bezkopiorowej komunikacji IPC przy renderingu 4K.
*   `command_builder.py`: Budowanie parametrów wywołania procesu FFmpeg oraz filtrów wideo.
*   `streaming.py`: Pętla produkcyjno-konsumencka przesyłania klatek do potoku stdin FFmpeg i obsługa postępu.
*   `second_pass.py`: Renderowanie klatek na dysk (BMP) i generowanie końcowego pliku wideo.

## Kompatybilność wsteczna

Stary plik `src/ffmpeg_pipeline.py` w katalogu głównym modułów działa jako re-export wrapper kierujący wywołania do tego pakietu. Wszystkie istniejące importy w testach i kontrolerze są w pełni obsługiwane bez zmian.
