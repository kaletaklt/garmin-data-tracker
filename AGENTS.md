# Architektura Systemu: Garmin AI Personal Coach (`garmin-data-tracker`)

## Cel projektu
Autonomiczny system trenerski łączący Garmin Connect, Google Sheets, Google Calendar, Tasker oraz Gemini / Antigravity.

## Struktura modułów
- `wellness_collector.py`: Pobiera statystyki snu, HRV, RHR, Body Battery, stresu i kroków z ostatnich 7 dni do zakładki `Wellness`.
- `activity_collector.py`: Pobiera 20 ostatnich aktywności i aktualizuje ostatnie 7 dni w zakładce `Aktywnosci`.
- `ai_coach.py`: Punkt wejścia i orkiestrator silnika trenerskiego (`main()` oraz obsługa arkusza `Treningi`: `get_credentials`, `get_spreadsheet`, `ensure_treningi_headers`, `normalize_steps_only`), integrujący 4 moduły pomocnicze:
  - `coach_analytics.py`: Analityka fizjologiczna i odczyt strategii (`analyze_full_history`, `read_goals_and_strategy`, `safe_float`) – wylicza CTL (42d), ATL (7d), TSB, ACWR, bazę 60d HRV/RHR/Snu, statystyki objętości z 8 tygodni oraz odczytuje zakładkę `Cele_i_Strategia` (tabela Mezocykli oraz tabela Konfiguracji, Reguł, Urlopów i Startów).
  - `coach_auditor.py`: Audyt wykonania treningów (TODO-06) oraz strażnik reguł mikrocyklu (`audit_past_workouts`, `parse_planned_steps_summary`, `format_pace_min_km`, `enforce_fixed_gym_and_max_streak`, `is_rest_day_entry`) – porównuje zaplanowane jednostki z zakładką `Aktywnosci`, aktualizuje kolumny `Status` i `Notatka_Trenera` oraz wymusza sztywne sesje siłowe z Google Calendar i zasadę maksymalnie 3 dni treningowych z rzędu.
  - `gcal_bridge.py`: Integracja z Google Calendar (`fetch_calendar_context`, `extract_fixed_gym_days`, `estimate_workout_duration_minutes`, `find_optimal_workout_slot`, `sync_workout_to_google_calendar`) – pobiera grafik na 10 dni, wykrywa sztywne sesje siłowe (`gym A`/`gym B`), dobiera optymalne okna czasowe poza godzinami pracy/spotkaniami i synchronizuje wydarzenia `[AI Coach]`.
  - `gemini_client.py`: Klient LLM i generator planu 7-dniowego (TODO-05) (`get_dynamic_high_end_models`, `ask_holistic_7day_coach`, `parse_json_response`, `clean_empty_values`) – dynamicznie wybiera najwyższy dostępny model Gemini i generuje/adaptuje kroczący plan 7-dniowy.
- `log_subjective.py`: Zapisuje subiektywne raporty samopoczucia (energia, RPE, DOMS, dyskomfort) do zakładki `Dziennik_Subiektywny` i opcjonalnie wyzwala natychmiastową adaptację planu (`ai_coach.py` + `sync_calendar.py`).
- `sync_calendar.py`: Parsuje kody treningów ze statusami `Do wgrania` oraz `Do aktualizacji` i wysyła je do kalendarza Garmin Connect (oraz czyści wycofane treningi biegowe zamienione na `REST`).
- `calendar_organizer.py`: Automatycznie kategoryzuje, porządkuje tytuły, dodaje ikony i przypisuje spójną paletę kolorów (`colorId`) wydarzeniom w Google Calendar.
- `add_workout.py`: Parser kroków treningowych (`warmup`, `interval`, `recovery`, `cooldown`) na format JSON Garmin ExecutableStepDTO.

## Zasady dla agentów Antigravity
1. Nigdy nie używaj `get_all_records()` na zakładce `Wellness` (zawiera dodatkowe kolumny z formułami MA7/MA30 po kolumnie 24) ani `Aktywnosci` (tnij do 25 kolumn). Zawsze używaj `get_all_values()`.
2. Składnia kroków treningowych w kolumnie `Kod Treningu`:
   - Pierwsza linia to zawsze nagłówek: `YYYY-MM-DD Nazwa treningu` (pomijany przez `lines[1:]` w `sync_calendar.py`).
   - Kolejne linie muszą zaczynać się od `warmup,`, `interval,`, `recovery,` lub `cooldown,`.
   - Biegi spokojne, rozgrzewki (`warmup`) i schłodzenia (`cooldown`) są zawsze planowane na **tętno** (`XXX-YYYbpm`), natomiast akcenty jakościowe (Tempo, Próg, Interwały) w krokach `interval` na **tempo** (`M:SS-M:SS`).
   - Dla dni bez biegania (siłownia, rower, basen, regeneracja) cały `Kod Treningu` ma wartość `REST`.
3. Cykl życia statusów w zakładce `Treningi`:
   - `Do wgrania` / `Do aktualizacji` / `Zaplanowane (Bez biegu)` -> nadawane przez `ai_coach.py` podczas generowania i adaptacji planu 7-dniowego (TODO-05).
   - `Zaplanowane` -> nadawane przez `sync_calendar.py` po pomyślnym przesłaniu treningu biegowego do Garmin Connect.
   - `Zrealizowane ✅...` / `Zmodyfikowane ⚠️...` / `Pominięte ❌` -> nadawane przez `coach_auditor.py` (`audit_past_workouts`) podczas audytu wykonania (TODO-06).
