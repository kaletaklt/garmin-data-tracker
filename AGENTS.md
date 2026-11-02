# Architektura Systemu: Garmin AI Personal Coach (`garmin-data-tracker`)

## Cel projektu
Autonomiczny system trenerski łączący Garmin Connect, Google Sheets, Google Calendar, Tasker oraz modele Gemini 4 Argon / Antigravity.

## Struktura modułów
- `wellness_collector.py`: Pobiera statystyki snu, HRV, RHR, Body Battery, stresu i kroków z ostatnich 7 dni do zakładki `Wellness`.
- `activity_collector.py`: Pobiera 20 ostatnich aktywności i aktualizuje ostatnie 7 dni w zakładce `Aktywnosci`.
- `ai_coach.py`: Silnik fizjologiczny i decyzyjny. Wylicza CTL (42d), ATL (7d), TSB, ACWR, bazę 60d HRV/RHR, czyta cele wieloletnie z zakładki `Cele_i_Strategia`, pobiera grafik z Google Calendar API i planuje trening w zakładce `Treningi`.
- `sync_calendar.py`: Parsuje kody treningów ze statusami `Do wgrania` oraz `Do aktualizacji` i wysyła je do kalendarza Garmin Connect.
- `add_workout.py`: Parser kroków treningowych (`warmup`, `interval`, `recovery`, `cooldown`) na format JSON Garmin ExecutableStepDTO.

## Zasady dla agentów Antigravity
1. Nigdy nie używaj `get_all_records()` na zakładce `Wellness` (zawiera dodatkowe kolumny z formułami MA7/MA30 po kolumnie 24). Zawsze używaj `get_all_values()` i tnij do 24 kolumn.
2. Składnia kroków treningowych w kolumnie `Kod Treningu`:
   - Pierwsza linia to zawsze nagłówek: `YYYY-MM-DD Nazwa treningu` (pomijany przez `lines[1:]` w `sync_calendar.py`).
   - Kolejne linie muszą zaczynać się od `warmup,`, `interval,`, `recovery,` lub `cooldown,`.
   - Dla dni bez biegania (siłownia / odpoczynek) cały `Kod Treningu` ma wartość `REST`.
