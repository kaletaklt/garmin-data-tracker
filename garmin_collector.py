import os
import csv
import datetime
import requests

ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")

today = datetime.date.today().isoformat()

# Zapytanie do oficjalnego API Intervals.icu o dane wellness z dzisiaj
url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness/{today}"
response = requests.get(url, auth=("API_KEY", API_KEY))

if response.status_code == 200:
    data = response.json()
    
    record = {
        "Data": today,
        "Tetno_Spoczynkowe": data.get("restingHR"),
        "HRV_SDNN": data.get("hrv"),
        "HRV_rMSSD": data.get("hrvRMSSD"),
        "Sen_Wynik": data.get("sleepScore"),
        "Sen_Godziny": round(data.get("sleepSecs", 0) / 3600, 2) if data.get("sleepSecs") else None,
        "BodyBattery": data.get("bodyBattery"),
        "Stres_Sredni": data.get("avgStress"),
        "Waga_kg": data.get("weight")
    }

    file_exists = os.path.isfile("garmin_data.csv")
    with open("garmin_data.csv", mode="a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=record.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)
    print("Dane zsynchronizowane pomyślnie z Intervals!")
else:
    print(f"Błąd pobierania danych: {response.status_code}")
