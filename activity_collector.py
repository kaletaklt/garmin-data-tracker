import os
import json
import datetime
from garminconnect import Garmin

def collect_activities():
    # Konstruktor bez session_data_dir
    client = Garmin(os.environ.get("GARMIN_EMAIL"), os.environ.get("GARMIN_PASSWORD"))
    client.login(".") # Wczytanie z bieżącego katalogu

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=7)
    
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
            "Czas_Ruchu_Min": round((act.get("movingDuration") or 0) / 60, 2) or None,
            "Dystans_Km": round((act.get("distance") or 0) / 1000, 2) or None,
            "Srednie_HR": act.get("averageHR"),
            "Max_HR": act.get("maxHR"),
            "Kalorie": act.get("calories"),
            "Przewyzszenia_m": act.get("elevationGain"),
            "Kadencja_Srednia": act.get("averageRunningCadenceInStepsPerMinute"),
            "Dlugosc_Kroku_m": round((act.get("avgStrideLength") or 0) / 100, 2) or None,
            "Balans_L_P": act.get("avgLeftBalance")
        }
        rows.append(record)

    with open("activities_data.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=4)
    print(f"Pobrano {len(rows)} aktywności.")

if __name__ == "__main__":
    collect_activities()
