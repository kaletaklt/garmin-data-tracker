import os
import re
import json
import requests
import datetime
import gspread

from garmin_auth import GarminAuthenticator
from add_workout import WorkoutStepParser, GarminWorkoutBuilder, WorkoutManager

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
JOIN_API_KEY = os.getenv("JOIN_API_KEY")
JOIN_DEVICE_ID = os.getenv("JOIN_DEVICE_ID")


def send_join_alert(date_str, workout_name):
    if not JOIN_API_KEY or not JOIN_DEVICE_ID:
        print(f"Pominięto alert Join (brak klucza/ID) dla: {workout_name} ({date_str})")
        return
    text = f"garmin_alert=:={date_str}=:={workout_name}"
    url = "https://joinjoaomgcd.appspot.com/_ah/api/messaging/v1/sendPush"
    params = {"apikey": JOIN_API_KEY, "deviceId": JOIN_DEVICE_ID, "text": text}
    try:
        requests.get(url, params=params, timeout=10)
        print(f"Wysłano alert do Taskera o nieznanym treningu: {workout_name} ({date_str})")
    except Exception as e:
        print(f"Błąd wysyłania alertu: {e}")


def get_google_sheet():
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("Brak zmiennej GSPREAD_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    gc = gspread.service_account_from_dict(creds_dict)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet("Treningi")


def get_garmin_calendar_items(garmin_client, year, month):
    """Pobiera elementy kalendarza Garmin Connect (miesiące w API Garmina są indeksowane od 0 do 11)."""
    endpoint = f"/calendar-service/year/{year}/month/{month - 1}"
    data = garmin_client.connectapi(endpoint)
    if isinstance(data, dict):
        return data.get("calendarItems", [])
    return []


def delete_existing_workouts_on_date(garmin_client, target_date):
    try:
        dt = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
        items = get_garmin_calendar_items(garmin_client, dt.year, dt.month)
        for item in items:
            if item.get("itemType") == "workout" and item.get("date") == target_date:
                wid = item.get("workoutId")
                if wid:
                    garmin_client.connectapi(f"/workout-service/workout/{wid}", method="DELETE")
                    print(f"Usunięto poprzednią wersję treningu z dnia {target_date} (ID: {wid}).")
    except Exception as e:
        print(f"Uwaga przy czyszczeniu starego treningu ({target_date}): {e}")


def parse_and_upload(garmin_client, workout_code, target_date, workout_name):
    raw_workout_code = workout_code.replace(r'\n', '\n')
    lines = [line.strip() for line in raw_workout_code.split('\n') if line.strip()]

    manager = WorkoutManager(garmin_client)
    parser = WorkoutStepParser()
    builder = GarminWorkoutBuilder(workout_name)

    valid_types = {"warmup", "interval", "recovery", "cooldown"}

    for line in lines[1:]:
        line = line.lstrip(', ').strip()
        parts = re.split(r'[\s,]+', line, maxsplit=1)
        if len(parts) < 2:
            continue
        step_type = parts[0].lower()
        text = parts[1].lstrip(', ').strip()
        if step_type in valid_types:
            builder.add_step(parser.parse(step_type, text))

    manager.upload_and_schedule(builder.get_payload(), target_date)


def main():
    print("Logowanie do Garmin Connect...")
    garmin_client = GarminAuthenticator().login()

    print("Pobieranie zakładki 'Treningi' z Google Sheets...")
    sheet = get_google_sheet()
    all_values = sheet.get_all_values()

    if len(all_values) < 2:
        print("Brak wpisów w zakładce 'Treningi'.")
        return

    sheet_workouts = {}

    # FAZA 1: Wgrywanie / Aktualizacja z Arkusza do Garmina
    for idx, row in enumerate(all_values[1:]):
        row_idx = idx + 2
        date_str = str(row[0]).strip() if len(row) > 0 else ""
        name_str = str(row[1]).strip() if len(row) > 1 else ""
        code_str = str(row[2]).strip() if len(row) > 2 else ""
        status = str(row[3]).strip() if len(row) > 3 else ""

        if not date_str or not code_str:
            continue

        sheet_workouts[date_str] = name_str

        if code_str.upper() == "REST" or status.lower().startswith("zaplanowane"):
            if status.lower() == "do aktualizacji" and code_str.upper() == "REST":
                delete_existing_workouts_on_date(garmin_client, date_str)
                sheet.update_cell(row_idx, 4, "Zaplanowane (Bez biegu)")
            continue

        print(f"Przetwarzanie treningu: {date_str} - {name_str} (Status: {status})")
        try:
            if status.lower() == "do aktualizacji":
                delete_existing_workouts_on_date(garmin_client, date_str)
            parse_and_upload(garmin_client, code_str, date_str, name_str)
            sheet.update_cell(row_idx, 4, "Zaplanowane")
            print("Sukces! Zaktualizowano arkusz i kalendarz Garmin.")
        except Exception as e:
            print(f"Błąd podczas planowania {date_str}: {e}")

    # FAZA 2: Sprawdzanie Garmina (nieautoryzowane treningi)
    print("Sprawdzanie kalendarza Garmin...")
    try:
        today = datetime.date.today()
        cal_items = get_garmin_calendar_items(garmin_client, today.year, today.month)

        if today.day > 20:
            next_m = today.month + 1 if today.month < 12 else 1
            next_y = today.year if today.month < 12 else today.year + 1
            cal_items.extend(get_garmin_calendar_items(garmin_client, next_y, next_m))

        for item in cal_items:
            date_str = item.get("date")
            title = item.get("title")

            if item.get("itemType") == "workout" and date_str:
                item_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                if item_date >= today and date_str not in sheet_workouts:
                    print(f"UWAGA: Nieznany trening w Garminie: {date_str} ({title})")
                    send_join_alert(date_str, title)

    except Exception as e:
        print(f"Błąd podczas analizy kalendarza Garmina: {e}")


if __name__ == "__main__":
    main()
