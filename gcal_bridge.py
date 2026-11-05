import os
import re
import json
import datetime
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request


def get_credentials(scopes):
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("Brak zmiennej GSPREAD_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    return service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)


def fetch_calendar_context(calendar_id, days_ahead=10):
    """Pobiera wyłącznie odczyt wydarzeń z Google Calendar (kolorowaniem zajmuje się calendar_organizer.py)."""
    if not calendar_id or "@" not in calendar_id:
        return [], []

    try:
        creds = get_credentials(["https://www.googleapis.com/auth/calendar"])
        creds.refresh(Request())
        headers = {"Authorization": f"Bearer {creds.token}"}

        now = datetime.datetime.now(datetime.timezone.utc)
        time_min = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (now + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

        base_url = f"https://www.googleapis.com/calendar/v3/calendars/{requests.utils.quote(calendar_id)}/events"
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 100
        }
        r = requests.get(base_url, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            return [f"Kalendarz niedostępny (kod {r.status_code})."], []

        raw_items = r.json().get("items", [])
        events_summary = []

        for ev in raw_items:
            summary = ev.get("summary", "Zajęty termin")
            if "AI Coach]" in summary:
                continue

            is_self_organizer = ev.get("organizer", {}).get("self", False)
            attendees = ev.get("attendees", [])
            my_status = "accepted"
            for att in attendees:
                if att.get("self"):
                    my_status = att.get("responseStatus", "needsAction")
                    break

            if not is_self_organizer and my_status != "accepted":
                continue

            s_low = summary.lower()
            transparency = ev.get("transparency", "opaque")
            start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            end = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))

            if "biuro" in s_low:
                tag = "[PRACA Z BIURA - trening możliwy rano lub po 17:30]"
            elif any(k in s_low for k in ["gym", "siłownia", "silownia"]):
                tag = "[WPISANA SIŁOWNIA W KALENDARZU]"
            elif transparency == "transparent":
                tag = "[INFORMACYJNE - nie blokuje treningu]"
            else:
                tag = "[ZAJĘTY TERMIN]"

            events_summary.append(f"{start[:16]} -> {end[:16]}: {summary} {tag}")

        return events_summary, raw_items
    except Exception as e:
        return [f"Błąd odczytu kalendarza: {e}"], []


def extract_fixed_gym_days(raw_calendar_items):
    """
    Wykrywa dni, w których użytkownik sam wpisał siłownię (Gym A / Gym B) w Google Calendar.
    Są to dni SZTYWNE (umówione z dziewczyną), których AI nie może nadpisać biegiem.
    """
    fixed_gym = {}
    for ev in raw_calendar_items:
        summary = str(ev.get("summary", "")).strip()
        s_low = summary.lower()
        if "ai coach]" in s_low:
            continue
        if any(k in s_low for k in ["gym", "siłownia", "silownia"]):
            start_str = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))[:10]
            if start_str:
                fixed_gym[start_str] = summary
    return fixed_gym


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

        is_self = ev.get("organizer", {}).get("self", False)
        attendees = ev.get("attendees", [])
        my_status = "accepted"
        for att in attendees:
            if att.get("self"):
                my_status = att.get("responseStatus", "accepted")
                break
        if not is_self and my_status != "accepted":
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
    Zapisuje lub aktualizuje wydarzenie [AI Coach] w Google Calendar zgodnie z nową paletą:
    - Lekarze: 2 (Jasnozielony / Szałwia) - w calendar_organizer.py
    - Bieganie: 10 (Ciemnozielony / Bazylia)
    - Rower: 6 (Pomarańczowy / Mandarynka)
    - Basen: 7 (Niebieski / Paw)
    - Siłownia: 11 (Czerwony / Pomidor)
    - Regeneracja / Informacyjne: 8 (Szary / Grafit)
    """
    if not calendar_id or "@" not in calendar_id:
        return

    try:
        creds = get_credentials(["https://www.googleapis.com/auth/calendar"])
        creds.refresh(Request())
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json"
        }

        base_url = f"https://www.googleapis.com/calendar/v3/calendars/{requests.utils.quote(calendar_id)}/events"
        next_day = (datetime.datetime.strptime(target_date, "%Y-%m-%d").date() + datetime.timedelta(days=1)).isoformat()

        params = {
            "timeMin": f"{target_date}T00:00:00Z",
            "timeMax": f"{next_day}T00:00:00Z",
            "singleEvents": True
        }
        r_list = requests.get(base_url, headers=headers, params=params, timeout=15)
        items_on_day = r_list.json().get("items", []) if r_list.status_code == 200 else []

        # Usuwamy poprzedni wpis [AI Coach] z tego dnia przed aktualizacją
        for item in items_on_day:
            if "AI Coach]" in str(item.get("summary", "")):
                ev_id = item.get("id")
                requests.delete(f"{base_url}/{ev_id}", headers=headers, timeout=10)

        w_low = workout_name.lower()
        is_pure_rest = False

        # Dobór koloru i ikony wg dyscypliny + ochrona przed duplikatem ręcznie wpisanej siłowni
        if any(k in w_low for k in ["siłownia", "silownia", "gym", "siła"]):
            for item in items_on_day:
                s_item = str(item.get("summary", "")).lower()
                if "ai coach]" not in s_item and any(g in s_item for g in ["gym", "siłownia", "silownia"]):
                    print(f"W Google Calendar na {target_date} istnieje już ręczny wpis '{item.get('summary')}' - pomijam duplikat.")
                    return
            color_id = "11"  # Czerwony (Pomidor) - Siłownia
            icon = "🏋️"
        elif any(k in w_low for k in ["basen", "pływanie", "swim"]):
            color_id = "7"   # Niebieski (Paw) - Basen
            icon = "🏊"
        elif any(k in w_low for k in ["rower", "gravel", "bike", "kolars"]):
            color_id = "6"   # Pomarańczowy (Mandarynka) - Rower
            icon = "🚴"
        elif steps_code.upper() == "REST" or any(k in w_low for k in ["regeneracja", "wolne", "odpoczynek"]):
            color_id = "8"   # Szary (Grafit) - Regeneracja / Informacyjne
            icon = "🧘"
            is_pure_rest = True
        else:
            color_id = "10"  # Ciemnozielony (Bazylia) - Bieganie
            icon = "🏃"

        event_body = {
            "summary": f"{icon} [AI Coach] {workout_name}",
            "description": f"Kroki treningu:\n{steps_code}\n\nAnaliza trenera AI:\n{coach_note}",
            "colorId": color_id
        }

        if is_pure_rest:
            event_body["start"] = {"date": target_date}
            event_body["end"] = {"date": next_day}
            event_body["transparency"] = "transparent"
        else:
            dur_mins = estimate_workout_duration_minutes(steps_code)
            start_dt, end_dt = find_optimal_workout_slot(items_on_day, target_date, dur_mins)
            event_body["start"] = {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Europe/Warsaw"}
            event_body["end"] = {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Europe/Warsaw"}

        if guest_email and "@" in guest_email and not is_pure_rest:
            event_body["attendees"] = [{"email": guest_email.strip()}]

        r_ins = requests.post(base_url, headers=headers, json=event_body, timeout=15)
        if r_ins.status_code == 403 and "attendees" in event_body:
            event_body.pop("attendees", None)
            r_ins = requests.post(base_url, headers=headers, json=event_body, timeout=15)

        if r_ins.status_code in [200, 201]:
            print(f"Zapisano w Google Calendar ({target_date}): {icon} [AI Coach] {workout_name} (colorId={color_id})")
        else:
            print(f"Uwaga: Google Calendar zwrócił kod {r_ins.status_code}: {r_ins.text[:200]}")
    except Exception as e:
        print(f"Błąd zapisu do Google Calendar ({target_date}): {e}")
