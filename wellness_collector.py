import os
import json
import datetime
from garminconnect import Garmin

DAYS_TO_FETCH = 2

def collect_wellness():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    
    # Skrypt wykryje pliki sesji z poprzedniego kroku i zaloguje się automatycznie
    client = Garmin(email, password, session_data_dir=".")
    client.login()

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH - 1)
    
    rows = []
    curr_date = start_date

    while curr_date <= end_date:
        date_str = curr_date.isoformat()
        print(f"Pobieranie statystyk zdrowotnych dla: {date_str}")
        
        stats = client.get_stats(date_str) or {}
        sleep_resp = client.get_sleep_data(date_str) or {}
        hrv_resp = client.get_hrv_data(date_str) or {}

        daily_sleep = sleep_resp.get('dailySleepDTO', {})
        sleep_score = daily_sleep.get('sleepScores', {}).get('overall', {}).get('value')
        
        record = {
            "Data": date_str,
            "Tetno_Spoczynkowe": stats.get('restingHeartRate'),
            "HRV_rMSSD": hrv_resp.get('hrvSummary', {}).get('lastNightAvg'),
            "Sen_Wynik": sleep_score,
            "Sen_Godziny": round(daily_sleep.get('sleepTimeSeconds', 0) / 3600, 2) if daily_sleep.get('sleepTimeSeconds') else None,
            "Sen_Gleboki_Min": round(daily_sleep.get('deepSleepSeconds', 0) / 60) if daily_sleep.get('deepSleepSeconds') else None,
            "Sen_Lekki_Min": round(daily_sleep.get('lightSleepSeconds', 0) / 60) if daily_sleep.get('lightSleepSeconds') else None,
            "Sen_REM_Min": round(daily_sleep.get('remSleepSeconds', 0) / 60) if daily_sleep.get('remSleepSeconds') else None,
            "Sen_Czuwanie_Min": round(daily_sleep.get('awakeSleepSeconds', 0) / 60) if daily_sleep.get('awakeSleepSeconds') else None,
            "BodyBattery_Max": stats.get('maxBodyBattery'),
            "BodyBattery_Min": stats.get('minBodyBattery'),
            "Stres_Sredni": stats.get('averageStressLevel'),
            "Kroki": stats.get('totalSteps'),
            "Kalorie_Aktywne": stats.get('activeKilocalories')
        }
        rows.append(record)
        curr_date += datetime.timedelta(days=1)

    with open("wellness_data.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=4)
    print("✅ Pomyślnie zebrano dane Wellness.")

if __name__ == "__main__":
    collect_wellness()
