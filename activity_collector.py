import os
import json
import csv
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")
DAYS_TO_FETCH = 7 # Skrypt przeszukuje ostatnie 7 dni pod kątem wykonanych aktywności

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH)

# ZAPYTANIE O WYKONANE AKTYWNOŚCI (NIE Z KALENDARZA!)
act_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities?oldest={start_date.isoformat()}&newest={end_date.isoformat()}"
act_res = requests.get(act_url, auth=("API_KEY", API_KEY))

rows = []
if act_res.status_code == 200:
    for act in act_res.json():
        act_id = act.get("id")
        if not act_id: continue
        
        # Pobranie szczegółów pojedynczego treningu
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
            "Czas_Ruchu_Min": round(act.get("moving_time", 0) / 60, 1),
            "Dystans_Km": round(act.get("distance", 0) / 1000, 2),
            "Obciazenie_TSS": act.get("icu_training_load"),
            "Intensywnosc_IF": round(act.get("icu_intensity", 0), 2) if act.get("icu_intensity") else None,
            "Srednie_HR": act.get("average_heartrate"),
            "Max_HR": act.get("max_heartrate"),
            "Kalorie": act.get("calories"),
            "Przewyzszenia_W_Gore_m": act.get("total_elevation_gain"),
            "Przewyzszenia_W_Dol_m": act.get("total_elevation_loss"),
            
            # Strefy HR
            "Strefa_Z1_Min": z1, "Strefa_Z2_Min": z2, "Strefa_Z3_Min": z3, "Strefa_Z4_Min": z4, "Strefa_Z5_Min": z5,
            
            # Moc i Dynamika Biegu
            "Srednia_Moc_W": det.get("icu_average_watts") or det.get("average_watts"),
            "Moc_NP_W": det.get("icu_weighted_avg_watts"),
            "Kadencja_Srednia": det.get("average_cadence") * 2 if det.get("average_cadence") and det.get("average_cadence") < 100 else det.get("average_cadence"),
            "Balans_L_P": det.get("avg_left_right_balance") or det.get("left_right_balance"),
            "Czas_Kontaktu_GCT_ms": det.get("avg_ground_contact_time") or det.get("ground_contact_time"),
            "Odchylenie_Pionowe_mm": det.get("avg_vertical_oscillation") or det.get("vertical_oscillation"),
            "Dlugosc_Kroku_m": round(det.get("avg_stride_length") / 100, 2) if det.get("avg_stride_length") and det.get("avg_stride_length") > 10 else det.get("avg_stride_length"),
            "Temperatura_C": det.get("average_temp")
        }
        rows.append(record)

# Alerty biomechaniczne po wykonanym treningu
def check_activity_alerts(record):
    sender, password, receiver = os.environ.get("EMAIL_SENDER"), os.environ.get("EMAIL_PASSWORD"), os.environ.get("EMAIL_RECEIVER")
    if not (sender and password and receiver): return

    alerts = []
    balance_str = record.get("Balans_L_P")
    if balance_str and "/" in str(balance_str):
        try:
            left_val = float(str(balance_str).split("/")[0].strip())
            if left_val < 48.5 or left_val > 51.5:
                alerts.append(f"⚠️ Zaburzona symetria biegu (Balans L/P): {balance_str}. Wskazuje to na znaczne odciążanie prawego uda/biodra.")
        except ValueError: pass

    if alerts:
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = sender, receiver, f"🚨 ALERT BIOMECHANICZNY - {record.get('Nazwa')}"
        body = f"Podczas ostatniego treningu ({record.get('Data')}) wystąpiły odchylenia w technice:\n\n" + "\n".join([f"- {a}" for a in alerts])
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender, password)
                server.sendmail(sender, receiver, msg.as_string())
        except Exception as e: print(e)

if rows:
    check_activity_alerts(rows[-1]) # Sprawdza tylko ostatni wykonany trening

# ZAPIS CSV
csv_file = "activities_data.csv"
existing_data = {}
fieldnames = list(rows[0].keys()) if rows else []
if os.path.isfile(csv_file):
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames: fieldnames = reader.fieldnames
        for row in reader: existing_data[row["ID_Aktywnosci"]] = row

for r in rows: existing_data[r["ID_Aktywnosci"]] = {k: ("" if v is None else v) for k, v in r.items()}
with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    # Sortowanie od najstarszego do najnowszego
    for d in sorted(existing_data.keys(), key=lambda k: existing_data[k]["Data"]): writer.writerow(existing_data[d])

# ZAPIS GOOGLE SHEETS
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
            if len(existing_vals[0]) < len(fieldnames): sheet.update('A1', [fieldnames])
            existing_map = {row[0]: idx + 1 for idx, row in enumerate(existing_vals) if row}

        for r in rows:
            row_vals = [("" if v is None else v) for v in r.values()]
            if r["ID_Aktywnosci"] in existing_map: sheet.update(f"A{existing_map[r['ID_Aktywnosci']]}", [row_vals])
            else: sheet.append_row(row_vals)
    except Exception as e: print(e)
