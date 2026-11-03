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
    """Usuwa puste klucze ze słowników, aby zmniejszyć rozmiar promptu i przyspieszyć odpowiedź AI."""
    if isinstance(data, list):
        return [clean_empty_values(v) for v in data]
    if isinstance(data, dict):
        return {k: clean_empty_values(v) for k, v in data.items() if v not in ["", None]}
    return data


def ensure_goals_sheet(sh):
    """Tworzy lub odczytuje zakładkę 'Cele_i_Strategia'."""
    try:
        ws = sh.worksheet("Cele_i_Strategia")
        rows = ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        print("Tworzenie nowej zakładki 'Cele_i_Strategia'...")
        ws = sh.add_worksheet(title="Cele_i_Strategia", rows=40, cols=6)
        default_rows = [
            ["Typ_Wpisu", "Nazwa / Klucz", "Data_lub_Wartosc", "Dystans / Dyscyplina", "Cel_Wynikowy", "Priorytet / Uwagi"],
            ["KONFIGURACJA", "Kalendarz_Email", DEFAULT_CALENDAR_ID, "Google Calendar", "Odczyt i zapis", "Wpisz swój email Gmail w kolumnie C"],
            ["KONFIGURACJA", "Profil_Atlety", "Hybrydowy (Bieganie + Siłownia + Gravel)", "2x Siłownia (Gym A/B), 3x Bieg", "Utrzymanie siły i masy mięśniowej", "Unikaj ciężkich interwałów dzień po przysiadach/RDL"],
            ["KONFIGURACJA", "Rekord_Zyciowy_HM", "1:36:00", "Półmaraton (21.1 km)", "Marzec 2024", "Historyczny punkt odniesienia"],
            ["START_GLOWNY", "Półmaraton Warszawski 2027", "2027-03-28", "Bieg 21.1 km", "Sub 1:30:00 (tempo 4:15/km)", "Priorytet A - cel główny makrocyklu"],
            ["START_KONTROLNY", "Bieg Niepodległości / Test 10km", "2026-11-11", "Bieg 10 km", "Sprawdzenie tętna progowego", "Priorytet B - bieg kontrolny"]
        ]
        ws.update(values=default_rows, range_name="A1")
        rows = default_rows

    config = {}
    races = []
    today = datetime.date.today()

    for r in rows[1:]:
        if len(r) < 3 or not r[0].strip():
            continue
        entry_type = r[0].strip().upper()
        name = r[1].strip()
        val_or_date = r[2].strip()
        dist = r[3].strip() if len(r) > 3 else ""
        goal = r[4].strip() if len(r) > 4 else ""
        notes = r[5].strip() if len(r) > 5 else ""

        if entry_type == "KONFIGURACJA":
            config[name] = {
                "wartosc": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |")
            }
        elif "START" in entry_type:
            days_left = None
            phase = "Planowanie długoterminowe"
            try:
                race_date = datetime.datetime.strptime(val_or_date, "%Y-%m-%d").date()
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

    return config, races


def fetch_google_calendar_events(calendar_id, days_ahead=7):
    if not calendar_id or "@" not in calendar_id:
        return ["Brak skonfigurowanego adresu Kalendarza Google."]

    try:
        creds = get_credentials(["https://www.googleapis.com/auth/calendar"])
        creds.refresh(Request())
        token = creds.token

        now = datetime.datetime.now(datetime.timezone.utc)
        time_min = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (now + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

        url = f"https://www.googleapis.com/calendar/v3/calendars/{requests.utils.quote(calendar_id)}/events"
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 50
        }
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            return [f"Kalendarz niedostępny (kod {r.status_code})."]

        items = r.json().get("items", [])
        events_summary = []
        for ev in items:
            summary = ev.get("summary", "Zajęty termin")
            if summary.startswith("[AI Coach]"):
                continue
            start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            end = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))
            events_summary.append(f"{start[:16]} -> {end[:16]}: {summary}")

        return events_summary if events_summary else ["Brak zaplanowanych wydarzeń na najbliższe 7 dni."]
    except Exception as e:
        return [f"Nie udało się pobrać kalendarza: {e}"]


def sync_workout_to_google_calendar(calendar_id, target_date, workout_name, steps_code, coach_note):
    """Zapisuje lub aktualizuje zaplanowany trening bezpośrednio w Kalendarzu Google."""
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
                if str(item.get("summary", "")).startswith("[AI Coach]"):
                    ev_id = item.get("id")
                    requests.delete(f"{base_url}/{ev_id}", headers=headers, timeout=10)

        event_body = {
            "summary": f"[AI Coach] {workout_name}",
            "description": f"Kroki treningu:\n{steps_code}\n\nAnaliza trenera AI:\n{coach_note}",
            "start": {"date": target_date},
            "end": {"date": next_day}
        }
        r_ins = requests.post(base_url, headers=headers, json=event_body, timeout=15)
        if r_ins.status_code in [200, 201]:
            print(f"Dodano wpis do Kalendarza Google na dzień {target_date}: [AI Coach] {workout_name}")
        else:
            print(f"Uwaga: Google Calendar zwrócił kod {r_ins.status_code} przy próbie zapisu.")
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
    """
    Dynamicznie pobiera listę modeli z API Google, odrzuca modele lite/gemma/specjalistyczne
    i sortuje je od najwyższej klasy oraz najnowszej generacji.
    """
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
        print(f"Dynamiczny ranking najlepszych modeli (bez Lite/Gemma): {ranked}")
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

    prompt = f"""Jesteś elitarnym, holistycznym trenerem personalnym AI (bieganie długodystansowe, przygotowanie siłowe, kolarstwo gravelowe) prowadzącym zawodnika długofalowo przez kolejne sezony.

ZADANIE:
Przeanalizuj pełny kontekst fizjologiczny, realizację dotychczasowego planu, kalendarz prywatny oraz cele wieloletnie i zaplanuj optymalną decyzję treningową na jutro: {target_date} ({day_name}).

PEŁNY KONTEKST ZAWODNIKA (JSON):
{json.dumps(compact_context, ensure_ascii=False)}

WYTYCZNE TRENERSKIE:
1. PERIODYZACJA I CELE: Dostosuj bodziec do aktualnej fazy makrocyklu względem głównego startu A oraz startów kontrolnych B.
2. FIZJOLOGIA I REGENERACJA: Zwróć uwagę na odchylenie 7-dniowego HRV i RHR od bazy 60-dniowej, wynik snu, Body Battery oraz wskaźnik ACWR i TSB.
3. GRAFIK I KALENDARZ GOOGLE: Jeśli jutro w kalendarzu Google są całodniowe wyjazdy lub bardzo napięty grafik, dostosuj czas trwania jednostki lub zaplanuj dzień wolny/regenerację.
4. TRENING HYBRYDOWY: Jeśli na jutro przypada dzień wolny od biegania (np. sama siłownia lub pełny odpoczynek), ustaw w polu "steps" dokładnie słowo: REST
5. ZASADY KODU TRENINGU BIEGOWEGO (KRYTYCZNE DLA PARSERA GARMINA):
   Jeśli jutro jest bieg, każdy krok musi być w osobnej linii i zaczynać się od:
   warmup, interval, recovery, cooldown
   Po przecinku podaj dystans (np. 2km lub 400m) LUB czas (np. 15min lub 90s).
   Po kolejnym przecinku podaj widełki tempa (np. 4:10-4:20) LUB tętna (np. 135-148bpm).
   Nie używaj zapisu pętli typu "4x" - rozpisz każde powtórzenie w osobnej linii.

Zwróć odpowiedź WYŁĄCZNIE jako czysty obiekt JSON w formacie:
{{
  "workout_name": "Krótka nazwa treningu (np. Progowe 3x2km lub Regeneracja / Siłownia)",
  "steps": "wieloliniowy kod kroków dla Garmina LUB słowo REST jeśli jutro dzień bez biegania",
  "coach_memory_note": "Zwięzła notatka analityczna (2-3 zdania): dlaczego podjąłeś taką decyzję i co planujesz na kolejne 3-4 dni mikrocyklu."
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

    max_wait_seconds = 900  # Pętla próbuje do skutku przez maksymalnie 15 minut
    start_time = time.time()
    round_num = 1

    while (time.time() - start_time) < max_wait_seconds:
        models_to_try = [m for m in active_models if m not in permanently_blocked]
        if not models_to_try:
            # Jeśli wszystkie zostały oznaczone jako zablokowane, resetujemy listę po odczekaniu
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
                        print(f"Model {model_name} ma limit=0 na obecnym planie klucza API - pomijam w kolejnych rundach.")
                        permanently_blocked.add(model_name)
                    else:
                        print(f"Model {model_name} przekroczył chwilowy limit zapytań (429). Spróbuję ponownie w kolejnej rundzie.")

                elif response.status_code in [400, 404]:
                    print(f"Model {model_name} niedostępny (kod {response.status_code}) - pomijam w kolejnych rundach.")
                    permanently_blocked.add(model_name)

                elif response.status_code in [500, 502, 503, 504]:
                    print(f"Serwer modelu {model_name} przeciążony (kod {response.status_code}). Czekam 6s przed kolejnym modelem...")
                    time.sleep(6)

                else:
                    print(f"Model {model_name} zwrócił nieoczekiwany kod {response.status_code}.")

            except requests.exceptions.Timeout:
                print(f"Model {model_name} przekroczył 120s czasu odpowiedzi (Timeout). Przechodzę dalej...")
            except Exception as e:
                print(f"Błąd przy modelu {model_name}: {e}")

        wait_between_rounds = min(15 * round_num, 45)
        print(f"Żaden model nie odpowiedział w rundzie {round_num}. Odczekuję {wait_between_rounds}s przed kolejną pętlą...")
        time.sleep(wait_between_rounds)
        round_num += 1

    raise RuntimeError("Przekroczono 15-minutowy limit oczekiwania na odpowiedź modeli Gemini.")


def main():
    print("Łączenie z ekosystemem Google Sheets...")
    sh = get_spreadsheet()

    wellness_sheet = sh.worksheet("Wellness")
    activities_sheet = sh.worksheet("Aktywnosci")
    treningi_sheet = sh.worksheet("Treningi")

    athlete_config, races_schedule = ensure_goals_sheet(sh)
    cal_email = athlete_config.get("Kalendarz_Email", {}).get("wartosc", DEFAULT_CALENDAR_ID)

    print("Pobieranie grafiku z Google Calendar...")
    calendar_events = fetch_google_calendar_events(cal_email, days_ahead=7)

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
    for idx, row in enumerate(existing_rows):
        if row and str(row[0]).strip() == target_date:
            existing_row_idx = idx + 2
            break

    default_note = "Samopoczucie w normie, brak dolegliwości."
    if existing_row_idx and USER_NOTES.strip() in ["", default_note, "Brak dodatkowych uwag, samopoczucie w normie."]:
        print(f"Trening na jutro ({target_date}) jest już zaplanowany, brak nowych uwag. Pomijam.")
        return

    context_payload = {
        "dzisiejsza_data": datetime.date.today().isoformat(),
        "uwagi_zawodnika_dzis": USER_NOTES,
        "konfiguracja_zawodnika": athlete_config,
        "kalendarz_startow_wieloletni": races_schedule,
        "wydarzenia_google_calendar_7_dni": calendar_events,
        "wskazniki_obciazenia_CTL_ATL_ACWR": load_metrics,
        "trendy_wellness_7d_vs_60d": wellness_summary,
        "ostatnie_7_dni_wellness": recent_wellness,
        "ostatnie_12_aktywnosci": recent_activities,
        "ostatnie_zaplanowane_treningi_i_notatki_AI": recent_planned
    }

    ai_plan = ask_holistic_ai_coach(context_payload, target_date, day_name)

    workout_name = ai_plan.get("workout_name", "Trening AI").strip()
    steps_code = ai_plan.get("steps", "interval, 8km, 5:10-5:30").strip()
    coach_note = ai_plan.get("coach_memory_note", "").strip()

    if steps_code.upper() == "REST" or "REST" in steps_code.upper().splitlines()[0]:
        full_workout_code = "REST"
        status_flag = "Zaplanowane (Bez biegu)"
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
