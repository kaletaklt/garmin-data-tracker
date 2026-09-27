import os
import csv
import datetime
from garminconnect import Garmin

# Pobranie danych logowania z sekretów GitHub
email = os.environ.get("GARMIN_EMAIL")
password = os.environ.get("GARMIN_PASSWORD")

client = Garmin(email, password)
client.login()

today = datetime.date.today().isoformat()

# Pobranie słowników danych z API Garmina
summary = client.get_user_summary(today) or {}
hrv = client.get_hrv_data(today) or {}
sleep = client.get_sleep_data(today) or {}
readiness = client.get_training_readiness(today) or {}
status = client.get_training_status(today) or {}

# Wyciągnięcie szczegółowych metryk
sleep_dto = sleep.get("dailySleepDTO", {})
sleep_scores = sleep_dto.get("sleepScores", {})

record = {
    "Data": today,
    # OGÓLNE & SERCE
    "Tetno_Spoczynkowe_BPM": summary.get("restingHeartRate"),
    "Tetno_Max_BPM": summary.get("maxHeartRate"),
    "Kroki": summary.get("totalSteps"),
    "Kalorie_Aktywne": summary.get("activeKilocalories"),
    "Pietra_Gora": summary.get("floorsAscended"),
    
    # SEN & REGENERACJA
    "Sen_Wynik": sleep_scores.get("overall", {}).get("value"),
    "Sen_Czas_Gody": round(sleep_dto.get("sleepTimeSeconds", 0) / 3600, 2) if sleep_dto.get("sleepTimeSeconds") else None,
    "Sen_Gleboki_Min": round((sleep_dto.get("deepSleepSeconds") or 0) / 60),
    "Sen_Lekki_Min": round((sleep_dto.get("lightSleepSeconds") or 0) / 60),
    "Sen_REM_Min": round((sleep_dto.get("remSleepSeconds") or 0) / 60),
    "Sen_Czuwanie_Min": round((sleep_dto.get("awakeSleepSeconds") or 0) / 60),
    "Srednie_SpO2": sleep_dto.get("averageSpO2Value"),
    "Sredni_Oddech_Noc": sleep_dto.get("averageRespirationValue"),
    
    # HRV (VARIABLE HEART RATE)
    "HRV_Status": hrv.get("hrvSummary", {}).get("status"),
    "HRV_Ostatnia_Noc": hrv.get("hrvSummary", {}).get("lastNightAvg"),
    "HRV_Srednia_7dni": hrv.get("hrvSummary", {}).get("weeklyAvg"),
    
    # STRES & BODY BATTERY
    "Stres_Sredni": summary.get("averageStressLevel"),
    "Stres_Max": summary.get("maxStressLevel"),
    "BodyBattery_Max": summary.get("bodyBatteryHighestValue"),
    "BodyBattery_Min": summary.get("bodyBatteryLowestValue"),
    "BodyBattery_Naladowanie": summary.get("bodyBatteryChargedValue"),
    "BodyBattery_Rozladowanie": summary.get("bodyBatteryDrainedValue"),
    
    # FORMA & GOTOWOŚĆ TRENINGOWA
    "Gotowosc_Treningowa_Score": readiness[0].get("score") if isinstance(readiness, list) and len(readiness) > 0 else readiness.get("score"),
    "Status_Treningowy": status.get("trainingStatusDTO", {}).get("type"),
    "VO2Max_Bieg": status.get("mostRecentVO2Max", {}).get("generic", {}).get("vo2MaxValue")
}

file_exists = os.path.isfile("garmin_data.csv")

with open("garmin_data.csv", mode="a", newline="", encoding="utf-8") as file:
    writer = csv.DictWriter(file, fieldnames=record.keys())
    if not file_exists:
        writer.writeheader()
    writer.writerow(record)

print(f"Pomyślnie zapisano kompletne dane dla dnia {today}")
