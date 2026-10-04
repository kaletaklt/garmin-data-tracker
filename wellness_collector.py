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
DAYS_TO_FETCH = 2

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH - 1)

rows = []
curr_date = start_date

while curr_date <= end_date:
    date_str = curr_date.isoformat()
    
    # Zapytanie Wellness
    well_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness/{date_str}"
    well_res = requests.get(well_url, auth=("API_KEY", API_KEY))
    well_data = well_res.json() if well_res.status_code == 200 else {}
    
    ctl = well_data.get("ctl")
    atl = well_data.get("atl")
    tsb = round(ctl - atl, 2) if ctl is not None and atl is not None else None
    sleep_secs = well_data.get("sleepSecs")

    record = {
        "Data": date_str,
        "Waga_kg": well_data.get("weight"),
        "Tkanka_Tluszczowa_Pct": well_data.get("bodyFat"),
        "Tetno_Spoczynkowe": well_data.get("restingHR"),
        "HRV_SDNN": well_data.get("hrv"),
        "HRV_rMSSD": well_data.get("hrvRMSSD"),
        "Sen_Wynik": well_data.get("sleepScore") or well_data.get("sleepQuality"),
        "Sen_Godziny": round(sleep_secs / 3600, 2) if sleep_secs else None,
        "Sen_Gleboki_Min": round((well_data.get("deepSleepSecs") or 0) / 60) if well_data.get("deepSleepSecs") else None,
        "Sen_Lekki_Min": round((well_data.get("lightSleepSecs") or 0) / 60) if well_data.get("lightSleepSecs") else None,
        "Sen_REM_Min": round((well_data.get("remSleepSecs") or 0) / 60) if well_data.get("remSleepSecs") else None,
        "Sen_Czuwanie_Min": round((well_data.get("awakeSleepSecs") or 0) / 60) if well_data.get("awakeSleepSecs") else None,
        "Oddech_Noc_rpm": well_data.get("respiration"),
        "BodyBattery": well_data.get("bodyBattery"),
        "Stres_Sredni": well_data.get("avgStress"),
        "SpO2_Srednie": well_data.get("spO2"),
        "Kroki": well_data.get("steps") if well_data.get("steps") is not None else 0,
        "Kalorie_Aktywne": well_data.get("activeCalories") or well_data.get("kcalConsumed") or 0,
        "VO2Max": well_data.get("vo2max"),
        "Forma_Fitness_CTL": ctl,
        "Zmeczenie_Fatigue_ATL": atl,
        "Swiezosc_Form_TSB": tsb,
        "Ramp_Rate": well_data.get("rampRate")
    }
    rows.append(record)
    curr_date += datetime.timedelta(days=1)

# Alerty
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

    rhr = record.get("Tetno_Spoczynkowe")
    if rhr and prev_records:
        recent_rhrs = [r.get("Tetno_Spoczynkowe") for r in prev_records if r.get("Tetno_Spoczynkowe")]
        if len(recent_rhrs) >= 3:
            avg_rhr = sum(recent_rhrs[-7:]) / len(recent_rhrs[-7:])
            if rhr >= avg_rhr + 5: alerts.append(f"⚠️ Podwyższone RHR: {rhr} bpm (średnia: {round(avg_rhr,1)} bpm).")

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

# ZAPIS CSV
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
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        try:
            sheet = spreadsheet.worksheet("Wellness")
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title="Wellness", rows="1000", cols="30")
        
        existing_vals = sheet.get_all_values()
        if not existing_vals:
            sheet.append_row(fieldnames)
            existing_map = {}
        else:
            if len(existing_vals[0]) < len(fieldnames): sheet.update('A1', [fieldnames])
            existing_map = {row[0]: idx + 1 for idx, row in enumerate(existing_vals) if row}

        for r in rows:
            row_vals = [("" if v is None else v) for v in r.values()]
            if r["Data"] in existing_map: sheet.update(f"A{existing_map[r['Data']]}", [row_vals])
            else: sheet.append_row(row_vals)
    except Exception as e: print(e)
