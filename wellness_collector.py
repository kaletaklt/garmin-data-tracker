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
from garminconnect import Garmin

# Konfiguracja
GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")
ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")
DAYS_TO_FETCH = 2

# Logowanie do Garmina
try:
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()
except Exception as e:
    print(f"Błąd logowania do Garmina: {e}")
    exit(1)

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH - 1)

rows = []
curr_date = start_date

while curr_date <= end_date:
    date_str = curr_date.isoformat()
    
    # 1. Pobieranie dokładnych danych bezpośrednio z Garmina
    stats = client.get_stats(date_str) or {}
    sleep = client.get_sleep_data(date_str) or {}
    hrv_data = client.get_hrv_data(date_str) or {}
    
    # Przetwarzanie snu z Garmina
    daily_sleep = sleep.get('dailySleepDTO', {})
    sleep_score = daily_sleep.get('sleepScores', {}).get('overall', {}).get('value')
    
    deep_min = round(daily_sleep.get('deepSleepSeconds', 0) / 60)
    light_min = round(daily_sleep.get('lightSleepSeconds', 0) / 60)
    rem_min = round(daily_sleep.get('remSleepSeconds', 0) / 60)
    awake_min = round(daily_sleep.get('awakeSleepSeconds', 0) / 60)
    total_sleep_hours = round(daily_sleep.get('sleepTimeSeconds', 0) / 3600, 2)
    
    # Przetwarzanie HRV i Stresu
    hrv_avg = hrv_data.get('hrvSummary', {}).get('lastNightAvg')
    
    # 2. Pobieranie modelu Fitness/Fatigue z Intervals.icu
    well_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness/{date_str}"
    well_res = requests.get(well_url, auth=("API_KEY", API_KEY))
    well_data = well_res.json() if well_res.status_code == 200 else {}
    
    ctl = well_data.get("ctl")
    atl = well_data.get("atl")
    tsb = round(ctl - atl, 2) if ctl is not None and atl is not None else None

    # Tworzenie rekordu
    record = {
        "Data": date_str,
        "Waga_kg": well_data.get("weight"), # Wagę często dopisujesz w Intervals lub z wagi
        "Tkanka_Tluszczowa_Pct": well_data.get("bodyFat"),
        "Tetno_Spoczynkowe": stats.get('restingHeartRate'),
        "HRV_rMSSD": hrv_avg,
        "Sen_Wynik": sleep_score,
        "Sen_Godziny": total_sleep_hours if total_sleep_hours > 0 else None,
        "Sen_Gleboki_Min": deep_min if deep_min > 0 else None,
        "Sen_Lekki_Min": light_min if light_min > 0 else None,
        "Sen_REM_Min": rem_min if rem_min > 0 else None,
        "Sen_Czuwanie_Min": awake_min if awake_min > 0 else None,
        "BodyBattery_Max": stats.get('maxBodyBattery'),
        "BodyBattery_Min": stats.get('minBodyBattery'),
        "Stres_Sredni": stats.get('averageStressLevel'),
        "Kroki": stats.get('totalSteps', 0),
        "Kalorie_Aktywne": stats.get('activeKilocalories', 0),
        "Forma_Fitness_CTL": ctl,
        "Zmeczenie_Fatigue_ATL": atl,
        "Swiezosc_Form_TSB": tsb
    }
    rows.append(record)
    curr_date += datetime.timedelta(days=1)

# Alerty e-mailowe (bez zmian)
def check_wellness_alerts(record, prev_records=None):
    sender, password, receiver = os.environ.get("EMAIL_SENDER"), os.environ.get("EMAIL_PASSWORD"), os.environ.get("EMAIL_RECEIVER")
    if not (sender and password and receiver): return

    alerts = []
    tsb = record.get("Swiezosc_Form_TSB")
    if tsb is not None and tsb < -25:
        alerts.append(f"⚠️ Bardzo niskie TSB: {tsb}. Ryzyko przetrenowania.")
        
    hrv = record.get("HRV_rMSSD")
    if hrv and prev_records:
        recent_hrvs = [r.get("HRV_rMSSD") for r in prev_records if r.get("HRV_rMSSD")]
        if len(recent_hrvs) >= 3:
            avg_hrv = sum(recent_hrvs[-7:]) / len(recent_hrvs[-7:])
            if hrv < avg_hrv * 0.85: alerts.append(f"⚠️ Spadek HRV: {hrv} ms (średnia: {round(avg_hrv,1)} ms).")

    if alerts:
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = sender, receiver, f"🚨 OSTRZEŻENIE REGENERACYJNE [{record.get('Data')}]"
        body = "Wykryto słabszą regenerację:\n\n" + "\n".join([f"- {a}" for a in alerts])
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender, password)
                server.sendmail(sender, receiver, msg.as_string())
        except Exception as e: print(e)

if rows: check_wellness_alerts(rows[-1], rows[:-1])

# ZAPIS CSV (UPSERT)
csv_file = "wellness_data.csv"
existing_data = {}
fieldnames = list(rows[0].keys())
if os.path.isfile(csv_file):
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames: fieldnames = reader.fieldnames
        for row in reader: existing_data[row["Data"]] = row

for r in rows: existing_data[r["Data"]] = {k: ("" if v is None else v) for k, v in r.items()}
with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for d in sorted(existing_data.keys()): writer.writerow(existing_data[d])

# ZAPIS GOOGLE SHEETS
if GSPREAD_CREDENTIALS and GOOGLE_SHEET_ID:
    try:
        creds = Credentials.from_service_account_info(json.loads(GSPREAD_CREDENTIALS), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client_gs = gspread.authorize(creds)
        spreadsheet = client_gs.open_by_key(GOOGLE_SHEET_ID)
        try:
            sheet = spreadsheet.worksheet("Wellness")
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title="Wellness", rows="1000", cols="30")
        
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
            if r["Data"] in existing_map: 
                sheet.update(range_name=f"A{existing_map[r['Data']]}", values=[row_vals])
            else: 
                sheet.append_row(row_vals)
    except Exception as e: print(e)
