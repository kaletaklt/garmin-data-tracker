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

# Pobieramy 2 dni: wczoraj (dla zamknięcia i weryfikacji) oraz dzisiaj (dla bieżącej aktualizacji)
DAYS_TO_FETCH = 2

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH - 1)

# 1. Pobranie aktywności z danego zakresu dat
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
    
    # --- Zapytanie Wellness ---
    well_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness/{date_str}"
    well_res = requests.get(well_url, auth=("API_KEY", API_KEY))
    well_data = well_res.json() if well_res.status_code == 200 else {}
    
    day_acts = activities_by_date.get(date_str, [])
    
    act_names = ", ".join([a.get("name", "") for a in day_acts]) if day_acts else None
    act_types = ", ".join([a.get("type", "") for a in day_acts]) if day_acts else None
    total_moving_time = sum([a.get("moving_time", 0) for a in day_acts]) if day_acts else 0
    total_distance_km = round(sum([a.get("distance", 0) for a in day_acts]) / 1000, 2) if day_acts else 0
    total_load = sum([a.get("icu_training_load", 0) or 0 for a in day_acts]) if day_acts else 0
    
    # Tętna i kalorie z aktywności
    hrs = [a.get("average_heartrate") for a in day_acts if a.get("average_heartrate")]
    max_hrs = [a.get("max_heartrate") for a in day_acts if a.get("max_heartrate")]
    avg_hr = round(sum(hrs) / len(hrs)) if hrs else None
    max_hr = max(max_hrs) if max_hrs else None
    total_calories = sum([a.get("calories", 0) or 0 for a in day_acts]) if day_acts else 0

    # Przewyższenia
    total_elev_gain = sum([a.get("total_elevation_gain", 0) or 0 for a in day_acts]) if day_acts else 0
    total_elev_loss = sum([a.get("total_elevation_loss", 0) or 0 for a in day_acts]) if day_acts else 0

    # Zmienne szczegółowe dla biegów i stref HR
    run_cadence_avg = None
    run_cadence_max = None
    run_gct = None
    run_balance = None
    run_vert_osc = None
    run_stride = None
    run_power_avg = None
    run_power_max = None

    hr_z1 = hr_z2 = hr_z3 = hr_z4 = hr_z5 = 0

    for act in day_acts:
        act_id = act.get("id")
        if act_id:
            detail_url = f"https://intervals.icu/api/v1/activity/{act_id}"
            det_res = requests.get(detail_url, auth=("API_KEY", API_KEY))
            if det_res.status_code == 200:
                det = det_res.json()

                # Zbieranie stref tętna (sekundy -> minuty)
                icu_hr_zones = det.get("icu_hr_zones") or []
                if len(icu_hr_zones) >= 5:
                    hr_z1 += round((icu_hr_zones[0] or 0) / 60, 1)
                    hr_z2 += round((icu_hr_zones[1] or 0) / 60, 1)
                    hr_z3 += round((icu_hr_zones[2] or 0) / 60, 1)
                    hr_z4 += round((icu_hr_zones[3] or 0) / 60, 1)
                    hr_z5 += round((icu_hr_zones[4] or 0) / 60, 1)

                # Dynamika biegu i moc biegowa
                act_type = act.get("type", "")
                if act_type in ["Run", "VirtualRun", "TrailRun"]:
                    cad = det.get("average_cadence")
                    if cad and cad < 100: cad *= 2
                    run_cadence_avg = cad
                    
                    max_cad = det.get("max_cadence")
                    if max_cad and max_cad < 100: max_cad *= 2
                    run_cadence_max = max_cad

                    run_gct = det.get("avg_ground_contact_time") or det.get("ground_contact_time")
                    run_balance = det.get("avg_left_right_balance") or det.get("left_right_balance")
                    run_vert_osc = det.get("avg_vertical_oscillation") or det.get("vertical_oscillation")
                    
                    stride = det.get("avg_stride_length") or det.get("stride_length")
                    if stride and stride > 10: stride = round(stride / 100, 2)
                    run_stride = stride

                    run_power_avg = det.get("icu_average_watts") or det.get("average_watts")
                    run_power_max = det.get("max_watts")

    # Wskaźniki formy i regeneracji
    ctl = well_data.get("ctl")
    atl = well_data.get("atl")
    tsb = round(ctl - atl, 2) if ctl is not None and atl is not None else None

    # Obsługa czasu snu
    sleep_secs = well_data.get("sleepSecs")
    sleep_hours = round(sleep_secs / 3600, 2) if sleep_secs else None

    record = {
        "Data": date_str,
        
        # --- REGENERACJA & KONDYCJA (WELLNESS) ---
        "Tetno_Spoczynkowe": well_data.get("restingHR"),
        "HRV_SDNN": well_data.get("hrv"),
        "HRV_rMSSD": well_data.get("hrvRMSSD"),
        "Sen_Wynik": well_data.get("sleepScore") or well_data.get("sleepQuality"),
        "Sen_Godziny": sleep_hours,
        "Sen_Gleboki_Min": round((well_data.get("deepSleepSecs") or 0) / 60) if well_data.get("deepSleepSecs") else 0,
        "Sen_Lekki_Min": round((well_data.get("lightSleepSecs") or 0) / 60) if well_data.get("lightSleepSecs") else 0,
        "Sen_REM_Min": round((well_data.get("remSleepSecs") or 0) / 60) if well_data.get("remSleepSecs") else 0,
        "Sen_Czuwanie_Min": round((well_data.get("awakeSleepSecs") or 0) / 60) if well_data.get("awakeSleepSecs") else 0,
        "Oddech_Noc_rpm": well_data.get("respiration"),
        "BodyBattery": well_data.get("bodyBattery"),
        "Stres_Sredni": well_data.get("avgStress"),
        "Waga_kg": well_data.get("weight"),
        "SpO2_Srednie": well_data.get("spO2"),
        "Kroki": well_data.get("steps") if well_data.get("steps") is not None else 0,
        "Kalorie_Aktywne": well_data.get("activeCalories") or well_data.get("kcalConsumed") or 0,
        "VO2Max": well_data.get("vo2max"),

        # --- MODEL FORMY & ZMĘCZENIA (INTERVALS) ---
        "Forma_Fitness_CTL": ctl,
        "Zmeczenie_Fatigue_ATL": atl,
        "Swiezosc_Form_TSB": tsb,
        "Ramp_Rate": well_data.get("rampRate"),

        # --- PODSUMOWANIE TRENINGÓW ---
        "Trening_Liczba": len(day_acts),
        "Trening_Typy": act_types,
        "Trening_Nazwy": act_names,
        "Trening_Czas_Calkowity_Min": round(total_moving_time / 60, 1) if total_moving_time else 0,
        "Trening_Dystans_Km": total_distance_km,
        "Trening_Obciazenie_Load": total_load,
        "Trening_Intensywnosc_IF": round(day_acts[0].get("icu_intensity", 0), 2) if day_acts and day_acts[0].get("icu_intensity") else None,
        "Trening_Srednie_HR": avg_hr,
        "Trening_Max_HR": max_hr,
        "Trening_Kalorie": total_calories,
        "Przewyszenia_Gora_m": total_elev_gain,
        "Przewyszenia_Dol_m": total_elev_loss,

        # --- STREFY TĘTNA (MINUTY) ---
        "Strefa_HR_Z1_Min": hr_z1,
        "Strefa_HR_Z2_Min": hr_z2,
        "Strefa_HR_Z3_Min": hr_z3,
        "Strefa_HR_Z4_Min": hr_z4,
        "Strefa_HR_Z5_Min": hr_z5,

        # --- DYNAMIKA BIEGU I MOC ---
        "Bieg_Moc_Srednia_W": run_power_avg,
        "Bieg_Moc_Max_W": run_power_max,
        "Bieg_Kadencja_Srednia": run_cadence_avg,
        "Bieg_Kadencja_Max": run_cadence_max,
        "Bieg_GCT_ms": run_gct,
        "Bieg_Balans_LP": run_balance,
        "Bieg_Odchylenie_Pionowe_mm": run_vert_osc,
        "Bieg_Dlugosc_Kroku_m": run_stride
    }
    rows.append(record)
    curr_date += datetime.timedelta(days=1)

# --- FUNKCJA SPRAWDZAJĄCA ALERTY I WYSYŁAJĄCA E-MAIL ---
def check_and_send_alerts(record, prev_records=None):
    sender = os.environ.get("EMAIL_SENDER")
    password = os.environ.get("EMAIL_PASSWORD")
    receiver = os.environ.get("EMAIL_RECEIVER")

    if not (sender and password and receiver):
        print("Brak danych konfiguracji e-mail w Secrets. Pomijam sprawdzanie alertów.")
        return

    alerts = []
    
    tsb = record.get("Swiezosc_Form_TSB")
    if tsb is not None and tsb < -25:
        alerts.append(f"⚠️ Bardzo niskie TSB (Świeżość): {tsb}. Wysokie ryzyko przetrenowania.")

    balance_str = record.get("Bieg_Balans_LP")
    if balance_str and "/" in str(balance_str):
        try:
            left_val = float(str(balance_str).split("/")[0].strip())
            if left_val < 48.5 or left_val > 51.5:
                alerts.append(f"⚠️ Zaburzona symetria biegu (Balans L/P): {balance_str}. Ryzyko mikrourazu/kompensacji.")
        except ValueError:
            pass

    hrv = record.get("HRV_rMSSD")
    if hrv and prev_records:
        recent_hrvs = [r.get("HRV_rMSSD") for r in prev_records if r.get("HRV_rMSSD") is not None]
        if len(recent_hrvs) >= 3:
            avg_hrv = sum(recent_hrvs[-7:]) / len(recent_hrvs[-7:])
            if hrv < avg_hrv * 0.85:
                alerts.append(f"⚠️ Spadek HRV rMSSD: {hrv} ms (średnia 7-dniowa: {round(avg_hrv, 1)} ms). Słaba regeneracja.")

    rhr = record.get("Tetno_Spoczynkowe")
    if rhr and prev_records:
        recent_rhrs = [r.get("Tetno_Spoczynkowe") for r in prev_records if r.get("Tetno_Spoczynkowe") is not None]
        if len(recent_rhrs) >= 3:
            avg_rhr = sum(recent_rhrs[-7:]) / len(recent_rhrs[-7:])
            if rhr >= avg_rhr + 5:
                alerts.append(f"⚠️ Podwyższone Tętno Spoczynkowe: {rhr} bpm (średnia 7-dniowa: {round(avg_rhr, 1)} bpm).")

    if alerts:
        subject = f"🚨 OSTRZEŻENIE TRENERSKIE - Garmin Alert [{record.get('Data')}]"
        body = f"Cześć!\n\nWykryto niepokojące odchylenia w Twoich danych z dnia {record.get('Data')}:\n\n"
        for alert in alerts:
            body += f"- {alert}\n"
        body += "\nZalecenie: Rozważ zmniejszenie intensywności dzisiejszego akcentu lub zmianę na lekki bieg tlenowy / regenerację.\n\nTwoja Automatyzacja Garmin"

        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = receiver
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        try:
            server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
            server.close()
            print("Alert e-mail został pomyślnie wysłany!")
        except Exception as e:
            print(f"Błąd wysyłania wiadomości e-mail: {e}")

# Sprawdzamy alert dla najnowszego rekordu (dzisiejszego)
if rows:
    check_and_send_alerts(rows[-1], rows[:-1])

# --- ZAPIS / AKTUALIZACJA CSV (UPSERT DLA WCZORAJ I DZIŚ) ---
csv_file = "garmin_data.csv"
existing_csv_data = {}
fieldnames = list(rows[0].keys()) if rows else []

if os.path.isfile(csv_file):
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            fieldnames = reader.fieldnames
        for row in reader:
            if row.get("Data"):
                existing_csv_data[row["Data"]] = row

for r in rows:
    cleaned_row = {k: ("" if v is None else v) for k, v in r.items()}
    existing_csv_data[r["Data"]] = cleaned_row

sorted_dates = sorted(existing_csv_data.keys())
with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for d in sorted_dates:
        writer.writerow(existing_csv_data[d])

print(f"Zaktualizowano plik CSV dla ostatnich {len(rows)} dni.")

# --- ZAPIS / AKTUALIZACJA GOOGLE SHEETS (UPSERT DLA WCZORAJ I DZIŚ) ---
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
            existing_dates_map = {}
        else:
            if len(existing_values[0]) < len(fieldnames):
                sheet.update('A1', [list(fieldnames)])
            existing_dates_map = {row[0]: idx + 1 for idx, row in enumerate(existing_values) if row}

        for r in rows:
            date_key = r["Data"]
            row_vals = [("" if v is None else v) for v in r.values()]
            
            if date_key in existing_dates_map:
                row_idx = existing_dates_map[date_key]
                sheet.update(f"A{row_idx}", [row_vals])
                print(f"Zaktualizowano wiersz {row_idx} w Google Sheets dla daty {date_key}.")
            else:
                sheet.append_row(row_vals)
                print(f"Dodano nowy wiersz w Google Sheets dla daty {date_key}.")

    except Exception as e:
        print(f"Błąd Google Sheets: {e}")
