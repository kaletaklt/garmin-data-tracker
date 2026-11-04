def estimate_workout_duration_minutes(steps_code):
    """Szacuje czas trwania treningu w minutach na podstawie kroków."""
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
            total_min += float(m_km.group(1)) * 5.5  # średnio 5:30/km
        elif m_m:
            total_min += (float(m_m.group(1)) / 1000.0) * 5.0
    return max(45, int(round(total_min + 15, -1)))  # +15 min na rozgrzewkę/prysznic


def find_optimal_workout_slot(items_on_day, target_date_str, duration_mins):
    """
    Dobiera optymalną godzinę treningu:
    - Pn-Pt: po zakończeniu wydarzenia 'Czas pracy' / 'Biuro' (+30 min buforu), domyślnie 17:30.
    - Sob-Niedz: nie wcześniej niż o 09:00, z ominięciem kolizji w kalendarzu.
    """
    target_dt = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
    is_weekend = target_dt.weekday() >= 5

    busy_intervals = []
    work_end_hour_min = None

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

        if any(k in summary for k in ["czas pracy", "biuro", "praca", "work"]):
            work_end_hour_min = e_dt + datetime.timedelta(minutes=30)
            busy_intervals.append((s_dt, e_dt))
        elif ev.get("transparency", "opaque") != "transparent":
            busy_intervals.append((s_dt, e_dt))

    busy_intervals.sort(key=lambda x: x[0])

    if is_weekend:
        candidate_start = datetime.datetime.combine(target_dt, datetime.time(9, 0))
    else:
        if work_end_hour_min:
            candidate_start = work_end_hour_min
        else:
            candidate_start = datetime.datetime.combine(target_dt, datetime.time(17, 30))

    # Szukamy pierwszego wolnego okna bez kolizji ze spotkaniami
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
    Zapisuje trening w Google Calendar o wyliczonej godzinie, z nowymi kolorami i opcjonalnym zaproszeniem gościa.
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

        for item in items_on_day:
            if "AI Coach]" in str(item.get("summary", "")):
                ev_id = item.get("id")
                requests.delete(f"{base_url}/{ev_id}", headers=headers, timeout=10)

        w_low = workout_name.lower()
        is_pure_rest = False

        if any(k in w_low for k in ["siłownia", "silownia", "gym", "siła"]):
            color_id = "4"   # Kwiat wiśni / Flaming - Siłownia
            icon = "🏋️"
        elif any(k in w_low for k in ["basen", "pływanie", "swim"]):
            color_id = "7"   # Paw - Basen
            icon = "🏊"
        elif any(k in w_low for k in ["rower", "gravel", "bike", "kolars"]):
            color_id = "9"   # Jagodowy - Rower
            icon = "🚴"
        elif steps_code.upper() == "REST" or any(k in w_low for k in ["regeneracja", "wolne", "odpoczynek"]):
            color_id = "8"   # Grafit - Informacyjne / Regeneracja
            icon = "🧘"
            is_pure_rest = True
        else:
            color_id = "10"  # Bazyliowy - Bieganie
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
            print("Konto usługi nie ma uprawnień do wysyłania zaproszeń e-mail - zapisuję wydarzenie bez pola 'attendees'...")
            event_body.pop("attendees", None)
            r_ins = requests.post(base_url, headers=headers, json=event_body, timeout=15)

        if r_ins.status_code in [200, 201]:
            print(f"Zapisano w Google Calendar ({target_date}): {icon} [AI Coach] {workout_name}")
        else:
            print(f"Uwaga: Google Calendar zwrócił kod {r_ins.status_code}: {r_ins.text[:200]}")
    except Exception as e:
        print(f"Błąd zapisu do Google Calendar: {e}")
