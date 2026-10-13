# Archiwa źródeł

Twórz przyszłe ZIP-y poleceniem `python tools/create_source_archive.py <nowy-plik.zip>`.
Skrypt pakuje bieżącą zawartość plików śledzonych przez Git, pomija
`__pycache__`, `.pyc` i `.pyo` oraz odmawia nadpisania istniejącego ZIP-a.
Przed archiwizacją sprawdź `git status`: nowe, nieśledzone źródła i raporty
nie wchodzą do archiwum. To snapshot źródeł, nie paczka portable.

Śledzone `.pyd`, DLL, `.lib` i `.exp` nie są odfiltrowywane. Ignorowane
binaria runtime wymagają osobnego manifestu dystrybucji. Nie uruchamiaj
sync_portable ani build_portable w celu tworzenia archiwum źródeł.
Nie używaj rekurencyjnego Compress-Archive na całym katalogu repozytorium:
reguły `.gitignore` nie filtrują takiego ZIP-a.
