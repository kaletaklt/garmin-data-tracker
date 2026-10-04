import os
import json
import datetime
from garminconnect import Garmin

def collect_wellness():
    # Konstruktor bez session_data_dir
    client = Garmin(os.environ.get("GARMIN_EMAIL"), os.environ.get("GARMIN_PASSWORD"))
    client.login(".") # Wczytanie z bieżącego katalogu

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=1)
    rows = []
    
    curr_date = start_date
    while curr_date <= end_date:
        date_str = curr_date.isoformat()
        stats = client.get_stats(date_str) or {}
        sleep = client.get_sleep_data(date_str) or {}
        hrv = client.get_hrv_data(date_str) or {}

        ds = sleep.get('dailySleepDTO', {})
        
        record = {
            "Data": date_str,
            "Tetno_Spoczynkowe": stats.get('restingHeartRate'),
            "HRV_rMSSD": hrv.get('hrvSummary', {}).get('lastNightAvg'),
            "Sen_Wynik": ds.get('sleepScores', {}).get('overall', {}).get('value'),
            "Sen_Godziny": round((ds.get('sleepTimeSeconds') or 0) / 3600, 2) or None,
            "Sen_Gleboki_Min": round((ds.get('deepSleepSeconds') or 0) / 60) or None,
            "Sen_Lekki_Min": round((ds.get('lightSleepSeconds') or 0) / 60) or None,
            "Sen_REM_Min": round((ds.get('remSleepSeconds') or 0) / 60) or None,
            "BodyBattery_Max": stats.get('maxBodyBattery'),
            "BodyBattery_Min": stats.get('minBodyBattery'),
            "Stres_Sredni": stats.get('averageStressLevel'),
            "Kroki": stats.get('totalSteps', 0),
            "Kalorie_Aktywne": stats.get('activeKilocalories', 0)
        }
        rows.append(record)
        curr_date += datetime.timedelta(days=1)

    with open("wellness_data.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=4)
    print("Pobrano dane Wellness.")

if __name__ == "__main__":
    collect_wellness()
