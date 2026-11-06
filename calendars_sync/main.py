"""
Punkt wejścia modułu `calendars_sync`:
1. Porządkuje Google Calendar (ikony, tytuły, kolory z palety użytkownika).
2. Kopiuje ręcznie wpisane sesje siłowe (`Gym A` / `Gym B`) z Google Calendar do kalendarza Garmin Connect.
3. Tworzy w Google Calendar lustrzane wydarzenia `[AI Coach]` dla treningów zaplanowanych w Garmin Connect / arkuszu `Treningi`.
"""
from calendars_sync.garmin_to_google import mirror_garmin_workouts_to_google
from calendars_sync.google_to_garmin import sync_gym_events_to_garmin
from calendars_sync.organizer import organize_google_calendar
from common.athlete_config import load_konfiguracja, resolve_calendar_id
from common.garmin_auth import GarminAuthenticator
from common.google_auth import get_spreadsheet


def main():
    sh = get_spreadsheet()
    konfig = load_konfiguracja(sh)
    cal_id = resolve_calendar_id(konfig)

    print("=== KROK 1/3: Organizacja i kolorowanie wydarzeń w Google Calendar ===")
    if cal_id and "@" in cal_id:
        organize_google_calendar(calendar_id=cal_id)

    print("=== KROK 2/3: Synchronizacja sesji siłowych Google Calendar -> Garmin Connect ===")
    garmin_client = GarminAuthenticator().login()
    sync_gym_events_to_garmin(garmin_client=garmin_client, spreadsheet=sh)

    print("=== KROK 3/3: Lustrzana synchronizacja planu Garmin Connect -> Google Calendar ===")
    mirror_garmin_workouts_to_google(garmin_client=garmin_client, spreadsheet=sh)


if __name__ == "__main__":
    main()
