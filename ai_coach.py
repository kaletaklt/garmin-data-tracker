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
        return {k: clean_empty_values(v) for k, v in data.items() if v not in ["", None]}
    return data


def ensure_goals_sheet(sh):
    """
    Odczytuje wszystkie wpisy użytkownika z zakładki 'Cele_i_Strategia' (w tym URLOP, REGULA_TRENINGOWA,
    PREFERENCJE_TYGODNIA, START_ROZWAZANY, UWAGA_STRATEGICZNA) i dopisuje nowe szablony, jeśli ich brakuje.
    """
    try:
        ws = sh.worksheet("Cele_i_Strategia")
        rows = ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Cele_i_Strategia", rows=60, cols=6)
        rows = [["Typ_Wpisu", "Nazwa / Klucz", "Data_lub_Wartosc", "Dystans / Dyscyplina", "Cel_Wynikowy", "Priorytet / Uwagi"]]
        ws.update(values=rows, range_name="A1")

    existing_keys = {r[1].strip() for r in rows[1:] if len(r) > 1 and r[1].strip()}
    template_additions = [
        ["REGULA_TRENINGOWA", "Biegi_Spokojne_HR", "Tylko Tętno (BPM)", "Z1/Rozgrzewka: 115-132bpm, Z2/Easy: 125-145bpm", "Zakaz podawania tempa dla Easy Run", "Wszystkie biegi Easy, Recovery i spokojne Long Run muszą mieć cel w bpm"],
        ["REGULA_TRENINGOWA", "Biegi_Jakosciowe_Tempo", "Tempo (min/km)", "Tempo HM: 4:10-4:20/km, Interwały: 3:50-4:05/km", "Sterowanie tempem na akcentach", "Dla biegów progowych i interwałów używaj widełek min/km"],
        ["PREFERENCJE_TYGODNIA", "Rozklad_Dyscyplin", "2-3x Siłownia (Gym A/B), 3x Bieg", "Przeplatanie: Rower / Basen", "Elastyczna rotacja bodźców", "Wplataj rower lub basen jako trening uzupełniający/regeneracyjny"],
        ["START_ROZWAZANY", "Wpisz rozważane zawody", "2027-06-15", "Bieg / Triathlon / Gravel", "Cel orientacyjny", "Status: Rozważam - AI weźmie pod uwagę w strategii"],
        ["UWAGA_STRATEGICZNA", "Miejsce na Twoje pomysły", "Aktywne", "Wskazówka dla AI", "Analiza długoterminowa", "Dopisz tu dowolny wiersz (np. KONTUZJA, POMYSL, URLOP), a AI go uwzględni"]
    ]
    new_rows_to_append = [t for t in template_additions if t[1] not in existing_keys]
    if new_rows_to_append:
        for tr in new_rows_to_append:
            ws.append_row(tr)
            rows.append(tr)

    config = {}
    races = []
    vacations_and_blocks = []
    training_rules_and_ideas = []
    today = datetime.date.today()

    for r in rows[1:]:
        if len(r) < 2 or not r[0].strip():
            continue
        entry_type = r[0].strip().upper()
        name = r[1].strip()
        val_or_date = r[2].strip() if len(r) > 2 else ""
        dist = r[3].strip() if len(r) > 3 else ""
        goal = r[4].strip() if len(r) > 4 else ""
        notes = r[5].strip() if len(r) > 5 else ""

        if name == "Wpisz rozważane zawody":
            continue

        if entry_type == "KONFIGURACJA":
            config[name] = {
                "wartosc": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |")
            }
        elif "START" in entry_type:
            days_left = None
            phase = "Planowanie długoterminowe"
            try:
                race_date = datetime.datetime.strptime(val_or_date[:10], "%Y-%m-%d").date()
                days_left = (race_date - today).days
                weeks_left = round(days_left / 7, 1)
                if days_left < 0:
                    phase = "Zakończony"
                elif weeks_left <= 2:
                    phase = "Tapering (Ostrzenie formy / redukcja objętości)"
                elif weeks_left <= 6:
                    phase = "Peak (Szczyt formy / specyfika startowa)"
                elif weeks_left <= 12:
                    phase = "Build (Rozbudowa wytrzymałości tempowej i progowej)"
                else:
                    phase = "Base (Budowa bazy tlenowej, siły i ekonomii biegu)"
            except ValueError:
                pass

            if days_left is None or days_left >= -7:
                races.append({
                    "typ": entry_type,
                    "nazwa": name,
                    "data": val_or_date,
                    "dni_do_startu": days_left,
                    "faza_makrocyklu": phase,
                    "dystans": dist,
                    "cel": goal,
                    "uwagi": notes
                })
        elif any(k in entry_type for k in ["URLOP", "WYJAZD", "NIEDOSTEPNOSC", "PRZERWA"]):
            vacations_and_blocks.append({
                "typ": entry_type,
                "nazwa": name,
                "okres": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |")
            })
        else:
            training_rules_and_ideas.append({
                "kategoria": entry_type,
                "klucz": name,
                "wartosc": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |")
            })

    return config, races, vacations_and_blocks, training_rules_and_ideas


def auto_color_and_fetch_calendar(calendar_id, days_ahead=10):
    """
    1. Automatycznie nadaje kolory wydarzeniom w Google Calendar wg słów kluczowych (rozszerzenie auto-kolorujące).
    2. Filtruje wydarzenia wg reguł:
       - Ignoruje wydarzenia innych organizatorów, gdzie Twój status != 'accepted' (np. Terapia ze statusem 'tentative').
       - Rozpoznaje 'Biuro' jako ramy pracy stacjonarnej.
    """
    if not calendar_id or "@" not in calendar_id:
        return ["Brak skonfigurowanego adresu Kalendarza Google."]

    try:
        creds = get_credentials(["https://www.googleapis.com/auth/calendar"])
        creds.refresh(Request())
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json"
        }

        now = datetime.datetime.now(datetime.timezone.utc)
        time_min = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (now + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

        base_url = f"https://www.googleapis.com/calendar/v3/calendars/{requests.utils.quote(calendar_id)}/events"
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 80
        }
        r = requests.get(base_url, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            return [f"Kalendarz niedostępny (kod {r.status_code})."]

        items = r.json().get("items", [])
        events_summary = []

        for ev in items:
            summary = ev.get("summary", "Zajęty termin")
            if summary.startswith("[AI Coach]") or "AI Coach]" in summary:
                continue

            ev_id = ev.get("id")
            current_color = ev.get("colorId", "")
            s_low = summary.lower()

            # --- AUTO-COLORING WG TWOJEJ PALETY ---
            desired_color = None
            if "biuro" in s_low:
                desired_color = "5"   # Bananowy (Biuro)
            elif any(k in s_low for k in ["praca", "work", "call", "daily"]):
                desired_color = "9"   # Jagodowy (Czas pracy)
            elif any(k in s_low for k in ["lekarz", "odczulanie", "dentysta", "badania", "ortopeda", "fizjo"]):
                desired_color = "4"   # Flamingowy (Lekarze)
            elif any(k in s_low for k in ["urlop", "wyjazd", "lot ", "rzym", "wakacje"]):
                desired_color = "11"  # Pomidorowy (Urlopy/Wyjazdy)
            elif any(k in s_low for k in ["terapia", "claudia", "kwiatuszek"]):
                desired_color = "7"   # Pawi / Baby Blue (Informacyjne / Claudia)
            elif any(k in s_low for k in ["spotkanie", "kolacja", "randka", "kino", "urodziny"]):
                desired_color = "3"   # Winogronowy (Spotkania)

            if desired_color and current_color != desired_color and ev.get("organizer", {}).get("self", False):
                try:
                    requests.patch(
                        f"{base_url}/{ev_id}",
                        headers=headers,
                        json={"colorId": desired_color},
                        timeout=8
                    )
                except Exception:
                    pass

            # --- FILTROWANIE DLA AI COACHA ---
            is_self_organizer = ev.get("organizer", {}).get("self", False)
            attendees = ev.get("attendees", [])
            my_status = "accepted"
            for att in attendees:
                if att.get("self"):
                    my_status = att.get("responseStatus", "needsAction")
                    break

            # Jeśli organizatorem jest ktoś inny, a Ty nie kliknąłeś "Tak" (np. Terapia = tentative/declined), ignorujemy
            if not is_self_organizer and my_status != "accepted":
                continue

            transparency = ev.get("transparency", "opaque")
            start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            end = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))

            if "biuro" in s_low:
                tag = "[PRACA Z BIURA - trening możliwy rano lub po 17:30]"
            elif transparency == "transparent":
                tag = "[WYDARZENIE INFORMACYJNE - nie blokuje treningu]"
            else:
                tag = "[ZAJĘTY TERMIN]"

            events_summary.append(f"{start[:16]} -> {end[:16]}: {summary} {tag}")

        return events_summary if events_summary else ["Brak zaplanowanych wydarzeń na najbliższe dni."]
    except Exception as e:
        return [f"Nie udało się pobrać kalendarza: {e}"]


def sync_workout_to_google_calendar(calendar_id, target_date, workout_name, steps_code, coach_note):
    """
    Zapisuje trening w Google Calendar z zasadą: 1 dyscyplina = 1 stały kolor:
    - Bieganie: Bazyliowy (10)
    - Siłownia: Grafitowy (8)
    - Rower / Gravel: Mandarynkowy (6)
    - Basen / Pływanie: Szałwiowy (2)
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
        if r_list.status_code == 200:
            for item in r_list.json().get("items", []):
                if "AI Coach]" in str(item.get("summary", "")):
                    ev_id = item.get("id")
                    requests.delete(f"{base_url}/{ev_id}", headers=headers, timeout=10)

        w_low = workout_name.lower()
        if any(k in w_low for k in ["siłownia", "gym", "siła", "strength"]):
            color_id = "8"   # Grafitowy - Siłownia
            icon = "🏋️"
        elif any(k in w_low for k in ["rower", "gravel", "bike", "kolars"]):
            color_id = "6"   # Mandarynkowy - Rower
            icon = "🚴"
        elif any(k in w_low for k in ["basen", "pływanie", "swim"]):
            color_id = "2"   # Szałwiowy - Basen
            icon = "🏊"
        elif steps_code.upper() == "REST" or any(k in w_low for k in ["regeneracja", "wolne", "rest"]):
            color_id = "7"   # Pawi (Baby Blue) - Regeneracja
            icon = "🧘"
        else:
            color_id = "10"  # Bazyliowy - Bieganie
            icon = "🏃"

        event_body = {
            "summary": f"{icon} [AI Coach] {workout_name}",
            "description": f"Kroki treningu:\n{steps_code}\n\nAnaliza trenera AI:\n{coach_note}",
            "start": {"date": target_date},
            "end": {"date": next_day},
            "colorId": color_id,
            "transparency": "transparent"
        }
        r_ins = requests.post(base_url, headers=headers, json=event_body, timeout=15)
        if r_ins.status_code in [200, 201]:
            print(f"Zapisano w Google Calendar ({target_date}): {icon} [AI Coach] {workout_name} (Kolor ID: {color_id})")
        else:
            print(f"Uwaga: Google Calendar zwrócił kod {r_ins.status_code} przy zapisie.")
    except Exception as e:
        print(f"Błąd zapisu do Google Calendar: {e}")


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

    for row in a_rows:
        padded = row[:25] + [""] * max(0, 25 - len(row))
        act = dict(zip(a_headers, padded))
        try:
            a_date = datetime.datetime.strptime(act.get("Data", ""), "%Y-%m-%d").date()
        except ValueError:
            continue

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

    return wellness_summary, recent_wellness, load_metrics, recent_activities


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
        print(f"Dynamiczny ranking najlepszych modeli: {ranked}")
        if ranked:
            return ranked
    except Exception as e:
        print(f"Błąd pobierania katalogu modeli: {e}")

    return ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-flash-latest", "gemini-3.5-flash"]


def parse_json_response(raw_text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned)


def ask_holistic_ai_coach(context_payload, target_date, day_name):
    if not GEMINI_API_KEY:
        raise ValueError("Brak klucza GEMINI_LLM_API_KEY!")

    compact_context = clean_empty_values(context_payload)

    prompt = f"""Jesteś elitarnym, holistycznym trenerem personalnym AI (bieganie długodystansowe, przygotowanie siłowe Gym A/B, kolarstwo gravelowe, basen) prowadzącym zawodnika długofalowo przez kolejne sezony.

ZADANIE:
Przeanalizuj pełny kontekst fizjologiczny, zasady z zakładki Cele_i_Strategia (w tym urlopy, wytyczne i rozważane starty), kalendarz prywatny oraz obciążenie i zaplanuj optymalną decyzję treningową na jutro: {target_date} ({day_name}).

PEŁNY KONTEKST ZAWODNIKA (JSON):
{json.dumps(compact_context, ensure_ascii=False)}

BEZWZGLĘDNE WYTYCZNE TRENERSKIE:
1. BIEGI SPOKOJNE NA TĘTNO (BPM), AKCENTY NA TEMPO (MIN/KM):
   - Dla WSZYSTKICH biegów spokojnych (Easy Run, Bieg Tlenowy, Recovery Run, spokojny Long Run) oraz dla rozgrzewek (warmup) i schłodzeń (cooldown) ZAWSZE podawaj cel jako ZAKRES TĘTNA w formacie `XXX-YYYbpm` (np. `warmup, 1km, 115-132bpm`, `interval, 5km, 125-145bpm`, `cooldown, 1km, 115-132bpm`). NIGDY nie podawaj tempa min/km dla biegów spokojnych!
   - Wyłącznie dla biegów jakościowych (Tempo Półmaratońskie, Bieg Progowy, Interwały VO2max, Rytmy) podawaj w odcinkach głównych (`interval`) widełki tempa `M:SS-M:SS` (np. `interval, 2km, 4:10-4:20`).
2. URLOPY, WYJAZDY I KALENDARZ:
   - Sprawdź sekcję `urlopy_i_niedostepnosci` oraz `wydarzenia_google_calendar`. Dostosuj mikrocykl do wyjazdów (np. przed urlopem możesz zaplanować nieco mocniejszy bodziec, a w trakcie urlopu regenerację).
3. TRENING HYBRYDOWY I PRZEPLATANIE DYSCYPLIN:
   - Zawodnik trenuje 2-3x w tygodniu siłowo (Gym A / Gym B), biega 3x w tygodniu oraz przeplata to rowerem lub basenem. Jeśli na jutro przypada Siłownia, Rower, Basen lub pełny Odpoczynek (dzień bez biegania), wpisz odpowiednią nazwę w `workout_name` (np. `Siłownia - Sesja B` lub `Basen Regeneracyjny`), a w polu `steps` wpisz dokładnie słowo: REST
4. SKŁADNIA PARSERA GARMINA (DLA DNI BIEGOWYCH):
   Każdy krok w osobnej linii zaczynający się od: `warmup`, `interval`, `recovery`, `cooldown`.
   Po przecinku dystans (`2km`, `400m`) lub czas (`15min`, `90s`), a po kolejnym przecinku cel (`125-145bpm` dla tlenu lub `4:10-4:20` dla akcentu). Bez zapisu pętli typu "3x".

Zwróć odpowiedź WYŁĄCZNIE jako czysty obiekt JSON w formacie:
{{
  "workout_name": "Krótka nazwa treningu (np. Spokojny Bieg Tlenowy Z2 (6 km) lub Siłownia - Sesja B)",
  "steps": "wieloliniowy kod kroków dla Garmina LUB słowo REST jeśli jutro dzień bez biegania",
  "coach_memory_note": "Zwięzła notatka analityczna (2-3 zdania): uzasadnienie decyzji i plan na kolejne 3-4 dni mikrocyklu."
}}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.25
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

        print(f"\n--- RUNDA {round_num} POSZUKIWANIA DOSTĘPNEGO MODELU ---")

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            print(f"[Runda {round_num}] Konsultacja z modelem: {model_name} (timeout=120s)...")

            try:
                response = requests.post(url, json=payload, timeout=120)

                if response.status_code == 200:
                    data = response.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = parse_json_response(raw_text)
                    print(f"SUKCES! Plan wygenerowany przez model: {model_name} w rundzie {round_num}.")
                    return parsed

                elif response.status_code == 429:
                    err_text = response.text
                    if "limit: 0" in err_text or "limit:0" in err_text:
                        permanently_blocked.add(model_name)
                    else:
                        print(f"Model {model_name} chwilowo limitowany (429).")

                elif response.status_code in [400, 404]:
                    permanently_blocked.add(model_name)

                elif response.status_code in [500, 502, 503, 504]:
                    print(f"Serwer modelu {model_name} przeciążony ({response.status_code}). Czekam 6s...")
                    time.sleep(6)

            except requests.exceptions.Timeout:
                print(f"Model {model_name} przekroczył 120s (Timeout).")
            except Exception as e:
                print(f"Błąd przy modelu {model_name}: {e}")

        wait_between_rounds = min(15 * round_num, 45)
        time.sleep(wait_between_rounds)
        round_num += 1

    raise RuntimeError("Przekroczono 15-minutowy limit oczekiwania na odpowiedź modeli Gemini.")


def main():
    print("Łączenie z ekosystemem Google Sheets...")
    sh = get_spreadsheet()

    wellness_sheet = sh.worksheet("Wellness")
    activities_sheet = sh.worksheet("Aktywnosci")
    treningi_sheet = sh.worksheet("Treningi")

    athlete_config, races_schedule, vacations_and_blocks, training_rules = ensure_goals_sheet(sh)
    cal_email = athlete_config.get("Kalendarz_Email", {}).get("wartosc", DEFAULT_CALENDAR_ID)

    print("Porządkowanie kolorów i pobieranie grafiku z Google Calendar...")
    calendar_events = auto_color_and_fetch_calendar(cal_email, days_ahead=10)

    print("Wyliczanie wskaźników CTL/ATL/ACWR i trendów wieloletnich...")
    wellness_summary, recent_wellness, load_metrics, recent_activities = analyze_full_history(
        wellness_sheet, activities_sheet
    )

    existing_rows = ensure_treningi_headers(treningi_sheet)
    recent_planned = []
    for r in existing_rows[-7:]:
        recent_planned.append({
            "Data": r[0] if len(r) > 0 else "",
            "Nazwa": r[1] if len(r) > 1 else "",
            "Status": r[3] if len(r) > 3 else "",
            "Notatka_Trenera": r[4] if len(r) > 4 else ""
        })

    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    target_date = tomorrow.isoformat()
    days_pl = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
    day_name = days_pl[tomorrow.weekday()]

    existing_row_idx = None
    existing_name = ""
    existing_code = ""
    for idx, row in enumerate(existing_rows):
        if row and str(row[0]).strip() == target_date:
            existing_row_idx = idx + 2
            existing_name = str(row[1]).strip() if len(row) > 1 else ""
            existing_code = str(row[2]).strip() if len(row) > 2 else ""
            break

    # Wymuszamy aktualizację, jeśli jutrzejszy bieg spokojny ma wpisane tempo zamiast tętna (bpm)
    needs_hr_conversion = (
        existing_row_idx is not None
        and any(w in existing_name.lower() for w in ["spokojny", "easy", "tlenowy", "recovery"])
        and "bpm" not in existing_code.lower()
    )

    default_note = "Samopoczucie w normie, brak dolegliwości."
    if existing_row_idx and not needs_hr_conversion and USER_NOTES.strip() in ["", default_note, "Brak dodatkowych uwag, samopoczucie w normie."]:
        print(f"Trening na jutro ({target_date}) jest już w arkuszu. Synchronizuję z Google Calendar...")
        existing_steps = "\n".join(existing_code.splitlines()[1:]) if "\n" in existing_code else existing_code
        existing_note = str(existing_rows[existing_row_idx - 2][4]).strip() if len(existing_rows[existing_row_idx - 2]) > 4 else ""
        sync_workout_to_google_calendar(cal_email, target_date, existing_name, existing_steps, existing_note)
        return

    context_payload = {
        "dzisiejsza_data": datetime.date.today().isoformat(),
        "uwagi_zawodnika_dzis": USER_NOTES,
        "konfiguracja_zawodnika": athlete_config,
        "reguly_i_preferencje_treningowe": training_rules,
        "urlopy_i_niedostepnosci": vacations_and_blocks,
        "kalendarz_startow_wieloletni": races_schedule,
        "wydarzenia_google_calendar_10_dni": calendar_events,
        "wskazniki_obciazenia_CTL_ATL_ACWR": load_metrics,
        "trendy_wellness_7d_vs_60d": wellness_summary,
        "ostatnie_7_dni_wellness": recent_wellness,
        "ostatnie_12_aktywnosci": recent_activities,
        "ostatnie_zaplanowane_treningi_i_notatki_AI": recent_planned
    }

    ai_plan = ask_holistic_ai_coach(context_payload, target_date, day_name)

    workout_name = ai_plan.get("workout_name", "Trening AI").strip()
    steps_code = ai_plan.get("steps", "interval, 6km, 125-145bpm").strip()
    coach_note = ai_plan.get("coach_memory_note", "").strip()

    if steps_code.upper() == "REST" or "REST" in steps_code.upper().splitlines()[0]:
        full_workout_code = "REST"
        status_flag = "Do aktualizacji" if existing_row_idx else "Zaplanowane (Bez biegu)"
    else:
        full_workout_code = f"{target_date} {workout_name}\n{steps_code}"
        status_flag = "Do aktualizacji" if existing_row_idx else "Do wgrania"

    new_row = [target_date, workout_name, full_workout_code, status_flag, coach_note]

    if existing_row_idx:
        treningi_sheet.update(values=[new_row], range_name=f"A{existing_row_idx}:E{existing_row_idx}")
        print(f"ZAKTUALIZOWANO trening w Google Sheets na {target_date} -> {workout_name}")
    else:
        treningi_sheet.append_row(new_row)
        print(f"DODANO nowy trening w Google Sheets na {target_date} -> {workout_name}")

    sync_workout_to_google_calendar(cal_email, target_date, workout_name, steps_code, coach_note)


if __name__ == "__main__":
    main()
