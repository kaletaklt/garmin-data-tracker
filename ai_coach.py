import os
import re
import json
import datetime
import gspread
from google.oauth2 import service_account

from coach_analytics import (
    analyze_full_history,
    read_goals_and_strategy,
    safe_float,
)
from coach_auditor import (
    audit_past_workouts,
    parse_planned_steps_summary,
    format_pace_min_km,
    enforce_fixed_gym_and_max_streak,
    is_rest_day_entry,
)
from gcal_bridge import (
    fetch_calendar_context,
    extract_fixed_gym_days,
    estimate_workout_duration_minutes,
    find_optimal_workout_slot,
    sync_workout_to_google_calendar,
)
from gemini_client import (
    get_dynamic_high_end_models,
    ask_holistic_7day_coach,
    parse_json_response,
    clean_empty_values,
)

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
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

    print("Pobieranie grafiku i sztywnych dni siłowni z Google Calendar na 10 dni...")
    calendar_events, raw_calendar_items = fetch_calendar_context(cal_email, days_ahead=10)
    fixed_gym_days = extract_fixed_gym_days(raw_calendar_items)
    print(f"Wykryte sztywne sesje siłowe w kalendarzu: {fixed_gym_days}")

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
        "sztywne_dni_silowni_z_kalendarza": fixed_gym_days,
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

    # 2b. Twardy strażnik sztywnej siłowni z kalendarza i zasady max 3 dni treningowych z rzędu
    seven_day_plan = enforce_fixed_gym_and_max_streak(
        seven_day_plan, fixed_gym_days, activities_by_date, today
    )

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
