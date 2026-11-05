import os
import json
import datetime
import subprocess
import gspread
from google.oauth2 import service_account

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")


def get_spreadsheet():
    creds_dict = json.loads(os.getenv("GSPREAD_CREDENTIALS"))
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def main():
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet("Dziennik_Subiektywny")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Dziennik_Subiektywny", rows=500, cols=9)
        ws.append_row([
            "Data", "Godzina", "Typ_Raportu", "Energia_Rano_1_5",
            "RPE_Treningu_1_10", "DOMS_Bolesnosc", "Dyskomfort_Kontuzje",
            "Notatka_Glosowa_Tekstowa", "Reakcja_AI_Coach"
        ])

    now_pl = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1)))
    date_str = now_pl.strftime("%Y-%m-%d")
    time_str = now_pl.strftime("%H:%M:%S")

    report_type = os.getenv("REPORT_TYPE", "Rano_CheckIn").strip()
    energy = os.getenv("ENERGY_1_5", "").strip()
    rpe = os.getenv("RPE_1_10", "").strip()
    doms = os.getenv("DOMS_INFO", "Brak").strip()
    pain = os.getenv("PAIN_INFO", "Brak").strip()
    note = os.getenv("USER_NOTE", "").strip()
    trigger_replan = os.getenv("TRIGGER_REPLAN", "true").strip().lower() == "true"

    ai_reaction = "Zapisano w bazie kontekstowej"
    if trigger_replan:
        ai_reaction = "Wyzwolono natychmiastową adaptację planu AI Coach"

    new_row = [date_str, time_str, report_type, energy, rpe, doms, pain, note, ai_reaction]
    ws.append_row(new_row)
    print(f"Zapisano raport w Dziennik_Subiektywny: {new_row}")

    if trigger_replan:
        combined_note = (
            f"[{report_type} {date_str} {time_str}] "
            f"Energia: {energy or '-'}/5 | RPE: {rpe or '-'}/10 | "
            f"DOMS: {doms} | Dyskomfort: {pain} | Uwagi: {note}"
        )
        env = os.environ.copy()
        env["USER_NOTES"] = combined_note
        print("Uruchamianie ai_coach.py z nowym kontekstem subiektywnym...")
        subprocess.run(["python", "ai_coach.py"], env=env, check=True)
        print("Synchronizacja ewentualnych zmian z Garmin Connect...")
        subprocess.run(["python", "sync_calendar.py"], env=env, check=True)


if __name__ == "__main__":
    main()

