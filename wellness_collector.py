import os
import json
import datetime
from garminconnect import Garmin

def collect_wellness():
    client = Garmin(os.environ.get("GARMIN_EMAIL"), os.environ.get("GARMIN_PASSWORD"))
    client.login(".")

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
            "Tetno_Maksymalne": stats.get('maxHeartRate'),
            "HRV_rMSSD": hrv.get('hrvSummary', {}).get('lastNightAvg'),
            "HRV_Status": hrv.get('hrvSummary', {}).get('status'),
            "Sen_Wynik": ds.get('sleepScores', {}).get('overall', {}).get('value') or sleep.get('sleepScores', {}).get('overall', {}).get('value'),
            "Sen_Godziny": round((ds.get('sleepTimeSeconds') or 0) / 3600, 2) or None,
            "Sen_Gleboki_Min": round((ds.get('deepSleepSeconds') or 0) / 60) or None,
            "Sen_Lekki_Min": round((ds.get('lightSleepSeconds') or 0) / 60) or None,
            "Sen_REM_Min": round((ds.get('remSleepSeconds') or 0) / 60) or None,
            "Sen_Czuwanie_Min": round((ds.get('awakeSleepSeconds') or 0) / 60) or None,
            "SpO2_Srednie": stats.get('averageSpO2'),
            "SpO2_Min": stats.get('lowestSpO2'),
            "Oddech_Noc_Sredni": stats.get('sleepingRespiration') or stats.get('averageRespirationValue') or stats.get('averageRespiration'),
            "BodyBattery_Max": stats.get('bodyBatteryHighestValue') or stats.get('highestBodyBatteryValue') or stats.get('maxBodyBattery'),
            "BodyBattery_Min": stats.get('bodyBatteryLowestValue') or stats.get('lowestBodyBatteryValue') or stats.get('minBodyBattery'),
            "Stres_Sredni": stats.get('averageStressLevel'),
            "Stres_Czas_Odpoczynku_Min": round((stats.get('restStressDuration') or 0) / 60) or None,
            "Stres_Czas_Wysokiego_Min": round((stats.get('highStressDuration') or 0) / 60) or None,
            "Kroki": stats.get('totalSteps', 0),
            "Piętra_W_Gore": stats.get('floorsAscended', 0),
            "Kalorie_Aktywne": stats.get('activeKilocalories', 0),
            "Kalorie_Spoczynkowe": stats.get('bmrKilocalories', 0),
            "Minuty_Intensywne": stats.get('vigorousIntensityMinutes', 0)
        }
        rows.append(record)
        curr_date += datetime.timedelta(days=1)

    with open("wellness_data.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=4)
    print("Pobrano rozszerzone dane Wellness.")

if __name__ == "__main__":
    collect_wellness()
