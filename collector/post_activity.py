"""
Collector po zakończonej aktywności (wyzwalany np. powiadomieniem Garmin -> Tasker):
1. Pobiera najnowsze aktywności z zegarka Garmin do zakładki Aktywnosci.
2. Zapisuje ankietę potreningową (RPE, DOMS, dyskomfort, notatka) do Dziennik_Subiektywny.
3. Rozlicza dzisiejsze wykonanie w zakładce Treningi (audyt TODO-06).
4. Jeśli wykryto nieprawidłowość (np. bardzo wysokie RPE >= 9, ból/kontuzję, odchylenie od planu) -> uruchamia replan w ai_coach.
"""
import os

from collector.activities import collect_recent_activities
from collector.anomaly_detector import evaluate_replan_need
from collector.subjective import has_subjective_payload, log_subjective_entry, read_subjective_env
from common.garmin_auth import GarminAuthenticator
from common.google_auth import get_spreadsheet


def main():
    sh = get_spreadsheet()
    garmin_client = GarminAuthenticator().login()

    # 1. Pobranie najnowszych aktywności z zegarka
    collect_recent_activities(garmin_client=garmin_client, spreadsheet=sh)

    # 2. Sprawdzenie anomalii potreningowych (RPE, ból, odchylenie wykonania od planu)
    sub = read_subjective_env(default_report_type="Po_Treningu")
    should_replan, reasons = evaluate_replan_need(sh, sub)

    if should_replan:
        ai_reaction = f"Wyzwolono adaptację planu AI Coach ({'; '.join(reasons)})"
    else:
        ai_reaction = "Zapisano raport potreningowy – plan bez zmian"

    combined_note = ""
    if has_subjective_payload(sub):
        combined_note = log_subjective_entry(sh, sub, ai_reaction)

    # 3. Jeśli wykryto nieprawidłowość -> pełny replan; w przeciwnym razie tylko audyt dzisiejszego wykonania
    if should_replan:
        print(f"Wykryto nieprawidłowość po aktywności ({reasons}) – uruchamiam AI Coach...")
        if combined_note:
            os.environ["USER_NOTES"] = combined_note
        from calendars_sync.google_to_garmin import sync_gym_events_to_garmin
        from ai_coach.main import main as run_ai_coach
        from calendars_sync.garmin_to_google import mirror_garmin_workouts_to_google

        sync_gym_events_to_garmin(garmin_client=garmin_client, spreadsheet=sh)
        run_ai_coach()
        mirror_garmin_workouts_to_google(garmin_client=garmin_client, spreadsheet=sh)
    else:
        print("Brak nieprawidłowości wymagających zmiany planu – aktualizuję wyłącznie audyt wykonania (TODO-06)...")
        from ai_coach.analytics import analyze_full_history
        from ai_coach.auditor import audit_past_workouts
        from ai_coach.main import ensure_treningi_headers
        from common.config import SHEET_ACTIVITIES, SHEET_TRAININGS, SHEET_WELLNESS

        treningi_sheet = sh.worksheet(SHEET_TRAININGS)
        existing_rows = ensure_treningi_headers(treningi_sheet)
        _, _, _, _, activities_by_date = analyze_full_history(
            sh.worksheet(SHEET_WELLNESS), sh.worksheet(SHEET_ACTIVITIES)
        )
        audit_past_workouts(treningi_sheet, existing_rows, activities_by_date)


if __name__ == "__main__":
    main()
