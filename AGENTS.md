# Architektura Systemu: Garmin AI Personal Coach (`garmin-data-tracker`)

## Cel projektu
Autonomiczny system trenerski łączący Garmin Connect, Google Sheets, Google Calendar, Tasker oraz Gemini / Antigravity.

## Struktura modułów
- `wellness_collector.py`: Pobiera statystyki snu, HRV, RHR, Body Battery, stresu i kroków z ostatnich 7 dni do zakładki `Wellness`.
- `activity_collector.py`: Pobiera 20 ostatnich aktywności i aktualizuje ostatnie 7 dni w zakładce `Aktywnosci`.
- `ai_coach.py`: Silnik fizjologiczny i decyzyjny:
  - Wylicza CTL (42d), ATL (7d), TSB, ACWR, bazę 60d HRV/RHR/Snu oraz statystyki objętości z 8 tygodni.
  - Odczytuje zreorganizowaną zakładkę `Cele_i_Strategia` (tabela Mezocykli oraz tabela Konfiguracji, Reguł, Urlopów i Startów).
  - **TODO-06 (Automatyczny audyt wykonania treningu – Plan vs Wykonanie)**: Funkcja `audit_past_workouts()` porównuje zaplanowane jednostki z przeszłości (oraz z dzisiaj, jeśli aktywność już spłynęła) z zakładką `Aktywnosci` i aktualizuje kolumny `Status` (`Zrealizowane ✅`, `Zmodyfikowane ⚠️`, `Pominięte ❌`) oraz `Notatka_Trenera` (dopisuje tag `[AUDYT WYKONANIA: ...]`).
  - **TODO-05 (Generator i adaptator kroczącego planu 7-dniowego)**: Funkcja `ask_holistic_7day_coach()` planuje i adaptuje horyzont 7 kolejnych dni. Zachowuje stabilność istniejącego planu, o ile nie pojawiła się kolizja w Google Calendar (np. ręcznie wpisana siłownia `gym A`/`gym B`), spadek HRV lub pominięty trening.
  - Synchronizuje zaplanowane jednostki z Google Calendar (`sync_workout_to_google_calendar`), unikając duplikatów dla ręcznie wpisanych sesji siłowych i dobierając optymalne okno czasowe poza godzinami pracy/spotkaniami.
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
   - `Zrealizowane ✅...` / `Zmodyfikowane ⚠️...` / `Pominięte ❌` -> nadawane przez `ai_coach.py` podczas audytu wykonania (TODO-06).
