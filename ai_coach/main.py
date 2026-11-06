"""
Punkt wejścia `ai_coach`:
- Czyta arkusze Google Sheets (`Wellness`, `Aktywnosci`, `Cele_i_Strategia`, `Treningi`).
- Czyta kalendarze (Google Calendar + kalendarz Garmin Connect) wyłącznie w trybie odczytu.
- Przeprowadza audyt wykonania przeszłych treningów (TODO-06).
- Generuje i adaptuje 7-dniowy plan w Gemini (TODO-05) i przepuszcza go przez strażnika reguł (`rules.py`).
- Zapisuje plan wyłącznie w arkuszu `Treningi` oraz w kalendarzu Garmin Connect (`garmin_publisher.py`).
"""
import datetime
import os

from ai_coach.analytics import analyze_full_history, read_goals_and_strategy
from ai_coach.auditor import audit_past_workouts
from ai_coach.calendar_reader import extract_fixed_gym_days, fetch_calendar_context, read_garmin_calendar_window
from ai_coach.garmin_publisher import normalize_steps_only, publish_seven_day_plan_to_garmin
from ai_coach.gemini_client import ask_holistic_7day_coach
from ai_coach.rules import enforce_fixed_gym_and_max_streak
from common.config import GOOGLE_CALENDAR_ID, SHEET_ACTIVITIES, SHEET_TRAININGS, SHEET_WELLNESS
from common.garmin_auth import GarminAuthenticator
from common.google_auth import get_spreadsheet


def ensure_treningi_headers(treningi_sheet):
    expected = ["Data", "Nazwa", "Kod Treningu", "Status", "Notatka_Trenera", "Garmin_Workout_ID"]
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
    if len(all_values[0]) < 6:
        treningi_sheet.update_cell(1, 6, "Garmin_Workout_ID")
    return all_values[1:]


def main():
    user_notes = os.getenv("USER_NOTES", "Brak dodatkowych uwag, samopoczucie w normie.")

    print("Łączenie z ekosystemem Google Sheets oraz Garmin Connect...")
    sh = get_spreadsheet()
    garmin_client = GarminAuthenticator().login()

    wellness_sheet = sh.worksheet(SHEET_WELLNESS)
    activities_sheet = sh.worksheet(SHEET_ACTIVITIES)
    treningi_sheet = sh.worksheet(SHEET_TRAININGS)

    athlete_config, races_schedule, vacations_and_blocks, training_rules, mesocycles = read_goals_and_strategy(sh)
    cal_email = athlete_config.get("Kalendarz_Email", {}).get("wartosc") or GOOGLE_CALENDAR_ID

    print("Odczyt grafiku z Google Calendar oraz kalendarza Garmin Connect na 10 dni...")
    calendar_events, raw_calendar_items = fetch_calendar_context(cal_email, days_ahead=10)
    garmin_planned_by_date = read_garmin_calendar_window(garmin_client, days_ahead=10)
    fixed_gym_days = extract_fixed_gym_days(raw_calendar_items, garmin_planned_by_date)
    print(f"Wykryte sztywne sesje niebiegowe (Google + Garmin): {fixed_gym_days}")

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
                "note": r[4].strip() if len(r) > 4 else "",
                "garmin_workout_id": r[5].strip() if len(r) > 5 else "",
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
                "coach_memory_note": ex["note"],
            })

    context_payload = {
        "dzisiejsza_data": today.isoformat(),
        "uwagi_zawodnika_dzis": user_notes,
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
        "ostatnie_12_aktywnosci": recent_activities,
    }

    ai_response = ask_holistic_7day_coach(context_payload, horizon_days)
    seven_day_plan = ai_response.get("seven_day_plan", [])
    weekly_summary = ai_response.get("weekly_strategy_summary", "")
    if weekly_summary:
        print(f"Strategia tygodnia AI: {weekly_summary}")

    # 2b. Twardy strażnik sztywnej siłowni i zasady max 3 dni treningowych z rzędu
    seven_day_plan = enforce_fixed_gym_and_max_streak(
        seven_day_plan, fixed_gym_days, activities_by_date, today
    )

    # 3. Zapis wyłącznie do Arkusza Treningi oraz kalendarza Garmin Connect (z obsługą konfliktów)
    publish_seven_day_plan_to_garmin(
        garmin_client=garmin_client,
        treningi_sheet=treningi_sheet,
        seven_day_plan=seven_day_plan,
        existing_by_date=existing_by_date,
        garmin_planned_by_date=garmin_planned_by_date,
    )


if __name__ == "__main__":
    main()
