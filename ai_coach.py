import os
import re
import time
import json
import datetime
import requests
import gspread
from google.oauth2 import service_account
from google.auth.transport.requests import Request

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GEMINI_API_KEY = os.getenv("GEMINI_LLM_API_KEY")
USER_NOTES = os.getenv("USER_NOTES", "Brak dodatkowych uwag, samopoczucie w normie.")
DEFAULT_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", os.getenv("GARMIN_EMAIL", ""))


def get_credentials(scopes):
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("Brak zmiennej GSPREAD_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    return service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)


def get_spreadsheet():
    creds = get_credentials([
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ])
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def safe_float(val, default=None):
    if val is None or val == "":
        return default
    try:
        return float(str(val).replace(",", ".").strip())
    except ValueError:
        return default


def clean_empty_values(data):
    if isinstance(data, list):
        return [clean_empty_values(v) for v in data]
    if isinstance(data, dict):
        return {k: clean_empty_values(v) for k, v in data.items() if v not in ["", None, [], {}]}
    return data


def read_goals_and_strategy(sh):
    """
    Odczytuje zreorganizowaną zakładkę 'Cele_i_Strategia':
    zarówno tabelę Mezocykli, jak i tabelę Konfiguracji, Reguł, Urlopów i Startów.
    """
    ws = sh.worksheet("Cele_i_Strategia")
    rows = ws.get_all_values()

    config = {}
    races = []
    vacations_and_blocks = []
    training_rules = []
    mesocycles = []
    today = datetime.date.today()

    for r in rows:
        if len(r) < 2 or not r[0].strip():
            continue
        col0 = r[0].strip()
        col0_up = col0.upper()

        # Pomijamy wiersze nagłówkowe
        if col0_up in ["MEZOCYKL / FAZA", "TYP_WPISU"]:
            continue

        # 1. Wiersze tabeli Mezocykli
        if col0_up.startswith("MEZOCYKL") or col0_up.startswith("BLOK SPECJALNY"):
            mesocycles.append({
                "faza": col0,
                "okres": r[1].strip() if len(r) > 1 else "",
                "tygodnie": r[2].strip() if len(r) > 2 else "",
                "cel": r[3].strip() if len(r) > 3 else "",
                "objetosc_km": r[4].strip() if len(r) > 4 else "",
                "uklad_tygodnia": r[5].strip() if len(r) > 5 else "",
                "kluczowe_jednostki": r[6].strip() if len(r) > 6 else ""
            })
            continue

        # 2. Wiersze tabeli Konfiguracji / Startów / Urlopów / Reguł
        name = r[1].strip() if len(r) > 1 else ""
        val_or_date = r[2].strip() if len(r) > 2 else ""
        dist = r[3].strip() if len(r) > 3 else ""
        goal = r[4].strip() if len(r) > 4 else ""
        notes = r[5].strip() if len(r) > 5 else ""

        if col0_up == "KONFIGURACJA":
            config[name] = {
                "wartosc": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |")
            }
        elif "START" in col0_up:
            days_left = None
            try:
                race_date = datetime.datetime.strptime(val_or_date[:10], "%Y-%m-%d").date()
                days_left = (race_date - today).days
            except ValueError:
                pass

            if days_left is None or days_left >= -7:
                races.append({
                    "typ": col0_up,
                    "nazwa": name,
                    "data": val_or_date,
                    "dni_do_startu": days_left,
                    "dystans": dist,
                    "cel": goal,
                    "uwagi": notes
                })
        elif any(k in col0_up for k in ["URLOP", "WYJAZD", "NIEDOSTEPNOSC", "PRZERWA"]):
            vacations_and_blocks.append({
                "typ": col0_up,
                "nazwa": name,
                "okres": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |")
            })
        else:
            training_rules.append({
                "kategoria": col0_up,
                "klucz": name,
                "wartosc": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |")
            })

    return config, races, vacations_and_blocks, training_rules, mesocycles


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


# ==============================================================================
# TODO-06: AUTOMATYCZNY AUDYT WYKONANIA TRENINGU (PLAN VS WYKONANIE)
# ==============================================================================
def parse_planned_steps_summary(steps_code):
    if not steps_code or steps_code.strip().upper() == "REST":
        return {"is_run": False, "planned_km": 0.0, "hr_target": None, "pace_target": None}

    total_km = 0.0
    hr_targets = []
    pace_targets = []

    for line in steps_code.splitlines():
        l_strip = line.strip()
        if not any(l_strip.lower().startswith(k) for k in ["warmup", "interval", "recovery", "cooldown"]):
            continue
        m_km = re.search(r"(\d+(?:\.\d+)?)\s*km\b", l_strip, re.IGNORECASE)
        m_m = re.search(r"(\d+)\s*m\b", l_strip, re.IGNORECASE)
        m_hr = re.search(r"(\d+\s*-\s*\d+)\s*bpm", l_strip, re.IGNORECASE)
        m_pace = re.search(r"(\d+:\d{2}\s*-\s*\d+:\d{2})", l_strip)

        if m_km:
            total_km += float(m_km.group(1))
        elif m_m:
            total_km += float(m_m.group(1)) / 1000.0

        if "interval" in l_strip.lower():
            if m_hr:
                hr_targets.append(m_hr.group(1).replace(" ", "") + " bpm")
            if m_pace:
                pace_targets.append(m_pace.group(1).replace(" ", "") + "/km")

    return {
        "is_run": True,
        "planned_km": round(total_km, 2),
        "hr_target": hr_targets[0] if hr_targets else None,
        "pace_target": pace_targets[0] if pace_targets else None
    }


def format_pace_min_km(moving_mins, dist_km):
    if not moving_mins or not dist_km or dist_km <= 0:
        return "brak"
    pace_float = moving_mins / dist_km
    mins = int(pace_float)
    secs = int(round((pace_float - mins) * 60))
    if secs == 60:
        mins += 1
        secs = 0
    return f"{mins}:{secs:02d}/km"


def audit_past_workouts(treningi_sheet, existing_rows, activities_by_date):
    """
    TODO-06: Sprawdza zaplanowane treningi z przeszłości (oraz z dzisiaj, jeśli aktywność już wpadła),
    porównuje je z zakładką 'Aktywnosci' i zapisuje wynik audytu w kolumnach Status i Notatka_Trenera.
    """
    today = datetime.date.today()
    audit_reports = []

    for idx, row in enumerate(existing_rows):
        if len(row) < 4 or not row[0].strip():
            continue
        row_num = idx + 2
        d_str = row[0].strip()
        w_name = row[1].strip() if len(row) > 1 else ""
        w_code = row[2].strip() if len(row) > 2 else ""
        status = row[3].strip() if len(row) > 3 else ""
        coach_note = row[4].strip() if len(row) > 4 else ""

        try:
            w_date = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if w_date > today:
            continue

        # Jeśli wiersz był już wcześniej rozliczony, tylko przekazujemy go do kontekstu AI
        if any(status.startswith(prefix) for prefix in ["Zrealizowane", "Zmodyfikowane", "Pominięte"]):
            if (today - w_date).days <= 7:
                audit_reports.append({"data": d_str, "plan": w_name, "status": status, "notatka": coach_note})
            continue

        day_acts = activities_by_date.get(d_str, [])
        # Jeśli to dzisiejszy dzień i jeszcze nie ma zarejestrowanej aktywności, czekamy do wieczora/jutra
        if w_date == today and not day_acts:
            continue

        planned_info = parse_planned_steps_summary(w_code)
        w_low = w_name.lower()
        new_status = None
        audit_tag = ""

        if planned_info["is_run"]:
            runs = [a for a in day_acts if "running" in str(a.get("Typ", "")).lower()]
            if runs:
                run = runs[0]
                act_km = safe_float(run.get("Dystans_Km"), 0.0)
                act_min = safe_float(run.get("Czas_Ruchu_Min"), safe_float(run.get("Czas_Calkowity_Min"), 0.0))
                act_hr = safe_float(run.get("Srednie_HR"))
                max_hr = safe_float(run.get("Max_HR"))
                act_load = safe_float(run.get("Obciazenie_Treningowe_Load"))
                act_pace = format_pace_min_km(act_min, act_km)

                plan_km = planned_info["planned_km"]
                km_ratio = (act_km / plan_km) if plan_km > 0 else 1.0
                if 0.75 <= km_ratio <= 1.35:
                    new_status = "Zrealizowane ✅"
                else:
                    new_status = "Zmodyfikowane ⚠️"

                target_desc = planned_info["hr_target"] or planned_info["pace_target"] or "wg planu"
                audit_tag = (
                    f"[AUDYT WYKONANIA: Wykonano {act_km} km (plan: {plan_km} km), "
                    f"śr. tempo {act_pace}, śr. HR {int(act_hr) if act_hr else '?'} bpm "
                    f"(max {int(max_hr) if max_hr else '?'} bpm, cel: {target_desc}), "
                    f"Load: {round(act_load, 1) if act_load else '?'}]"
                )
            elif day_acts:
                other_types = ", ".join(str(a.get("Nazwa", a.get("Typ", ""))) for a in day_acts)
                new_status = "Zmodyfikowane ⚠️ (Inna aktywność)"
                audit_tag = f"[AUDYT WYKONANIA: Zamiast biegu wykonano: {other_types}]"
            else:
                new_status = "Pominięte ❌"
                audit_tag = "[AUDYT WYKONANIA: Brak zarejestrowanego biegu w Garminie w tym dniu]"

        else:
            # Planowany był dzień bez biegu (REST: Siłownia, Rower, Basen lub Regeneracja)
            if any(k in w_low for k in ["siłownia", "silownia", "gym", "siła"]):
                gyms = [a for a in day_acts if "strength" in str(a.get("Typ", "")).lower()]
                if gyms:
                    g = gyms[0]
                    dur = safe_float(g.get("Czas_Calkowity_Min"), 0.0)
                    avg_hr = safe_float(g.get("Srednie_HR"))
                    ld = safe_float(g.get("Obciazenie_Treningowe_Load"))
                    new_status = "Zrealizowane ✅ (Siłownia)"
                    audit_tag = f"[AUDYT WYKONANIA: Wykonano {g.get('Nazwa', 'Siłownia')} - czas {round(dur)} min, śr. HR {int(avg_hr) if avg_hr else '?'} bpm, Load {round(ld, 1) if ld else '?'}]"
                elif day_acts:
                    other_types = ", ".join(str(a.get("Nazwa", a.get("Typ", ""))) for a in day_acts)
                    new_status = "Zmodyfikowane ⚠️"
                    audit_tag = f"[AUDYT WYKONANIA: Zamiast siłowni zarejestrowano: {other_types}]"
                else:
                    new_status = "Pominięte ❌"
                    audit_tag = "[AUDYT WYKONANIA: Brak zarejestrowanej sesji siłowej w Garminie]"
            else:
                # Czysty dzień regeneracji lub lekki cross-training
                if not day_acts:
                    new_status = "Zrealizowane ✅ (Regeneracja)"
                    audit_tag = "[AUDYT WYKONANIA: Pełna regeneracja zgodnie z planem]"
                else:
                    other_types = ", ".join(str(a.get("Nazwa", a.get("Typ", ""))) for a in day_acts)
                    new_status = "Zrealizowane ✅ (Aktywna regeneracja)"
                    audit_tag = f"[AUDYT WYKONANIA: Aktywności w dniu bez biegu: {other_types}]"

        if new_status:
            updated_note = f"{coach_note}\n{audit_tag}".strip() if audit_tag not in coach_note else coach_note
            treningi_sheet.update(values=[[new_status, updated_note]], range_name=f"D{row_num}:E{row_num}")
            row[3] = new_status
            row[4] = updated_note
            print(f"Audyt TODO-06 ({d_str} - {w_name}): {new_status}")
            audit_reports.append({"data": d_str, "plan": w_name, "status": new_status, "audyt": audit_tag})

    return audit_reports


def analyze_full_history(wellness_sheet, activities_sheet):
    w_all = wellness_sheet.get_all_values()
    a_all = activities_sheet.get_all_values()
    today = datetime.date.today()

    w_headers = w_all[0][:24] if w_all else []
    w_rows = w_all[1:] if len(w_all) > 1 else []

    rhr_60, rhr_7, hrv_60, hrv_7, sleep_60, sleep_7 = [], [], [], [], [], []
    recent_wellness = []

    for row in w_rows[-90:]:
        padded = row[:24] + [""] * max(0, 24 - len(row))
        d_dict = dict(zip(w_headers, padded))
        try:
            d_date = datetime.datetime.strptime(d_dict.get("Data", ""), "%Y-%m-%d").date()
        except ValueError:
            continue

        days_ago = (today - d_date).days
        rhr = safe_float(d_dict.get("Tetno_Spoczynkowe"))
        hrv = safe_float(d_dict.get("HRV_rMSSD"))
        slp = safe_float(d_dict.get("Sen_Wynik"))

        if 0 <= days_ago <= 60:
            if rhr: rhr_60.append(rhr)
            if hrv: hrv_60.append(hrv)
            if slp: sleep_60.append(slp)
        if 0 <= days_ago <= 7:
            if rhr: rhr_7.append(rhr)
            if hrv: hrv_7.append(hrv)
            if slp: sleep_7.append(slp)

    for row in w_rows[-7:]:
        padded = row[:24] + [""] * max(0, 24 - len(row))
        recent_wellness.append(dict(zip(w_headers, padded)))

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    wellness_summary = {
        "RHR_srednia_7d": avg(rhr_7),
        "RHR_baza_60d": avg(rhr_60),
        "HRV_srednia_7d": avg(hrv_7),
        "HRV_baza_60d": avg(hrv_60),
        "Sen_Wynik_srednia_7d": avg(sleep_7),
        "Sen_Wynik_baza_60d": avg(sleep_60),
    }

    a_headers = a_all[0][:25] if a_all else []
    a_rows = a_all[1:] if len(a_all) > 1 else []

    daily_load = {}
    weekly_stats = {}
    recent_activities = []
    activities_by_date = {}

    for row in a_rows:
        padded = row[:25] + [""] * max(0, 25 - len(row))
        act = dict(zip(a_headers, padded))
        d_str = act.get("Data", "").strip()
        try:
            a_date = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if (today - a_date).days <= 30:
            activities_by_date.setdefault(d_str, []).append(act)

        load = safe_float(act.get("Obciazenie_Treningowe_Load"), 0.0)
        dist = safe_float(act.get("Dystans_Km"), 0.0)
        dur = safe_float(act.get("Czas_Calkowity_Min"), 0.0)
        atype = str(act.get("Typ", "")).lower()

        daily_load[a_date] = daily_load.get(a_date, 0.0) + load

        days_ago = (today - a_date).days
        if 0 <= days_ago <= 84:
            iso_yr, iso_wk, _ = a_date.isocalendar()
            wk_key = f"{iso_yr}-W{iso_wk:02d}"
            if wk_key not in weekly_stats:
                weekly_stats[wk_key] = {"run_km": 0.0, "run_sessions": 0, "gym_sessions": 0, "other_min": 0.0, "total_load": 0.0}
            weekly_stats[wk_key]["total_load"] += load
            if "running" in atype:
                weekly_stats[wk_key]["run_km"] += dist
                weekly_stats[wk_key]["run_sessions"] += 1
            elif "strength" in atype:
                weekly_stats[wk_key]["gym_sessions"] += 1
            else:
                weekly_stats[wk_key]["other_min"] += dur

    ctl, atl = 0.0, 0.0
    for i in range(180, -1, -1):
        d = today - datetime.timedelta(days=i)
        ld = daily_load.get(d, 0.0)
        ctl += (ld - ctl) * (1.0 / 42.0)
        atl += (ld - atl) * (1.0 / 7.0)

    tsb = ctl - atl
    acwr = round(atl / ctl, 2) if ctl > 5 else 1.0

    for row in a_rows[-12:]:
        padded = row[:25] + [""] * max(0, 25 - len(row))
        recent_activities.append(dict(zip(a_headers, padded)))

    sorted_weeks = dict(sorted(weekly_stats.items())[-8:])
    for k in sorted_weeks:
        sorted_weeks[k]["run_km"] = round(sorted_weeks[k]["run_km"], 1)
        sorted_weeks[k]["other_min"] = round(sorted_weeks[k]["other_min"], 0)
        sorted_weeks[k]["total_load"] = round(sorted_weeks[k]["total_load"], 0)

    load_metrics = {
        "CTL_Forma_Przewlekla_42d": round(ctl, 1),
        "ATL_Zmeczenie_Ostre_7d": round(atl, 1),
        "TSB_Bilans_Swiezosci": round(tsb, 1),
        "ACWR_Wskaznik_Ryzyka_Kontuzji": acwr,
        "Objetosc_Ostatnie_8_Tygodni": sorted_weeks
    }

    return wellness_summary, recent_wellness, load_metrics, recent_activities, activities_by_date


def ensure_treningi_headers(treningi_sheet):
    expected = ["Data", "Nazwa", "Kod Treningu", "Status", "Notatka_Trenera"]
    all_values = treningi_sheet.get_all_values()
    if not all_values:
        treningi_sheet.append_row(expected)
        return []
    if all_values[0][:4] != expected[:4]:
        treningi_sheet.clear()
        treningi_sheet.append_row(expected)
        return []
    if len(all_values[0]) < 5:
        treningi_sheet.update_cell(1, 5, "Notatka_Trenera")
    return all_values[1:]


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



def get_dynamic_high_end_models():
    excluded = [
        "lite", "gemma", "tts", "image", "vision", "embedding",
        "transcribe", "robotics", "lyria", "banana", "computer-use",
        "customtools", "clip", "nano", "antigravity", "deep-research", "omni"
    ]
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        models_data = r.json().get("models", [])
        scored = []

        for m in models_data:
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            name = m["name"].replace("models/", "")
            n_low = name.lower()

            if not n_low.startswith("gemini-"):
                continue
            if any(bad in n_low for bad in excluded):
                continue

            ver_match = re.search(r"gemini-(\d+(?:\.\d+)?)", n_low)
            if ver_match:
                version = float(ver_match.group(1))
                if version < 3.0:
                    continue
            else:
                version = 3.5

            if "argon" in n_low or "ultra" in n_low:
                tier = 4
            elif "pro" in n_low:
                tier = 3
            elif "flash" in n_low:
                tier = 2
            else:
                tier = 1

            is_stable = 0 if ("preview" in n_low or "exp" in n_low) else 1
            scored.append(((tier, version, is_stable), name))

        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = [name for _, name in scored]
        if ranked:
            return ranked
    except Exception as e:
        print(f"Błąd pobierania katalogu modeli: {e}")

    return ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-flash-latest", "gemini-3.5-flash"]


def parse_json_response(raw_text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned)


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


def is_rest_day_entry(workout_name, steps_code):
    """Sprawdza, czy dany dzień w planie jest całkowitym dniem odpoczynku (Rest Day)."""
    w_low = str(workout_name).lower()
    s_up = str(steps_code).strip().upper()
    if s_up != "REST" and not s_up.startswith("REST"):
        return False
    # Jeśli steps == REST, sprawdzamy, czy w nazwie nie kryje się siłownia, rower lub basen
    active_non_run_keywords = ["siłownia", "silownia", "gym", "siła", "rower", "gravel", "basen", "pływanie", "swim"]
    if any(k in w_low for k in active_non_run_keywords):
        return False
    return True


def enforce_fixed_gym_and_max_streak(seven_day_plan, fixed_gym_days, activities_by_date, today_date):
    """
    Twardy strażnik w Pythonie:
    1. Gwarantuje, że dni z ręcznie wpisanym Gym A / Gym B w Google Calendar są ustawione jako sztywna Siłownia.
    2. Pilnuje zasady: NIGDY więcej niż 3 dni treningowe z rzędu (4. dzień automatycznie staje się Rest Day),
       chroniąc także dzień przed sztywną siłownią, gdyby siłownia miała być 4. dniem z rzędu.
    """
    # Krok 1: Obliczamy, ile dni treningowych z rzędu było do dzisiaj włącznie
    initial_streak = 0
    for back_offset in range(0, 4):
        d_check = (today_date - datetime.timedelta(days=back_offset)).isoformat()
        acts = activities_by_date.get(d_check, [])
        # Liczymy dzień jako treningowy, jeśli była zarejestrowana aktywność biegowa/siłowa/kolarska/pływacka
        real_acts = [a for a in acts if str(a.get("Typ", "")).lower() not in ["walking", "breathwork", "meditation"]]
        if real_acts:
            initial_streak += 1
        else:
            if back_offset == 0:
                # Jeśli dzisiaj jeszcze nie było treningu, sprawdzamy od wczoraj
                continue
            break

    # Krok 2: Nakładamy sztywne dni siłowni z Google Calendar
    plan_by_date = {item["date"]: item for item in seven_day_plan if "date" in item}
    sorted_dates = sorted(plan_by_date.keys())

    for d_str in sorted_dates:
        if d_str in fixed_gym_days:
            cal_title = fixed_gym_days[d_str]
            plan_by_date[d_str]["workout_name"] = f"Siłownia ({cal_title})"
            plan_by_date[d_str]["steps"] = "REST"
            plan_by_date[d_str]["is_fixed_gym"] = True
        else:
            plan_by_date[d_str]["is_fixed_gym"] = False

    # Krok 3: Walidacja maksymalnie 3 dni treningowych z rzędu
    streak = initial_streak
    for i, d_str in enumerate(sorted_dates):
        item = plan_by_date[d_str]
        is_rest = is_rest_day_entry(item["workout_name"], item["steps"])

        if is_rest:
            streak = 0
            continue

        # Sprawdzamy, czy po tym dniu następują sztywne dni siłowni, które przekroczyłyby limit 3 dni
        future_fixed_streak = 0
        for j in range(i + 1, min(i + 4, len(sorted_dates))):
            if plan_by_date[sorted_dates[j]]["is_fixed_gym"]:
                future_fixed_streak += 1
            else:
                break

        if (streak + 1 > 3) or (not item["is_fixed_gym"] and (streak + 1 + future_fixed_streak > 3)):
            if not item["is_fixed_gym"]:
                print(f"[STRAŻNIK REGUŁY 3 DNI] Zamieniam {d_str} ({item['workout_name']}) na Rest Day (ciąg wyniósłby >3 dni).")
                item["workout_name"] = "Dzień Regeneracji (Rest Day)"
                item["steps"] = "REST"
                item["coach_memory_note"] = (
                    f"[Automatyczna korekta: zasada max 3 dni treningowych z rzędu] "
                    f"Pełny odpoczynek dostosowany do sztywnego grafiku siłowni w Google Calendar."
                )
                streak = 0
            else:
                streak += 1
        else:
            streak += 1

    return [plan_by_date[d] for d in sorted_dates]


# ==============================================================================
# TODO-05: GENERATOR I ADAPTATOR KROCZĄCEGO PLANU 7-DNIOWEGO
# ==============================================================================
def ask_holistic_7day_coach(context_payload, horizon_days):
    if not GEMINI_API_KEY:
        raise ValueError("Brak klucza GEMINI_LLM_API_KEY!")

    compact_context = clean_empty_values(context_payload)

    prompt = f"""Jesteś elitarnym, holistycznym trenerem personalnym AI (bieganie długodystansowe, przygotowanie siłowe Gym A/B, gravel, basen) prowadzącym zawodnika długofalowo.

ZADANIE (TODO-05 + TODO-06):
1. Przeanalizuj raport wykonania ostatnich treningów (`audyt_wykonania_planu_TODO_06`), trendy HRV/RHR/Snu, wskaźniki CTL/ATL/ACWR, plan mezocykli z `Cele_i_Strategia` oraz grafik w Google Calendar.
2. Zaplanuj lub zaadaptuj KROCZĄCY PLAN 7-DNIOWY dla następujących dat:
{json.dumps(horizon_days, ensure_ascii=False)}

PEŁNY KONTEKST ZAWODNIKA (JSON):
{json.dumps(compact_context, ensure_ascii=False)}

BEZWZGLĘDNE WYTYCZNE TRENERSKIE:
1. STABILNOŚĆ PLANU VS ADAPTACJA:
   - Jeśli na dany dzień w `obecnie_zaplanowane_7_dni` istnieje już trening i nie koliduje on z nowym wydarzeniem w Google Calendar, a regeneracja (HRV/Sen) oraz uwagi zawodnika są w normie -> ZACHOWAJ dotychczasową koncepcję i parametry tego dnia, aby nie zmieniać planu bez powodu.
   - Jeśli jednak w Google Calendar pojawiła się kolizja (np. wpisana ręcznie siłownia `gym B` w piątek lub `gym A` w poniedziałek), spadło HRV lub wczoraj pominięto jednostkę -> ZAADAPTUJ rozkład dni w tygodniu!
2. BIEGI SPOKOJNE NA TĘTNO (BPM), AKCENTY NA TEMPO (MIN/KM):
   - Dla WSZYSTKICH biegów spokojnych (Easy Run, Bieg Tlenowy, Recovery, spokojny Long Run) oraz dla rozgrzewek (`warmup`) i schłodzeń (`cooldown`) ZAWSZE podawaj cel jako ZAKRES TĘTNA w formacie `XXX-YYYbpm` (np. `warmup, 1km, 115-132bpm`, `interval, 4km, 125-145bpm`, `cooldown, 1km, 115-132bpm`). NIGDY nie podawaj tempa min/km dla biegów spokojnych!
   - Wyłącznie dla biegów jakościowych (Tempo HM, Próg, Interwały VO2max, Przebieżki) podawaj w odcinkach głównych (`interval`) widełki tempa `M:SS-M:SS` (np. `interval, 2km, 4:10-4:20`).
3. SZTYWNA SIŁOWNIA Z KALENDARZA I ZASADA MAX 3 DNI TRENINGOWYCH Z RZĘDU (NAJWAŻNIEJSZE!):
   - Zawodnik sam wpisuje sobie do Google Calendar sesje siłowe (`gym A`, `gym B` - umówione z dziewczyną). Te dni masz podane w polu `sztywne_dni_silowni_z_kalendarza`. Są one NIENARUSZALNE – w te dni zawsze planuj tę siłownię (`steps: "REST"`), nigdy bieg.
   - NADRZĘDNA ZASADA WSZYSTKIEGO: NIGDY NIE PLANUJ WIĘCEJ NIŻ 3 DNI TRENINGOWE Z RZĘDU (wliczając w to bieganie, siłownię, rower i basen)!
   - Jeżeli wypadałby 4. dzień treningowy z rzędu (lub gdyby zaplanowanie biegu sprawiło, że kolejnego dnia sztywna siłownia z kalendarza stałaby się 4. dniem z rzędu), automatycznie wstaw w ten dzień pełny odpoczynek: `workout_name: "Dzień Regeneracji (Rest Day)"` oraz `steps: "REST"`.
4. SKŁADNIA PARSERA GARMINA (DLA DNI BIEGOWYCH):
   Każdy krok w osobnej linii zaczynający się od: `warmup`, `interval`, `recovery`, `cooldown`. Bez zapisu pętli typu "4x" (rozpisz każde powtórzenie w osobnej linii).

Zwróć odpowiedź WYŁĄCZNIE jako czysty obiekt JSON w formacie:
{{
  "weekly_strategy_summary": "Krótkie podsumowanie strategii na najbliższe 7 dni oraz wnioski z audytu ostatnich treningów (2-3 zdania)",
  "seven_day_plan": [
    {{
      "date": "YYYY-MM-DD",
      "workout_name": "Krótka nazwa treningu",
      "steps": "wieloliniowy kod kroków dla Garmina LUB słowo REST",
      "coach_memory_note": "Zwięzłe uzasadnienie jednostki na ten dzień (1-2 zdania)"
    }}
  ]
}}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2
        }
    }

    active_models = get_dynamic_high_end_models()
    permanently_blocked = set()

    max_wait_seconds = 900
    start_time = time.time()
    round_num = 1

    while (time.time() - start_time) < max_wait_seconds:
        models_to_try = [m for m in active_models if m not in permanently_blocked]
        if not models_to_try:
            permanently_blocked.clear()
            models_to_try = list(active_models)

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            print(f"[Runda {round_num}] Generowanie 7-dniowego planu przez model: {model_name}...")

            try:
                response = requests.post(url, json=payload, timeout=120)
                if response.status_code == 200:
                    data = response.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = parse_json_response(raw_text)
                    print(f"SUKCES! Plan 7-dniowy wygenerowany przez model: {model_name}.")
                    return parsed
                elif response.status_code == 429:
                    if "limit: 0" in response.text or "limit:0" in response.text:
                        permanently_blocked.add(model_name)
                elif response.status_code in [400, 404]:
                    permanently_blocked.add(model_name)
                elif response.status_code in [500, 502, 503, 504]:
                    time.sleep(6)
            except Exception as e:
                print(f"Błąd przy modelu {model_name}: {e}")

        time.sleep(min(15 * round_num, 45))
        round_num += 1

    raise RuntimeError("Przekroczono limit oczekiwania na odpowiedź modeli Gemini.")


def normalize_steps_only(code_str):
    if not code_str:
        return ""
    lines = [l.strip() for l in code_str.strip().splitlines() if l.strip()]
    if not lines:
        return ""
    if lines[0].upper() == "REST":
        return "REST"
    if re.match(r"^\d{4}-\d{2}-\d{2}\b", lines[0]):
        return "\n".join(lines[1:]).strip()
    return "\n".join(lines).strip()


def main():
    print("Łączenie z ekosystemem Google Sheets...")
    sh = get_spreadsheet()

    wellness_sheet = sh.worksheet("Wellness")
    activities_sheet = sh.worksheet("Aktywnosci")
    treningi_sheet = sh.worksheet("Treningi")

    athlete_config, races_schedule, vacations_and_blocks, training_rules, mesocycles = read_goals_and_strategy(sh)
    cal_email = athlete_config.get("Kalendarz_Email", {}).get("wartosc", DEFAULT_CALENDAR_ID)
    guest_email = athlete_config.get("Gosc_Treningu_Email", {}).get("wartosc", "")

    print("Pobieranie grafiku z Google Calendar na 10 dni...")
    calendar_events, _ = fetch_calendar_context(cal_email, days_ahead=10)

    print("Wyliczanie wskaźników CTL/ATL/ACWR i trendów wieloletnich...")
    wellness_summary, recent_wellness, load_metrics, recent_activities, activities_by_date = analyze_full_history(
        wellness_sheet, activities_sheet
    )

    existing_rows = ensure_treningi_headers(treningi_sheet)

    # 1. TODO-06: Automatyczny audyt wykonania przeszłych i dzisiejszych treningów
    print("Wykonywanie audytu Plan vs Wykonanie (TODO-06)...")
    audit_reports = audit_past_workouts(treningi_sheet, existing_rows, activities_by_date)

    # 2. TODO-05: Przygotowanie horyzontu 7-dniowego (od jutra przez 7 dni)
    today = datetime.date.today()
    days_pl = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
    horizon_days = []
    for offset in range(1, 8):
        d = today + datetime.timedelta(days=offset)
        horizon_days.append({"date": d.isoformat(), "day_of_week": days_pl[d.weekday()]})

    existing_by_date = {}
    for idx, r in enumerate(existing_rows):
        if r and r[0].strip():
            existing_by_date[r[0].strip()] = {
                "row_num": idx + 2,
                "name": r[1].strip() if len(r) > 1 else "",
                "code": r[2].strip() if len(r) > 2 else "",
                "status": r[3].strip() if len(r) > 3 else "",
                "note": r[4].strip() if len(r) > 4 else ""
            }

    currently_planned_7d = []
    for hd in horizon_days:
        dt_str = hd["date"]
        if dt_str in existing_by_date:
            ex = existing_by_date[dt_str]
            currently_planned_7d.append({
                "date": dt_str,
                "workout_name": ex["name"],
                "steps": normalize_steps_only(ex["code"]),
                "status": ex["status"],
                "coach_memory_note": ex["note"]
            })

    context_payload = {
        "dzisiejsza_data": today.isoformat(),
        "uwagi_zawodnika_dzis": USER_NOTES,
        "konfiguracja_zawodnika": athlete_config,
        "plan_mezocykli": mesocycles,
        "reguly_i_preferencje_treningowe": training_rules,
        "urlopy_i_niedostepnosci": vacations_and_blocks,
        "kalendarz_startow_wieloletni": races_schedule,
        "wydarzenia_google_calendar_10_dni": calendar_events,
        "audyt_wykonania_planu_TODO_06": audit_reports,
        "obecnie_zaplanowane_7_dni": currently_planned_7d,
        "wskazniki_obciazenia_CTL_ATL_ACWR": load_metrics,
        "trendy_wellness_7d_vs_60d": wellness_summary,
        "ostatnie_7_dni_wellness": recent_wellness,
        "ostatnie_12_aktywnosci": recent_activities
    }

    ai_response = ask_holistic_7day_coach(context_payload, horizon_days)
    seven_day_plan = ai_response.get("seven_day_plan", [])
    weekly_summary = ai_response.get("weekly_strategy_summary", "")
    if weekly_summary:
        print(f"Strategia tygodnia AI: {weekly_summary}")

    # 3. Zapis i inteligentna adaptacja 7 dni w Arkuszu oraz w Google Calendar
    for day_item in seven_day_plan:
        target_date = str(day_item.get("date", "")).strip()
        if not target_date:
            continue

        workout_name = str(day_item.get("workout_name", "Trening AI")).strip()
        steps_raw = str(day_item.get("steps", "REST")).strip()
        coach_note = str(day_item.get("coach_memory_note", "")).strip()

        is_rest = (steps_raw.upper() == "REST" or steps_raw.upper().splitlines()[0] == "REST")
        if is_rest:
            full_workout_code = "REST"
            clean_new_steps = "REST"
        else:
            clean_new_steps = normalize_steps_only(steps_raw)
            full_workout_code = f"{target_date} {workout_name}\n{clean_new_steps}"

        if target_date in existing_by_date:
            ex = existing_by_date[target_date]
            old_steps = normalize_steps_only(ex["code"])
            old_name = ex["name"]

            # Sprawdzamy, czy AI zmieniło strukturę kroków lub dyscyplinę względem istniejącego wpisu
            steps_changed = (old_steps != clean_new_steps) or (old_name != workout_name)

            if not steps_changed and ex["status"].startswith("Zaplanowane"):
                print(f"[{target_date}] Plan bez zmian ({workout_name}) - zachowuję status '{ex['status']}'.")
                continue

            status_flag = "Do aktualizacji" if (not is_rest or old_steps != "REST") else "Zaplanowane (Bez biegu)"
            row_values = [target_date, workout_name, full_workout_code, status_flag, coach_note]
            treningi_sheet.update(values=[row_values], range_name=f"A{ex['row_num']}:E{ex['row_num']}")
            print(f"[{target_date}] ZAADAPTOWANO trening -> {workout_name} (Status: {status_flag})")
        else:
            status_flag = "Zaplanowane (Bez biegu)" if is_rest else "Do wgrania"
            row_values = [target_date, workout_name, full_workout_code, status_flag, coach_note]
            treningi_sheet.append_row(row_values)
            print(f"[{target_date}] DODANO nowy trening -> {workout_name} (Status: {status_flag})")

        sync_workout_to_google_calendar(cal_email, target_date, workout_name, clean_new_steps, coach_note, guest_email)


if __name__ == "__main__":
    main()