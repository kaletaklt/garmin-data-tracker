import os
import re
import json
import math
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


def ensure_goals_sheet(sh):
    """Tworzy lub odczytuje zakładkę 'Cele_i_Strategia' do wieloletniego zarządzania planem."""
    try:
        ws = sh.worksheet("Cele_i_Strategia")
        rows = ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        print("Tworzenie nowej zakładki 'Cele_i_Strategia'...")
        ws = sh.add_worksheet(title="Cele_i_Strategia", rows=40, cols=6)
        default_rows = [
            ["Typ_Wpisu", "Nazwa / Klucz", "Data_lub_Wartosc", "Dystans / Dyscyplina", "Cel_Wynikowy", "Priorytet / Uwagi"],
            ["KONFIGURACJA", "Kalendarz_Email", DEFAULT_CALENDAR_ID, "Google Calendar", "Odczyt 7 dni", "Wpisz swój email Gmail w kolumnie C"],
            ["KONFIGURACJA", "Profil_Atlety", "Hybrydowy (Bieganie + Siłownia + Gravel)", "2x Siłownia (Gym A/B), 3x Bieg", "Utrzymanie siły i masy mięśniowej", "Zasada: unikaj ciężkich interwałów dzień po ciężkich przysiadach/RDL"],
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
                weeks_left = None

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
    """Pobiera wydarzenia z Google Calendar na najbliższe dni przy użyciu tego samego konta usługi."""
    if not calendar_id or "@" not in calendar_id:
        return ["Brak skonfigurowanego adresu Kalendarza Google w zakładce Cele_i_Strategia."]

    try:
        creds = get_credentials(["https://www.googleapis.com/auth/calendar.readonly"])
        creds.refresh(Request())
        token = creds.token

        now = datetime.datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + datetime.timedelta(days=days_ahead)).isoformat() + "Z"

        url = f"https://www.googleapis.com/calendar/v3/calendars/{ requests.utils.quote(calendar_id) }/events"
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
            return [f"Kalendarz niedostępny (kod {r.status_code}) - upewnij się, że udostępniłeś kalendarz kontu usługi."]

        items = r.json().get("items", [])
        events_summary = []
        for ev in items:
            summary = ev.get("summary", "Zajęty termin")
            start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            end = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))
            events_summary.append(f"{start[:16]} -> {end[:16]}: {summary}")

        return events_summary if events_summary else ["Brak zaplanowanych wydarzeń w kalendarzu na najbliższe 7 dni."]
    except Exception as e:
        return [f"Nie udało się pobrać kalendarza: {e}"]


def analyze_full_history(wellness_sheet, activities_sheet):
    """Przetwarza pełną wieloletnią historię Wellness i Aktywności w zwięzłe wskaźniki fizjologiczne."""
    w_all = wellness_sheet.get_all_values()
    a_all = activities_sheet.get_all_values()

    today = datetime.date.today()

    # --- 1. Analiza Wellness (Trendy 7d vs 60d + ostatnie 7 dni szczegółowo) ---
    w_headers = w_all[0][:24] if w_all else []
    w_rows = w_all[1:] if len(w_all) > 1 else []

    rhr_60, rhr_7 = [], []
    hrv_60, hrv_7 = [], []
    sleep_60, sleep_7 = [], []
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

    # --- 2. Analiza Aktywności (CTL, ATL, TSB, ACWR + 12 tygodni objętości) ---
    a_headers = a_all[0][:25] if a_all else []
    a_rows = a_all[1:] if len(a_all) > 1 else []

    daily_load = {}
    weekly_stats = {}
    recent_activities = []

    for row in a_rows:
        padded = row[:25] + [""] * max(0, 25 - len(row))
        act = dict(zip(a_headers, padded))
        d_str = act.get("Data", "")
        try:
            a_date = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
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

    # Obliczanie CTL (42d EWMA) i ATL (7d EWMA) po ostatnich 180 dniach
    ctl = 0.0
    atl = 0.0
    for i in range(180, -1, -1):
        d = today - datetime.timedelta(days=i)
        ld = daily_load.get(d, 0.0)
        ctl = ctl + (ld - ctl) * (1.0 / 42.0)
        atl = atl + (ld - atl) * (1.0 / 7.0)

    tsb = ctl - atl
    acwr = round(atl / ctl, 2) if ctl > 5 else 1.0

    for row in a_rows[-14:]:
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
        "Interpretacja_ACWR": "Optymalny (0.8-1.3)" if 0.8 <= acwr <= 1.3 else ("Wysokie ryzyko przeciążenia (>1.3)" if acwr > 1.3 else "Niskie obciążenie (<0.8)"),
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
        print("Aktualizacja nagłówków w zakładce 'Treningi'...")
        treningi_sheet.clear()
        treningi_sheet.append_row(expected)
        return []
    if len(all_values[0]) < 5:
        treningi_sheet.update_cell(1, 5, "Notatka_Trenera")
    return all_values[1:]


def get_candidate_models():
    preferred_order = [
        "gemini-4-argon",
        "antigravity-preview-latest",
        "gemini-3.8-flash",
        "gemini-flash-latest",
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-pro-latest"
    ]
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        models_data = r.json().get("models", [])
        available = [
            m["name"].replace("models/", "")
            for m in models_data
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        candidates = [m for m in preferred_order if m in available]
        for m in available:
            if m not in candidates and not any(x in m for x in ["tts", "image", "lyria", "robotics", "transcribe"]):
                candidates.append(m)
        return candidates if candidates else preferred_order
    except Exception:
        return preferred_order


def parse_json_response(raw_text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned)


def ask_holistic_ai_coach(context_payload, target_date, day_name):
    if not GEMINI_API_KEY:
        raise ValueError("Brak klucza GEMINI_LLM_API_KEY!")

    prompt = f"""Jesteś elitarnym, holistycznym trenerem personalnym AI (bieganie długodystansowe, przygotowanie siłowe, kolarstwo gravelowe) prowadzącym zawodnika długofalowo przez kolejne sezony.

ZADANIE:
Przeanalizuj pełny kontekst fizjologiczny, realizację dotychczasowego planu, kalendarz prywatny oraz cele wieloletnie i zaplanuj optymalną decyzję treningową na jutro: {target_date} ({day_name}).

PEŁNY KONTEKST ZAWODNIKA (JSON):
{json.dumps(context_payload, ensure_ascii=False, indent=2)}

WYTYCZNE TRENERSKIE:
1. PERIODYZACJA I CELE: Dostosuj bodziec do aktualnej fazy makrocyklu względem głównego startu A oraz startów kontrolnych B.
2. FIZJOLOGIA I REGENERACJA: Zwróć uwagę na odchylenie 7-dniowego HRV i RHR od bazy 60-dniowej, wynik snu, Body Battery oraz wskaźnik ACWR i TSB.
3. GRAFIK I KALENDARZ GOOGLE: Jeśli jutro w kalendarzu Google są całodniowe wyjazdy lub bardzo napięty grafik, dostosuj czas trwania jednostki lub zaplanuj dzień wolny/regenerację.
4. TRENING HYBRYDOWY: Zawodnik trenuje siłowo (Gym A / Gym B) i biega. Jeśli z historii aktywności lub uwag wynika, że na jutro przypada dzień wolny od biegania (np. sama siłownia lub pełny odpoczynek), ustaw w polu "steps" dokładnie słowo: REST
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
  "coach_memory_note": "Zwięzła notatka analityczna (2-3 zdania): dlaczego podjąłeś taką decyzję (odnieś się do HRV/CTL/Kalendarza) i co planujesz na kolejne 3-4 dni mikrocyklu."
}}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.25
        }
    }

    for model_name in get_candidate_models():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        print(f"Konsultacja z modelem: {model_name}...")
        try:
            response = requests.post(url, json=payload, timeout=45)
            if response.status_code == 200:
                data = response.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"Plan wygenerowany przez model: {model_name}")
                return parse_json_response(raw_text)
            else:
                print(f"Model {model_name} zwrócił status {response.status_code}")
        except Exception as e:
            print(f"Błąd modelu {model_name}: {e}")

    raise RuntimeError("Wszystkie modele AI zwróciły błąd.")


def main():
    print("Łączenie z ekosystemem Google Sheets...")
    sh = get_spreadsheet()

    wellness_sheet = sh.worksheet("Wellness")
    activities_sheet = sh.worksheet("Aktywnosci")
    treningi_sheet = sh.worksheet("Treningi")

    # 1. Cele długoterminowe i konfiguracja
    athlete_config, races_schedule = ensure_goals_sheet(sh)
    cal_email = athlete_config.get("Kalendarz_Email", {}).get("wartosc", DEFAULT_CALENDAR_ID)

    # 2. Pobranie wydarzeń z Google Calendar na 7 dni wprzód
    print(f"Pobieranie grafiku z Google Calendar ({cal_email})...")
    calendar_events = fetch_google_calendar_events(cal_email, days_ahead=7)

    # 3. Analiza pełnej historii fizjologicznej
    print("Wyliczanie wskaźników CTL/ATL/ACWR i trendów wieloletnich...")
    wellness_summary, recent_wellness, load_metrics, recent_activities = analyze_full_history(
        wellness_sheet, activities_sheet
    )

    # 4. Odczyt historii zaplanowanych treningów i pamięci trenera
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

    # Sprawdzenie, czy jutrzejszy trening już istnieje w arkuszu
    existing_row_idx = None
    for idx, row in enumerate(existing_rows):
        if row and str(row[0]).strip() == target_date:
            existing_row_idx = idx + 2  # +2 bo wiersz 1 to nagłówek, a indeksowanie od 1
            break

    default_note = "Samopoczucie w normie, brak dolegliwości."
    if existing_row_idx and USER_NOTES.strip() in ["", default_note, "Brak dodatkowych uwag, samopoczucie w normie."]:
        print(f"Trening na jutro ({target_date}) jest już zaplanowany, a użytkownik nie zgłosił nowych uwag. Pomijam.")
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
        "ostatnie_14_aktywnosci": recent_activities,
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
        print(f"ZAKTUALIZOWANO trening na {target_date} -> {workout_name}")
    else:
        treningi_sheet.append_row(new_row)
        print(f"DODANO nowy trening na {target_date} -> {workout_name}")


if __name__ == "__main__":
    main()
