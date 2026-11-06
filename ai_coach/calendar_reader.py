"""
TYLKO ODCZYT kalendarzy dla `ai_coach`:
- Czyta Google Calendar (aby znać godziny pracy, spotkania oraz wpisane ręcznie sesje Gym A / Gym B).
- Czyta kalendarz Garmin Connect (aby widzieć już zaplanowane treningi siłowe / inne aktywności oraz obce biegi).
- Nie wykonuje żadnego zapisu do Google Calendar.
"""
import datetime

from common.config import AI_COACH_TAG, GCAL_TAG
from common.garmin_calendar import get_planned_workouts, group_by_date
from common.google_calendar import event_date, is_gym_title, is_relevant_for_me, list_events, strip_leading_icon


def fetch_calendar_context(calendar_id, days_ahead=10):
    """Pobiera wyłącznie odczyt wydarzeń z Google Calendar na najbliższe `days_ahead` dni."""
    if not calendar_id or "@" not in calendar_id:
        return [], []

    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        raw_items = list_events(calendar_id, now, now + datetime.timedelta(days=days_ahead), max_results=100)
        events_summary = []

        for ev in raw_items:
            summary = ev.get("summary", "Zajęty termin")
            if AI_COACH_TAG in summary or "AI Coach]" in summary:
                continue
            if not is_relevant_for_me(ev):
                continue

            s_low = summary.lower()
            transparency = ev.get("transparency", "opaque")
            start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            end = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))

            if "biuro" in s_low:
                tag = "[PRACA Z BIURA - trening możliwy rano lub po 17:30]"
            elif is_gym_title(s_low):
                tag = "[WPISANA SIŁOWNIA W KALENDARZU]"
            elif transparency == "transparent":
                tag = "[INFORMACYJNE - nie blokuje treningu]"
            else:
                tag = "[ZAJĘTY TERMIN]"

            events_summary.append(f"{start[:16]} -> {end[:16]}: {summary} {tag}")

        return events_summary, raw_items
    except Exception as e:
        return [f"Błąd odczytu kalendarza: {e}"], []


def extract_fixed_gym_days(raw_calendar_items, garmin_planned_by_date=None):
    """
    Zwraca słownik `{YYYY-MM-DD: nazwa_treningu}` dla dni, których AI Coach nie może nadpisać biegiem:
    1. Ręcznie wpisane sesje siłowe (`Gym A` / `Gym B` i opcjonalny sufiks w nawiasie) w Google Calendar.
    2. Zaplanowane już w kalendarzu Garmin Connect treningi niebiegowe (np. siłownia, rower, basen).
    """
    fixed_days = {}
    for ev in raw_calendar_items or []:
        summary = str(ev.get("summary", "")).strip()
        if "ai coach]" in summary.lower():
            continue
        if is_gym_title(summary):
            d_str = event_date(ev)
            if d_str:
                fixed_days[d_str] = strip_leading_icon(summary)

    for d_str, workouts in (garmin_planned_by_date or {}).items():
        for w in workouts:
            if not w.get("is_run", True):
                clean_title = w.get("title", "").replace(GCAL_TAG, "").strip() or f"Trening ({w.get('sport', 'inny')})"
                fixed_days.setdefault(d_str, clean_title)

    return fixed_days


def read_garmin_calendar_window(garmin_client, days_ahead=10):
    """Zwraca zgrupowane po dacie zaplanowane treningi z kalendarza Garmin Connect na najbliższe `days_ahead` dni."""
    today = datetime.date.today()
    end_date = today + datetime.timedelta(days=days_ahead)
    try:
        workouts = get_planned_workouts(garmin_client, today, end_date)
        return group_by_date(workouts)
    except Exception as e:
        print(f"Uwaga: nie udało się odczytać kalendarza Garmin ({e}).")
        return {}
