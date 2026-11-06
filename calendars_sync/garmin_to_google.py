"""
Synchronizacja Kalendarz Garmin Connect / Arkusz Treningi -> Google Calendar:
- Tworzy lustrzane wydarzenia `[AI Coach]` w Google Calendar dla zaplanowanych dni treningowych.
- Dobiera optymalne wolne okno godzinowe poza godzinami pracy/spotkaniami.
- Unika duplikatów dla ręcznie wpisanych sesji siłowych (`Gym A` / `Gym B`).
"""
import datetime
import re

import requests

from common.athlete_config import load_konfiguracja, resolve_calendar_id
from common.config import AI_COACH_TAG, SHEET_TRAININGS, TIMEZONE
from common.google_auth import calendar_events_url, calendar_headers, get_spreadsheet
from common.google_calendar import is_gym_title, is_relevant_for_me


def estimate_workout_duration_minutes(steps_code):
    if not steps_code or steps_code.upper() == "REST":
        return 60
    total_min = 0.0
    for line in steps_code.splitlines():
        m_min = re.search(r"(\d+(?:\.\d+)?)\s*min", line, re.IGNORECASE)
        m_sec = re.search(r"(\d+)\s*s(?:ek)?\b", line, re.IGNORECASE)
        m_km = re.search(r"(\d+(?:\.\d+)?)\s*km", line, re.IGNORECASE)
        m_m = re.search(r"(\d+)\s*m\b", line, re.IGNORECASE)
        if m_min:
            total_min += float(m_min.group(1))
        elif m_sec:
            total_min += float(m_sec.group(1)) / 60.0
        elif m_km:
            total_min += float(m_km.group(1)) * 5.5
        elif m_m:
            total_min += (float(m_m.group(1)) / 1000.0) * 5.0
    return max(45, int(round(total_min + 15, -1)))


def find_optimal_workout_slot(items_on_day, target_date_str, duration_mins):
    target_dt = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
    is_weekend = target_dt.weekday() >= 5

    busy_intervals = []
    work_end_dt = None

    for ev in items_on_day:
        summary = str(ev.get("summary", "")).lower()
        if "ai coach]" in summary:
            continue
        if not is_relevant_for_me(ev):
            continue

        start_str = ev.get("start", {}).get("dateTime", "")
        end_str = ev.get("end", {}).get("dateTime", "")
        if not start_str or not end_str:
            continue

        try:
            s_dt = datetime.datetime.fromisoformat(start_str[:19])
            e_dt = datetime.datetime.fromisoformat(end_str[:19])
        except ValueError:
            continue

        if any(k in summary for k in ["czas pracy", "biuro", "work time", "praca"]):
            work_end_dt = e_dt + datetime.timedelta(minutes=30)
            busy_intervals.append((s_dt, e_dt))
        elif ev.get("transparency", "opaque") != "transparent":
            busy_intervals.append((s_dt, e_dt))

    busy_intervals.sort(key=lambda x: x[0])

    if is_weekend:
        candidate_start = datetime.datetime.combine(target_dt, datetime.time(9, 0))
    else:
        candidate_start = work_end_dt if work_end_dt else datetime.datetime.combine(target_dt, datetime.time(17, 30))

    latest_start = datetime.datetime.combine(target_dt, datetime.time(21, 0))
    while candidate_start <= latest_start:
        candidate_end = candidate_start + datetime.timedelta(minutes=duration_mins)
        collision = False
        for b_start, b_end in busy_intervals:
            if candidate_start < b_end and candidate_end > b_start:
                candidate_start = b_end + datetime.timedelta(minutes=20)
                collision = True
                break
        if not collision:
            break

    return candidate_start, candidate_start + datetime.timedelta(minutes=duration_mins)


def sync_workout_to_google_calendar(calendar_id, target_date, workout_name, steps_code, coach_note, guest_email=""):
    """
    Zapisuje lub aktualizuje wydarzenie [AI Coach] w Google Calendar zgodnie z paletą kolorów:
    - Bieganie: 10 (Ciemnozielony / Bazylia)
    - Rower: 6 (Pomarańczowy / Mandarynka)
    - Basen: 7 (Niebieski / Paw)
    - Siłownia: 11 (Czerwony / Pomidor)
    - Regeneracja / Informacyjne: 8 (Szary / Grafit)
    """
    if not calendar_id or "@" not in calendar_id:
        return

    try:
        headers = calendar_headers()
        base_url = calendar_events_url(calendar_id)
        next_day = (datetime.datetime.strptime(target_date, "%Y-%m-%d").date() + datetime.timedelta(days=1)).isoformat()

        params = {
            "timeMin": f"{target_date}T00:00:00Z",
            "timeMax": f"{next_day}T00:00:00Z",
            "singleEvents": True,
        }
        r_list = requests.get(base_url, headers=headers, params=params, timeout=15)
        items_on_day = r_list.json().get("items", []) if r_list.status_code == 200 else []

        for item in items_on_day:
            if "AI Coach]" in str(item.get("summary", "")):
                ev_id = item.get("id")
                requests.delete(f"{base_url}/{ev_id}", headers=headers, timeout=10)

        w_low = workout_name.lower()
        is_pure_rest = False

        if any(k in w_low for k in ["siłownia", "silownia", "gym", "siła"]):
            for item in items_on_day:
                s_item = str(item.get("summary", ""))
                if "ai coach]" not in s_item.lower() and is_gym_title(s_item):
                    print(f"W Google Calendar na {target_date} istnieje już ręczny wpis '{s_item}' - pomijam duplikat.")
                    return
            color_id = "11"
            icon = "🏋️"
        elif any(k in w_low for k in ["basen", "pływanie", "swim"]):
            color_id = "7"
            icon = "🏊"
        elif any(k in w_low for k in ["rower", "gravel", "bike", "kolars"]):
            color_id = "6"
            icon = "🚴"
        elif steps_code.upper() == "REST" or any(k in w_low for k in ["regeneracja", "wolne", "odpoczynek"]):
            color_id = "8"
            icon = "🧘"
            is_pure_rest = True
        else:
            color_id = "10"
            icon = "🏃"

        event_body = {
            "summary": f"{icon} {AI_COACH_TAG} {workout_name}",
            "description": f"Kroki treningu:\n{steps_code}\n\nAnaliza trenera AI:\n{coach_note}",
            "colorId": color_id,
        }

        if is_pure_rest:
            event_body["start"] = {"date": target_date}
            event_body["end"] = {"date": next_day}
            event_body["transparency"] = "transparent"
        else:
            dur_mins = estimate_workout_duration_minutes(steps_code)
            start_dt, end_dt = find_optimal_workout_slot(items_on_day, target_date, dur_mins)
            event_body["start"] = {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": TIMEZONE}
            event_body["end"] = {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": TIMEZONE}

        if guest_email and "@" in guest_email and not is_pure_rest:
            event_body["attendees"] = [{"email": guest_email.strip()}]

        r_ins = requests.post(base_url, headers=headers, json=event_body, timeout=15)
        if r_ins.status_code == 403 and "attendees" in event_body:
            event_body.pop("attendees", None)
            r_ins = requests.post(base_url, headers=headers, json=event_body, timeout=15)

        if r_ins.status_code in [200, 201]:
            print(f"Zapisano w Google Calendar ({target_date}): {icon} {AI_COACH_TAG} {workout_name} (colorId={color_id})")
        else:
            print(f"Uwaga: Google Calendar zwrócił kod {r_ins.status_code}: {r_ins.text[:200]}")
    except Exception as e:
        print(f"Błąd zapisu do Google Calendar ({target_date}): {e}")


def _strip_header_line(code_str):
    if not code_str:
        return "REST"
    lines = [l.strip() for l in code_str.strip().splitlines() if l.strip()]
    if not lines or lines[0].upper() == "REST":
        return "REST"
    if re.match(r"^\d{4}-\d{2}-\d{2}\b", lines[0]):
        return "\n".join(lines[1:]).strip() or "REST"
    return "\n".join(lines).strip()


def mirror_garmin_workouts_to_google(garmin_client=None, spreadsheet=None, days_ahead=7):
    """Odzwierciedla aktualnie zaplanowane dni (z zakładki Treningi / Garmina) na kolejne `days_ahead` dni w Google Calendar."""
    sh = spreadsheet or get_spreadsheet()
    konfig = load_konfiguracja(sh)
    cal_id = resolve_calendar_id(konfig)
    guest_email = konfig.get("Gosc_Treningu_Email", "")
    if not cal_id or "@" not in cal_id:
        print("Pominięto Garmin -> Google: brak poprawnego adresu kalendarza Google.")
        return

    try:
        rows = sh.worksheet(SHEET_TRAININGS).get_all_values()
    except Exception as e:
        print(f"Nie udało się odczytać zakładki {SHEET_TRAININGS}: {e}")
        return

    today = datetime.date.today()
    max_date = today + datetime.timedelta(days=days_ahead)

    for r in rows[1:]:
        if len(r) < 3 or not r[0].strip():
            continue
        d_str = r[0].strip()
        try:
            dt = datetime.date.fromisoformat(d_str)
        except ValueError:
            continue
        if not (today <= dt <= max_date):
            continue

        w_name = r[1].strip() if len(r) > 1 else "Trening"
        w_code = _strip_header_line(r[2])
        status = r[3].strip() if len(r) > 3 else ""
        note = r[4].strip() if len(r) > 4 else ""

        if status.lower().startswith("konflikt"):
            continue

        sync_workout_to_google_calendar(cal_id, d_str, w_name, w_code, note, guest_email)


def main():
    mirror_garmin_workouts_to_google()


if __name__ == "__main__":
    main()
