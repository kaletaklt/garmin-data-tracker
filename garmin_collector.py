import os
import json
import csv
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials

ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")
DAYS_TO_FETCH = int(os.environ.get("DAYS_TO_FETCH", 1))

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH - 1)

# 1. Pobranie wydarzeń z zakresu dat
activities_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/events?oldest={start_date.isoformat()}&newest={end_date.isoformat()}"
act_res = requests.get(activities_url, auth=("API_KEY", API_KEY))

activities_by_date = {}
if act_res.status_code == 200:
    for act in act_res.json():
        if act.get("type") != "Note":
            act_date = act.get("start_date_local", "")[:10]
            if act_date not in activities_by_date:
                activities_by_date[act_date] = []
            activities_by_date[act_date].append(act)

rows = []
curr_date = start_date

while curr_date <= end_date:
    date_str = curr_date.isoformat()
    
    # Zapytanie Wellness
    well_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness/{date_str}"
    well_res = requests.get(well_url, auth=("API_KEY", API_KEY))
    well_data = well_res.json() if well_res.status_code == 200 else {}
    
    day_acts = activities_by_date.get(date_str, [])
    
    act_names = ", ".join([a.get("name", "") for a in day_acts]) if day_acts else None
    act_types = ", ".join([a.get("type", "") for a in day_acts]) if day_acts else None
    total_moving_time = sum([a.get("moving_time", 0) for a in day_acts]) if day_acts else 0
    total_distance_km = round(sum([a.get("distance", 0) for a in day_acts]) / 1000, 2) if day_acts else 0
    total_load = sum([a.get("icu_training_load", 0) or 0 for a in day_acts]) if day_acts else 0
    
    hrs = [a.get("average_heartrate") for a in day_acts if a.get("average_heartrate")]
    avg_hr = round(sum(hrs) / len(hrs)) if hrs else None
    total_calories = sum([a.get("calories", 0) or 0 for a in day_acts]) if day_acts else 0

    # Dociąganie szczegółowej dynamiki biegu dla pierwszej aktywności biegowej danego dnia
    run_cadence = None
    run_gct = None
    run_balance = None
    run_vert_osc = None
    run_stride = None

    for act in day_acts:
        act_type = act.get("type", "")
        if act_type in ["Run", "VirtualRun", "TrailRun"]:
            act_id = act.get("id")
            if act_id:
                detail_url = f"https://intervals.icu/api/v1/activity/{act_id}"
                det_res = requests.get(detail_url, auth=("API_KEY", API_KEY))
                if det_res.status_code == 200:
                    det = det_res.json()
                    run_cadence = det.get("average_cadence")
                    if run_cadence and run_cadence < 100:  # Korekta jeśli podano kadencję jednonożną
                        run_cadence *= 2
                    
                    run_gct = det.get("avg_ground_contact_time") or det.get("ground_contact_time")
                    run_balance = det.get("avg_left_right_balance") or det.get("left_right_balance")
                    run_vert_osc = det.get("avg_vertical_oscillation") or det.get("vertical_oscillation")
                    run_stride = det.get("avg_stride_length") or det.get("stride_length")
                    if run_stride and run_stride > 10:  # Przeliczenie cm na metry w razie potrzeby
                        run_stride = round(run_stride / 100, 2)
            break

    ctl = well_data.get("ctl")
    atl = well_data.get("atl")
    tsb = round(ctl - atl, 2) if ctl is not None and atl is not None else None

    record = {
        "Data": date_str,
        # WELLNESS
        "Tetno_Spoczynkowe": well_data.get("restingHR"),
        "HRV_SDNN": well_data.get("hrv"),
        "HRV_rMSSD": well_data.get("hrvRMSSD"),
        "Sen_Wynik": well_data.get("sleepScore"),
        "Sen_Godziny": round(well_data.get("sleepSecs", 0) / 3600, 2) if well_data.get("sleepSecs") else None,
        "Sen_Gleboki_Min": round((well_data.get("deepSleepSecs") or 0) / 60) if well_data.get("deepSleepSecs") else None,
        "Sen_REM_Min": round((well_data.get("remSleepSecs") or 0) / 60) if well_data.get("remSleepSecs") else None,
        "BodyBattery": well_data.get("bodyBattery"),
        "Stres_Sredni": well_data.get("avgStress"),
        "Waga_kg": well_data.get("weight"),
        "SpO2_Srednie": well_data.get("spO2"),
        "Kroki": well_data.get("steps"),
        "Forma_Fitness_CTL": ctl,
        "Zmeczenie_Fatigue_ATL": atl,
        "Swiezosc_Form_TSB": tsb,
        
        # OGLÓNE O TRENINGACH
        "Trening_Liczba": len(day_acts),
        "Trening_Typy": act_types,
        "Trening_Nazwy": act_names,
        "Trening_Czas_Calkowity_Min": round(total_moving_time / 60, 1) if total_moving_time else 0,
        "Trening_Dystans_Km": total_distance_km,
        "Trening_Obciazenie_Load": total_load,
        "Trening_Srednie_HR": avg_hr,
        "Trening_Kalorie": total_calories,

        # DYNAMIKA BIEGU (RUNNING DYNAMICS)
        "Bieg_Kadencja": run_cadence,
        "Bieg_GCT_ms": run_gct,
        "Bieg_Balans_LP": run_balance,
        "Bieg_Odchylenie_Pionowe_mm": run_vert_osc,
        "Bieg_Dlugosc_Kroku_m": run_stride
    }
    rows.append(record)
    curr_date += datetime.timedelta(days=1)

# Zapis CSV
file_exists = os.path.isfile("garmin_data.csv")
fieldnames = rows[0].keys() if rows else []
mode = "w" if (DAYS_TO_FETCH > 1 or not file_exists) else "a"

with open("garmin_data.csv", mode=mode, newline="", encoding="utf-8") as file:
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    if mode == "w":
        writer.writeheader()
    writer.writerows(rows)

print(f"Zapisano CSV z dynamiką biegu dla {len(rows)} dni.")

# Zapis Google Sheets
if GSPREAD_CREDENTIALS and GOOGLE_SHEET_ID:
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds_dict = json.loads(GSPREAD_CREDENTIALS)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

        existing_values = sheet.get_all_values()
        
        if not existing_values:
            sheet.append_row(list(fieldnames))
            existing_dates = set()
        else:
            # Aktualizujemy nagłówek jeśli doszły nowe kolumny
            if len(existing_values[0]) < len(fieldnames):
                sheet.update('A1', [list(fieldnames)])
            existing_dates = {row[0] for row in existing_values[1:] if row}

        new_rows_to_append = []
        for r in rows:
            if r["Data"] not in existing_dates:
                row_vals = [("" if v is None else v) for v in r.values()]
                new_rows_to_append.append(row_vals)

        if new_rows_to_append:
            sheet.append_rows(new_rows_to_append)
            print(f"Dodano {len(new_rows_to_append)} wierszy do Google Sheets.")
        else:
            print("Brak nowych wierszy do wpisania.")
    except Exception as e:
        print(f"Błąd Google Sheets: {e}")
