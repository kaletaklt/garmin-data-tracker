# Garmin AI Personal Coach (`garmin-data-tracker`)

Autonomiczny system trenerski łączący **Garmin Connect**, **Google Sheets**, **Google Calendar**, **Tasker** oraz **Google Gemini**.

## Architektura (3 moduły domenowe)

```text
garmin-data-tracker/
├── collector/          # 1. Zbieranie danych z zegarka (Wellness + Aktywności), ankiet RPE/Energii i detekcja anomalii
├── ai_coach/           # 2. Mózg operacji: analityka CTL/ATL, audyt wykonania, plan 7-dniowy Gemini i zapis do Garmin Connect
├── calendars_sync/     # 3. Integracja kalendarzy: Google <-> Garmin Connect oraz auto-organizer kolorów i ikon
└── common/             # Współdzielona infrastruktura (autoryzacja, parser kroków, API Garmin/Google)
```

### Uruchamianie modułów
- **Poranny collect (Wellness + ankieta poranna + warunkowy replan przy anomaliach):**
  ```bash
  python -m collector.morning
  ```
- **Collect po aktywności (Aktywności + ankieta RPE + audyt / warunkowy replan):**
  ```bash
  python -m collector.post_activity
  ```
- **AI Coach (Planowanie 7-dniowe i bezpośredni zapis do kalendarza Garmin Connect):**
  ```bash
  python -m ai_coach.main
  ```
- **Synchronizacja i organizacja kalendarzy (Google Calendar <-> Garmin Connect):**
  ```bash
  python -m calendars_sync.main
  ```
