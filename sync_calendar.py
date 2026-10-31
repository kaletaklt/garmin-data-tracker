import os
import re
import json
import requests
import datetime
import gspread

# Importujemy nasze gotowe klasy z poprzedniego skryptu!
from garmin_auth import GarminAuthenticator
from add_workout import WorkoutStepParser, GarminWorkoutBuilder, WorkoutManager

SPREADSHEET_ID = "1qpQ2OCTqqu7QrMl_O8Rs-cwwoYHPG1TEGV6JuD-RsIg"
JOIN_API_KEY = "29f49de67d054e8b92b7eaa47f122ea3"
JOIN_DEVICE_ID = "8160dbfac44d43ab956ca34412064bda"

def send_join_alert(date_str, workout_name):
    # Zlepiamy dane w jeden string rozdzielony =:= aby Tasker łatwo to odczytał
    text = f"garmin_alert=:={date_str}=:={workout_name}"
    url = "https://joinjoaomgcd.appspot.com/_ah/api/messaging/v1/sendPush"
    params = {
        "apikey": JOIN_API_KEY,
        "deviceId": JOIN_DEVICE_ID,
        "text": text
    }
    try:
        requests.get(url, params=params)
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

def parse_and_upload(garmin_client, workout_code, target_date, workout_name):
    raw_workout_code = workout_code.replace(r'\n', '\n')
    lines = [line.strip() for line in raw_workout_code.split('\n') if line.strip()]
    
    manager = WorkoutManager(garmin_client)
    parser = WorkoutStepParser()
    builder = GarminWorkoutBuilder(workout_name)
    
    valid_types = {"warmup", "interval", "recovery", "cooldown"}
    
    # Pomijamy pierwszą linię z kodem (bo to nagłówek z datą)
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
    records = sheet.get_all_records()
    
    sheet_workouts = {} 
    
    # ---------------------------------------------------------
    # FAZA 1: Wgrywanie z Arkusza do Garmina
    # ---------------------------------------------------------
    for idx, row in enumerate(records):
        row_idx = idx + 2 # Wiersz 1 to nagłówki
        date_str = str(row.get("Data", "")).strip()
        name_str = str(row.get("Nazwa", "")).strip()
        code_str = str(row.get("Kod Treningu", "")).strip()
        status = str(row.get("Status", "")).strip()
        
        if not date_str or not code_str:
            continue
            
        sheet_workouts[date_str] = name_str
            
        if status.lower() != "zaplanowane":
            print(f"Znaleziono nowy trening do wgrania: {date_str} - {name_str}")
            try:
                parse_and_upload(garmin_client, code_str, date_str, name_str)
                sheet.update_cell(row_idx, 4, "Zaplanowane") # Zapis do kolumny Status
                print(f"Sukces! Zaktualizowano arkusz.")
            except Exception as e:
                print(f"Błąd podczas planowania {date_str}: {e}")

    # ---------------------------------------------------------
    # FAZA 2: Sprawdzanie Garmina (czy są nieautoryzowane treningi)
    # ---------------------------------------------------------
    print("Sprawdzanie kalendarza Garmin...")
    try:
        today = datetime.date.today()
        # Pobieramy kalendarz na bieżący miesiąc
        cal = garmin_client.get_training_calendar(today.year, today.month)
        
        # Jeśli jesteśmy pod koniec miesiąca, sprawdzamy też kolejny
        if today.day > 20:
            next_m = today.month + 1 if today.month < 12 else 1
            next_y = today.year if today.month < 12 else today.year + 1
            cal.extend(garmin_client.get_training_calendar(next_y, next_m))
            
        for item in cal:
            date_str = item.get("date")
            title = item.get("title")
            
            # Odfiltrowujemy treningi (pomijamy np. cele krokowe czy przebyte aktywności)
            if item.get("itemType") == "workout" and date_str:
                item_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                
                # Sprawdzamy tylko przyszłość i dzień dzisiejszy
                if item_date >= today:
                    if date_str not in sheet_workouts:
                        print(f"UWAGA: Nieznany trening w Garminie: {date_str} ({title})")
                        send_join_alert(date_str, title)
                        
    except Exception as e:
        print(f"Błąd podczas analizy kalendarza Garmina: {e}")

if __name__ == "__main__":
    main()
