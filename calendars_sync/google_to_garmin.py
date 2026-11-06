"""
Synchronizacja Google Calendar -> Kalendarz Garmin Connect:
- Wykrywa ręcznie wpisane sesje siłowe w Google Calendar (np. 'Gym A', 'Gym B (nogi)').
- Wpisuje je jako zaplanowany trening siłowy `[GCal] Gym A (...)` w kalendarzu Garmin Connect (jeśli w danym dniu nie ma jeszcze zaplanowanego treningu siłowego),
  dzięki czemu kalendarz Garmin Connect zawiera kompletny obraz nadchodzącego tygodnia, a ai_coach automatycznie omija te dni przy planowaniu biegania.
- Ukończone treningi z LiftTrack trafiają bezpośrednio jako aktywności do Garmin Connect i są pobierane przez collector/activities.py.
"""
import datetime

from common.athlete_config import load_konfiguracja, resolve_calendar_id
from common.config import AI_COACH_TAG, GCAL_TAG
from common.garmin_auth import GarminAuthenticator
from common.garmin_calendar import get_planned_workouts, group_by_date, upload_and_schedule
from common.google_auth import get_spreadsheet
from common.google_calendar import event_date, is_gym_title, is_relevant_for_me, list_events, strip_leading_icon
from common.workout_parser import build_strength_workout


def sync_gym_events_to_garmin(garmin_client=None, spreadsheet=None, days_ahead=10):
    sh = spreadsheet or get_spreadsheet()
    konfig = load_konfiguracja(sh)
    cal_id = resolve_calendar_id(konfig)
    if not cal_id or "@" not in cal_id:
        print("Pominięto Google -> Garmin: brak poprawnego adresu kalendarza Google.")
        return {}

    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        gcal_items = list_events(cal_id, now, now + datetime.timedelta(days=days_ahead))
    except Exception as e:
        print(f"Błąd odczytu Google Calendar podczas synchronizacji siłowni: {e}")
        return {}

    gym_by_date = {}
    for ev in gcal_items:
        summary = str(ev.get("summary", "")).strip()
        if not summary or AI_COACH_TAG in summary:
            continue
        if not is_relevant_for_me(ev):
            continue
        if is_gym_title(summary):
            d_str = event_date(ev)
            if d_str:
                gym_by_date[d_str] = strip_leading_icon(summary)

    if not gym_by_date:
        print("Brak ręcznie wpisanych sesji siłowych (Gym A/B) w Google Calendar na najbliższe dni.")
        return {}

    client = garmin_client or GarminAuthenticator().login()
    today = datetime.date.today()
    end_date = today + datetime.timedelta(days=days_ahead)
    existing_by_date = group_by_date(get_planned_workouts(client, today, end_date))

    synced = {}
    for d_str, clean_title in sorted(gym_by_date.items()):
        try:
            target_dt = datetime.date.fromisoformat(d_str)
        except ValueError:
            continue
        if target_dt < today:
            continue

        day_workouts = existing_by_date.get(d_str, [])
        already_has_strength = any(
            (not w["is_run"]) or GCAL_TAG in w["title"] or is_gym_title(w["title"])
            for w in day_workouts
        )
        if already_has_strength:
            print(f"[{d_str}] W kalendarzu Garmin istnieje już trening niebiegowy/siłowy – pomijam kopiowanie '{clean_title}'.")
            synced[d_str] = clean_title
            continue

        workout_name = f"{GCAL_TAG} {clean_title}"
        try:
            payload = build_strength_workout(workout_name, description=f"Sesja siłowa z Google Calendar: {clean_title}")
            upload_and_schedule(client, payload, d_str)
            synced[d_str] = clean_title
        except Exception as e:
            print(f"Uwaga: nie udało się zapisać sesji siłowej '{workout_name}' w kalendarzu Garmin ({d_str}): {e}")

    return synced


def main():
    sync_gym_events_to_garmin()


if __name__ == "__main__":
    main()
