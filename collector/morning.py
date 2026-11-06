"""
Poranny collector:
1. Pobiera dane Wellness z zegarka Garmin (ostatnie 7 dni + dzisiaj).
2. Zapisuje poranną ankietę subiektywną (energia, DOMS, dyskomfort, notatka) do Dziennik_Subiektywny.
3. Sprawdza detektorem anomalii, czy wystąpiła nieprawidłowość w ankiecie lub statystykach (spadek HRV, skok RHR, słaby sen, braki w planie 7-dniowym).
4. Jeśli wykryto nieprawidłowość -> uruchamia synchronizację siłowni z Google Calendar oraz replan w ai_coach.
"""
import os

from collector.anomaly_detector import evaluate_replan_need
from collector.subjective import has_subjective_payload, log_subjective_entry, read_subjective_env
from collector.wellness import collect_wellness_days
from common.garmin_auth import GarminAuthenticator
from common.google_auth import get_spreadsheet


def main():
    sh = get_spreadsheet()
    garmin_client = GarminAuthenticator().login()

    # 1. Statystyki Wellness z zegarka
    collect_wellness_days(garmin_client=garmin_client, spreadsheet=sh)

    # 2. Odczyt porannej ankiety i detekcja nieprawidłowości
    sub = read_subjective_env(default_report_type="Rano_CheckIn")
    should_replan, reasons = evaluate_replan_need(sh, sub)

    if should_replan:
        ai_reaction = f"Wyzwolono adaptację planu AI Coach ({'; '.join(reasons)})"
    else:
        ai_reaction = "Parametry w normie – plan bez zmian"

    combined_note = ""
    if has_subjective_payload(sub):
        combined_note = log_subjective_entry(sh, sub, ai_reaction)

    # 3. Warunkowe uruchomienie AI Coach przy wykrytej nieprawidłowości
    if should_replan:
        print(f"Wykryto podstawę do adaptacji planu: {reasons}")
        if combined_note:
            os.environ["USER_NOTES"] = combined_note
        from calendars_sync.google_to_garmin import sync_gym_events_to_garmin
        from ai_coach.main import main as run_ai_coach
        from calendars_sync.garmin_to_google import mirror_garmin_workouts_to_google

        sync_gym_events_to_garmin(garmin_client=garmin_client, spreadsheet=sh)
        run_ai_coach()
        mirror_garmin_workouts_to_google(garmin_client=garmin_client, spreadsheet=sh)
    else:
        print("Brak anomalii w ankietach i statystykach – pomijam replan AI Coach.")


if __name__ == "__main__":
    main()
