import os
import json
import csv
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials

ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")
DAYS_TO_FETCH = 7 

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH)

act_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities?oldest={start_date.isoformat()}&newest={end_date.isoformat()}"
act_res = requests.get(act_url, auth=("API_KEY", API_KEY))

rows = []
if act_res.status_code == 200:
    for act in act_res.json():
        act_id = act.get("id")
        if not act_id: continue
        
        det_url = f"https://intervals.icu/api/v1/activity/{act_id}"
        det_res = requests.get(det_url, auth=("API_KEY", API_KEY))
        det = det_res.json() if det_res.status_code == 200 else act
        
        hr_zones = det.get("icu_hr_zones") or []
        z1 = round((hr_zones[0] or 0) / 60, 1) if len(hr_zones) > 0 else None
        z2 = round((hr_zones[1] or 0) / 60, 1) if len(hr_zones) > 1 else None
        z3 = round((hr_zones[2] or 0) / 60, 1) if len(hr_zones) > 2 else None
        z4 = round((hr_zones[3] or 0) / 60, 1) if len(hr_zones) > 3 else None
        z5 = round((hr_zones[4] or 0) / 60, 1) if len(hr_zones) > 4 else None

        record = {
            "ID_Aktywnosci": str(act_id),
            "Data": act.get("start_date_local", "")[:10],
            "Godzina_Rozpoczecia": act.get("start_date_local", "")[11:16],
            "Nazwa": act.get("name"),
            "Typ": act.get("type"),
            "Czas_Ruchu_Min": round((act.get("moving_time") or 0) / 60, 1),
            "Dystans_Km": round((act.get("distance") or 0) / 1000, 2),
            "Obciazenie_TSS": act.get("icu_training_load"),
            "Intensywnosc_IF": round(act.get("icu_intensity", 0), 2) if act.get("icu_intensity") else None,
            "Srednie_HR": act.get("average_heartrate"),
            "Max_HR": act.get("max_heartrate"),
            "Kalorie": act.get("calories"),
            "Przewyzszenia_W_Gore_m": act.get("total_elevation_gain"),
            
            "Strefa_Z1_Min": z1, "Strefa_Z2_Min": z2, "Strefa_Z3_Min": z3, "Strefa_Z4_Min": z4, "Strefa_Z5_Min": z5,
            
            "Kadencja_Srednia": det.get("average_cadence") * 2 if det.get("average_cadence") and det.get("average_cadence") < 100 else det.get("average_cadence"),
            "Balans_L_P": det.get("avg_left_right_balance") or det.get("left_right_balance"),
            "Czas_Kontaktu_GCT_ms": det.get("avg_ground_contact_time") or det.get("ground_contact_time"),
            "Dlugosc_Kroku_m": round(det.get("avg_stride_length") / 100, 2) if det.get("avg_stride_length") and det.get("avg_stride_length") > 10 else det.get("avg_stride_length")
        }
        rows.append(record)

csv_file = "activities_data.csv"
existing_data = {}
fieldnames = list(rows[0].keys()) if rows else []
if os.path.isfile(csv_file):
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames: fieldnames = reader.fieldnames
        for row in reader: existing_data[row["ID_Aktywnosci"]] = row

for r in rows: existing_data[r["ID_Aktywnosci"]] = {k: ("" if v is None else v) for k, v in r.items()}
if existing_data:
    with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in sorted(existing_data.keys(), key=lambda k: existing_data[k]["Data"]): writer.writerow(existing_data[d])

if GSPREAD_CREDENTIALS and GOOGLE_SHEET_ID and rows:
    try:
        creds = Credentials.from_service_account_info(json.loads(GSPREAD_CREDENTIALS), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        
        try:
            sheet = spreadsheet.worksheet("Aktywnosci")
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title="Aktywnosci", rows="1000", cols="30")
        
        existing_vals = sheet.get_all_values()
        if not existing_vals:
            sheet.append_row(fieldnames)
            existing_map = {}
        else:
            if len(existing_vals[0]) < len(fieldnames): 
                sheet.update(range_name='A1', values=[fieldnames])
            existing_map = {row[0]: idx + 1 for idx, row in enumerate(existing_vals) if row}

        for r in rows:
            row_vals = [("" if v is None else v) for v in r.values()]
            if r["ID_Aktywnosci"] in existing_map: 
                sheet.update(range_name=f"A{existing_map[r['ID_Aktywnosci']]}", values=[row_vals])
            else: 
                sheet.append_row(row_vals)
    except Exception as e: print(e)
