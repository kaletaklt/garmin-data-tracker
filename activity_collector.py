import os
import json
import datetime
from garminconnect import Garmin

DAYS_TO_FETCH = 7

def collect_activities():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    
    client = Garmin(email, password, session_data_dir=".")
    client.login()

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH)
    
    print(f"Pobieranie aktywności od {start_date} do {end_date}...")
    activities = client.get_activities_by_date(start_date.isoformat(), end_date.isoformat(), "")
    
    rows = []
    for act in activities:
        act_id = act.get("activityId")
        if not act_id: continue
        
        record = {
            "ID_Aktywnosci": str(act_id),
            "Data": act.get("startTimeLocal", "")[:10],
            "Godzina": act.get("startTimeLocal", "")[11:16],
            "Nazwa": act.get("activityName"),
            "Typ": act.get("activityType", {}).get("typeKey"),
            "Czas_Ruchu_Min": round(act.get("movingDuration", 0) / 60, 2) if act.get("movingDuration") else None,
            "Dystans_Km": round(act.get("distance", 0) / 1000, 2) if act.get("distance") else None,
            "Srednie_HR": act.get("averageHR"),
            "Max_HR": act.get("maxHR"),
            "Kalorie": act.get("calories"),
            "Przewyzszenia_W_Gore_m": act.get("elevationGain"),
            "Kadencja_Srednia": act.get("averageRunningCadenceInStepsPerMinute"),
            "Dlugosc_Kroku_m": round(act.get("avgStrideLength", 0) / 100, 2) if act.get("avgStrideLength") else None,
            "Balans_L_P": act.get("avgLeftBalance")
        }
        rows.append(record)

    with open("activities_data.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=4)
    print(f"✅ Zebrano {len(rows)} aktywności z ostatnich dni.")

if __name__ == "__main__":
    collect_activities()
