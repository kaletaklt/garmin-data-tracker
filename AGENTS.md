# Architektura Systemu: Garmin AI Personal Coach (`garmin-data-tracker`)

## Cel projektu
Autonomiczny system trenerski łączący Garmin Connect, Google Sheets, Google Calendar, Tasker oraz Gemini / Antigravity, podzielony na 3 odseparowane moduły domenowe (`collector/`, `ai_coach/`, `calendars_sync/`) oraz współdzieloną warstwę infrastrukturalną (`common/`).

## Struktura katalogów i modułów

### 1. `collector/` – Zbieranie danych z zegarka i odczuć subiektywnych
- `collector/morning.py` (`python -m collector.morning`): Poranny przepływ wywoływany o stałej porze z Taskera:
  1. Pobiera statystyki `Wellness` z ostatnich 7 dni + dzisiaj (`collector/wellness.py`).
  2. Zapisuje poranną ankietę (energia 1–5, DOMS, dyskomfort, notatka) do zakładki `Dziennik_Subiektywny` (`collector/subjective.py`).
  3. Uruchamia detektor nieprawidłowości (`collector/anomaly_detector.py`). Jeśli wykryto anomalię w ankiecie (np. niska energia <= 2, ból, DOMS, uwaga), w statystykach (spadek HRV > 12% względem bazy 60d, status HRV `UNBALANCED`/`LOW`/`POOR`, wzrost RHR >= 5 bpm, wynik snu < 60, Body Battery < 50) lub brakujące dni w 7-dniowym planie – automatycznie wyzwala `ai_coach` oraz `calendars_sync`.
- `collector/post_activity.py` (`python -m collector.post_activity`): Przepływ po zakończonej aktywności (wyzwalany powiadomieniem z Garmin Connect -> Tasker):
  1. Pobiera 20 najnowszych aktywności i aktualizuje ostatnie 7 dni w zakładce `Aktywnosci` (`collector/activities.py`).
  2. Zapisuje ankietę potreningową (RPE 1–10, DOMS, dyskomfort, notatka) do `Dziennik_Subiektywny`.
  3. Rozlicza wykonanie dzisiejszego treningu (audyt TODO-06), a jeśli wykryto anomalię (np. RPE >= 9, zgłoszony ból, odchylenie dystansu > 25% lub bieg w dzień `REST`) – wyzwala pełny replan `ai_coach`.

### 2. `ai_coach/` – Mózg operacji (Planowanie, Personalizacja, Zapis wyłącznie do Garmin Connect)
- `ai_coach/main.py` (`python -m ai_coach.main`): Orkiestrator silnika trenerskiego.
- `ai_coach/analytics.py`: Wylicza CTL (42d), ATL (7d), TSB, ACWR, bazę 60d HRV/RHR/Snu, statystyki objętości z 8 tygodni oraz odczytuje zakładkę `Cele_i_Strategia`.
- `ai_coach/auditor.py`: Audyt wykonania treningów (TODO-06) – porównuje zaplanowane jednostki z zakładką `Aktywnosci` i aktualizuje kolumny `Status` oraz `Notatka_Trenera`.
- `ai_coach/calendar_reader.py`: **Wyłącznie odczyt** Google Calendar oraz kalendarza Garmin Connect (wykrywa godziny pracy, spotkania oraz sztywne dni siłowni `Gym A` / `Gym B` i inne treningi niebiegowe).
- `ai_coach/rules.py`: Strażnik reguł mikrocyklu (`enforce_fixed_gym_and_max_streak`) – pilnuje nienaruszalności sztywnych sesji siłowych i limitu maksymalnie 3 dni treningowych z rzędu.
- `ai_coach/gemini_client.py`: Klient Gemini i generator kroczącego planu 7-dniowego (TODO-05).
- `ai_coach/garmin_publisher.py`: Zapisuje plan w zakładce `Treningi` (kolumny A–F, gdzie kolumna F to `Garmin_Workout_ID`) oraz publikuje treningi biegowe bezpośrednio do kalendarza Garmin Connect:
  - Jeśli w kalendarzu Garmin jest już trening siłowy (lub inny poza bieganiem) -> pomija ten dzień (`Zaplanowane (Bez biegu)`).
  - Jeśli w kalendarzu Garmin jest już **inny bieg** niż ten należący do `ai_coach` -> **nie usuwa go**, wysyła push Join do Taskera (`garmin_alert=:=data=:=nazwa`) z prośbą o usunięcie starego biegu i ustawia status `Konflikt ⚠️ (Usuń stary bieg w Garminie)`.
- `ai_coach/tools/add_workout.py` i `ai_coach/tools/delete_workout.py`: Narzędzia CLI dla workflowów ręcznego dodawania i usuwania treningów z kalendarza Garmin.

### 3. `calendars_sync/` – Integracja i porządkowanie kalendarzy
- `calendars_sync/main.py` (`python -m calendars_sync.main`): Uruchamia kompletny cykl synchronizacji kalendarzy:
  1. `calendars_sync/organizer.py`: Automatycznie kategoryzuje wydarzenia w Google Calendar, dodaje ikony emoji i nadaje kolory (`colorId`) z palety użytkownika.
  2. `calendars_sync/google_to_garmin.py`: Wykrywa ręcznie wpisane w Google Calendar sesje `Gym A` / `Gym B` (oraz opcjonalny sufiks w nawiasie) i wpisuje je jako zaplanowany trening siłowy `[GCal] Gym A (...)` w kalendarzu Garmin Connect.
  3. `calendars_sync/garmin_to_google.py`: Tworzy w Google Calendar lustrzane wydarzenia `[AI Coach]` dla zaplanowanych treningów z doborem optymalnego wolnego okna czasowego poza pracą i spotkaniami (bez duplikowania ręcznie wpisanej siłowni).

### 4. `common/` – Wspólna infrastruktura
- `config.py`, `google_auth.py`, `sheets.py`, `garmin_auth.py`, `garmin_calendar.py`, `google_calendar.py`, `workout_parser.py`, `athlete_config.py`, `notify.py`.

## Zasady dla agentów Antigravity
1. Nigdy nie używaj `get_all_records()` na zakładce `Wellness` (zawiera dodatkowe kolumny z formułami MA7/MA30 po kolumnie 24) ani `Aktywnosci` (tnij do 25 kolumn). Zawsze używaj `get_all_values()`.
2. Składnia kroków treningowych w kolumnie `Kod Treningu`:
   - Pierwsza linia to zawsze nagłówek: `YYYY-MM-DD Nazwa treningu`.
   - Kolejne linie muszą zaczynać się od `warmup,`, `interval,`, `recovery,` lub `cooldown,`.
   - Biegi spokojne, rozgrzewki (`warmup`) i schłodzenia (`cooldown`) są zawsze planowane na **tętno** (`XXX-YYYbpm`), natomiast akcenty jakościowe (Tempo, Próg, Interwały) w krokach `interval` na **tempo** (`M:SS-M:SS`).
   - Dla dni bez biegania (siłownia, rower, basen, regeneracja) cały `Kod Treningu` ma wartość `REST`.
3. Cykl życia statusów w zakładce `Treningi` (kolumny A–F: `Data`, `Nazwa`, `Kod Treningu`, `Status`, `Notatka_Trenera`, `Garmin_Workout_ID`):
   - `Zaplanowane` / `Zaplanowane (Bez biegu)` / `Do wgrania` -> nadawane przez `ai_coach/garmin_publisher.py` podczas publikacji planu 7-dniowego do Garmin Connect.
   - `Konflikt ⚠️ (Usuń stary bieg w Garminie)` -> nadawany przez `ai_coach/garmin_publisher.py`, gdy w kalendarzu Garmin istnieje obcy bieg (wysyłany jest wówczas alert Join do Taskera).
   - `Zrealizowane ✅...` / `Zmodyfikowane ⚠️...` / `Pominięte ❌` -> nadawane przez `ai_coach/auditor.py` podczas audytu wykonania (TODO-06).
