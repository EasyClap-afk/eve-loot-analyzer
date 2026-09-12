# EVE Loot & Jita Market Analyzer

Aplikacja desktopowa dla Windows 10/11 na podstawie specyfikacji v1.0.

## Uruchomienie

Kliknij **Start.bat** w folderze projektu albo **EveLootAnalyzer.exe** w `dist-v1.5/EveLootAnalyzer`.
Paczka `dist-v1.5/EveLootAnalyzer-Windows.zip` zawiera program i wymagane biblioteki: wypakuj cały folder, a następnie uruchom EXE. Python nie jest potrzebny w wersji spakowanej. Nie przenoś samego EXE bez folderu `_internal`.

Wersja 1.5 ma czarno-czerwony motyw inspirowany Pochven. Język wybierz w **Profil i ustawienia → Język interfejsu → Polski / English**. Wybór jest zapamiętywany lokalnie i działa od razu, także dla bieżących wyników i zapisanych sesji. Same obliczenia, identyfikatory i wartości w bazie nie są tłumaczone ani zmieniane. Nazwy przedmiotów, skilli, postaci i lokacji EVE pozostają oryginalne.

Polskie liczby mają przecinek dziesiętny, angielskie — kropkę. Próg na liście obserwowanych również przyjmuje format wybranego języka. Przykłady: `1 234,56` (PL), `1,234.56` (EN). Dokumentacja angielska: [README.en.md](README.en.md).

Opcjonalnie uruchom `Install.bat`: kopiuje program do `%LOCALAPPDATA%\Programs\EveLootAnalyzer` i tworzy skrót na pulpicie, bez uprawnień administratora. Aktualizację wykonuj przy zamkniętej aplikacji. Dane sesji pozostają w osobnym katalogu danych.

1. W zakładce **Profil i ustawienia** ustaw skille, RAW standings i stan klona.
2. W **Analiza lootu** wklej cargo skopiowane z EVE i kliknij **Analizuj rynek**.
3. Dwuklik na przedmiocie pokazuje fill levels, depth, historię, rozbicie score i uzasadnienie.
4. Dwuklik na blueprintcie pozwala ustawić remaining runs, runs, ME i TE. Parametry dotyczą każdej kopii w stosie; ilość kopii pochodzi z lootu. Przy różnych parametrach analizuj kopie osobno.
5. Dodaj przedmioty lub produkty BPC do **Watchlist** i odśwież ceny. Zapisz analizę jako sesję, aby zbierać statystyki.

Nazwy przedmiotów pozostają po angielsku. Pierwsze uruchomienie używa dołączonego indeksu SDE; bez indeksu aplikacja automatycznie go pobierze. Aktualizację uruchomisz w zakładce **Dane**.

Wiersze inventory mogą zawierać puste pole ilości (np. pojedynczy blueprint) — aplikacja przyjmuje wtedy 1 sztukę, zachowując pozycje pozostałych kolumn. Nieprawidłowa, niepusta ilość pozostaje nierozpoznana. Podsumowanie pokazuje liczbę rozpoznanych typów blueprintów i nierozpoznanych wierszy.

Tabela blueprintów pokazuje **Avg cost / 1 BPC** i **Avg profit / 1 BPC**. Są to koszt budowy i realistic profit całego stosu podzielone przez liczbę kopii. Jedna kopia obejmuje ustawioną liczbę runs. W szczegółach dostępne są też materiały, job fee, wpływy i zysk w przeliczeniu na jedną kopię. To średnie z analizy całego stosu; osobna analiza jednej kopii może dać inny wynik z powodu głębokości rynku i płynności.

Kliknij nagłówek kolumny w tabeli wyników, blueprintów, watchlisty, sesji lub dropów, aby sortować. Kolejne kliknięcie odwraca kolejność. Kwoty są porównywane według pełnej wartości ISK, niezależnie od skrótu k/m/b i zaokrąglenia. Kolumny z kilkoma wartościami porównywane są od lewej; N/A pozostaje oddzielną grupą. Odświeżenie tabeli zachowuje wybraną kolumnę i kierunek sortowania.

## Obliczenia i interpretacja

- Jita 4-4: station `60003760`, system `30000142`. Historia: cały The Forge `10000002`, jako przybliżenie płynności Jita.
- Instant Sell przechodzi po zleceniach obejmujących Jita, uwzględnia `min_volume`, dostępną ilość i dystans przez stargate’y. Częściowa sprzedaż pokazuje niesprzedaną ilość.
- Kwoty liczone przez `Decimal`, snapshoty przechowują je jako tekst dziesiętny bez konwersji przez float.
- Liquidity / Confidence / Realistic / ETA to jawne heurystyki z dokumentu, nie gwarancje sprzedaży. Brakujące dni historii mają zerowy wolumen, ale nie otrzymują wymyślonej ceny; confidence uwzględnia brak obserwacji.
- Realistic jest blendem scenariuszy. Gdy jednej ceny brakuje, pokazuje N/A. Suma z gwiazdką / PARTIAL zawiera tylko znane składniki. Przy częściowym buy depth niesprzedana część nie ma przypisanych wpływów z natychmiastowej sprzedaży.
- BPC build value oznacza dodatni zysk ekonomiczny z produkcji po pełnym zakupie materiałów, a nie cenę kontraktową kopii. Wymaga kapitału na materiały i job. `CANNOT BUILD` nie usuwa ekonomicznej kalkulacji; trzeba spełnić wymogi skilli. Zero przy nieopłacalnym BPC wynika z `max(0, profit)`.
- Produkcja: Jita NPC station, ME liczone na cały job, bez rigów. SCI i adjusted prices pobierane z ESI; materiały obecne w loocie nigdy nie zmniejszają kosztu budowy.
- Baseline podatków: specyfikacja z 2026-09-09, moduł `app/rules.py`. Nagłówek ESI używa tej daty, ograniczonej do bieżącego dnia UTC−11, ponieważ ESI odrzuca datę z przyszłości.
- Watchlist: target jednostkowy, kierunek `>=` lub `<=`; zmiana trybu zeruje stare pomiary, aby nie porównywać różnych miar. Odświeżenie respektuje ważny cache.
- Sesje są niezmiennymi snapshotami. Dashboard filtruje site i lokalną datę, liczy średnią, medianę, ISK/h i obserwowaną częstość dropów. Wartość łączna obejmuje regular realistic + ekonomiczną wartość BPC, nie faktycznie zrealizowany przychód. ISK/h nie obejmuje oczekiwania na sprzedaż i produkcję.

## Opcjonalne SSO

Tryb ręczny działa bez konta developerskiego. Do połączenia postaci zarejestruj własną aplikację typu Native / PKCE w EVE Developer Portal i wpisz publiczny **Client ID** w ustawieniach.

- Callback: `http://localhost:8765/callback`
- Scopes: `esi-skills.read_skills.v1` i `esi-characters.read_standings.v1`
- Nie używamy client secret. Refresh token jest zapisany w Windows Credential Manager; access token pozostaje w pamięci.
- Podpis JWT, issuer, audience, client ID i state są sprawdzane. Po połączeniu skille i standingi synchronizują się; manual override zachowuje ręczne wartości.
- Clone state ustaw ręcznie. SSO nie odczytuje parametrów BPC. Synchronizacja działa przy otwartej aplikacji co 15 minut; nie ma osobnego procesu w tle.
- Port 8765 musi być wolny. Login wygasa po 3 minutach. Przy błędzie ostatni profil pozostaje zachowany.
- Walidacja tokenu dopuszcza 60 sekund różnicy zegarów. Jeśli pojawi się komunikat o większej różnicy czasu, użyj w Windows: Ustawienia → Czas i język → Data i godzina → Synchronizuj teraz, a następnie ponownie połącz postać. Podpis, issuer, audience i Client ID nadal są sprawdzane.

Dokumentacja integracji: [CCP SDE](https://developers.eveonline.com/docs/services/static-data/), [CCP SSO / PKCE](https://developers.eveonline.com/docs/services/sso/).

## Dane lokalne

Domyślnie `%LOCALAPPDATA%\EveLootAnalyzer`: baza `analyzer.sqlite3`, cache i rotowane logi. Zakładka Dane umożliwia backup SQLite i otwarcie folderu. Zmienna `EVE_LOOT_DATA` pozwala wskazać oddzielny katalog, np. do testów. Eksport JSON zapisuje pełne wyniki bez tokenów.

## Uruchomienie ze źródeł / budowanie

Python 3.11+ (sprawdzone na 3.11) i Windows:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Testy i paczka:

```powershell
python -m pip install pytest pyinstaller
python -m pytest -q
powershell -ExecutionPolicy Bypass -File build.ps1
```

Warstwy: `parser.py`, `market.py`, `industry.py`, `rules.py` — logika; `esi.py`, `sde.py`, `sso.py` — integracje; `storage.py` — SQLite; `engine.py` — orkiestracja; `ui.py` — PySide6. Operacje sieciowe i import SDE wykonują się poza wątkiem GUI.

## Zakres weryfikacji

Automatyczne testy obejmują podatki, range/depth/min_volume, score, history, realistic cap, ME, job fee, profit/ROI, parser, cache/ETag/pagination/stale, profile, watchlist oraz scenariusz 5 itemów + 2 BPC i snapshot sesji. Połączenie publiczne ESI/SDE sprawdzone na rzeczywistych danych.

Pełne logowanie SSO wymaga Client ID i ręcznego zalogowania postaci; nie zostało sprawdzone na koncie użytkownika. Paczka Windows jest testowana lokalnie, nie na oddzielnej czystej maszynie. Program nie ma podpisu Authenticode; dystrybucja to przenośny ZIP z opcjonalnym instalatorem dla bieżącego użytkownika.

EVE Online i nazwy przedmiotów są własnością CCP. Aplikacja jest niezależnym zewnętrznym kalkulatorem.
