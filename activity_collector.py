import os
import datetime
from garmin_auth import GarminAuthenticator
from gsheets_updater import GSheetsUpdater

class ActivityCollector:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def fetch_recent_activities(self, limit=100):
        """Zwiększono limit do 100, aby mieć pewność pobrania pełnych 30 dni wstecz."""
        try:
            return self.client.get_activities(0, limit)
        except Exception as e:
            print(f"Błąd pobierania aktywności: {e}")
            return []

    def extract_activity_data(self, activity):
        def round_safe(val, digits=2):
            return round(val, digits) if val is not None else ""

        # Typ aktywności - poprawione zagnieżdżenie, żeby nie było NaN
        type_info = activity.get("activityType", {})
        type_key = type_info.get("typeKey", type_info.get("typeId", ""))
        
        # Wykluczenie dystansu dla stacjonarnych aktywności
        non_distance_types = [
            "strength_training", "yoga", "pilates", "meditation", 
            "breathwork", "stretching", "indoor_cardio", "fitness_equipment",
            "elliptical", "stair_climbing", "indoor_cycling", "treadmill_running"
        ]
        
        if type_key in non_distance_types:
            distance_val = ""
        else:
            dist = activity.get("distance")
            distance_val = round_safe(dist / 1000) if dist else ""

        # Szukanie odpowiednich kluczy Garmina 
        # (dodane sprawdzenia dla activityTrainingLoad i avgGroundContactBalance)
        training_load = activity.get("activityTrainingLoad", activity.get("trainingLoad", ""))
        left_balance = activity.get("avgGroundContactBalance", activity.get("avgLeftBalance", activity.get("leftBalance", "")))
        avg_power = activity.get("avgPower", activity.get("averagePower", ""))
        norm_power = activity.get("normPower", activity.get("normalizedPower", ""))
        avg_temp = activity.get("avgTemperature", activity.get("averageTemperature", ""))
        vo2_max = activity.get("vO2MaxValue", activity.get("vo2MaxValue", ""))

        # Czasami Garmin zwraca balans jako liczbę zmiennoprzecinkową np. 50.5 (co oznacza 50,5% dla lewej stopy)
        if isinstance(left_balance, (float, int)):
            left_balance = round(left_balance, 2)

        return [
            str(activity.get("activityId", "")),
            activity.get("startTimeLocal", "")[:10],
            activity.get("startTimeLocal", "")[11:16],
            activity.get("activityName", "Aktywność"),
            type_key,
            round_safe((activity.get("movingDuration") or 0) / 60),
            round_safe((activity.get("duration") or 0) / 60),
            distance_val,
            activity.get("averageHR", ""),
            activity.get("maxHR", ""),
            activity.get("aerobicTrainingEffect", ""),
            activity.get("anaerobicTrainingEffect", ""),
            training_load,                                  # Zaktualizowany Load
            activity.get("calories", ""),
            round_safe(activity.get("elevationGain")),
            round_safe(activity.get("elevationLoss")),
            activity.get("averageRunningCadenceInStepsPerMinute", activity.get("averageBikingCadenceInRevPerMinute", "")),
            round_safe((activity.get("avgStrideLength") or 0) / 100) if activity.get("avgStrideLength") else "",
            activity.get("avgGroundContactTime", ""),
            activity.get("avgVerticalOscillation", ""),
            left_balance,                                   # Zaktualizowany Balans L/P
            avg_power,
            norm_power,
            vo2_max,
            avg_temp
        ]

def main():
    garmin_client = GarminAuthenticator().login()
    collector = ActivityCollector(garmin_client)
    
    # 1. Pobieramy 100 najnowszych aktywności
    activities = collector.fetch_recent_activities(limit=100)
    if not activities:
        print("Brak nowych aktywności do przetworzenia.")
        return

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("Brak GOOGLE_SHEET_ID.")

    updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Aktywnosci")
    
    # 2. Skrypt przepuści wyłącznie aktywności z ostatnich 30 dni
    cutoff_date = datetime.date.today() - datetime.timedelta(days=30)
    
    for activity in reversed(activities):
        activity_id = str(activity.get("activityId", ""))
        if not activity_id:
            continue
            
        start_date_str = activity.get("startTimeLocal", "")[:10]
        if not start_date_str:
            continue
            
        try:
            # Weryfikacja czy aktywność mieści się w limicie 30 dni
            act_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
            if act_date < cutoff_date:
                continue
        except ValueError:
            pass
            
        row = collector.extract_activity_data(activity)
        updater.upsert_row(identifier=activity_id, col_index=1, row_data=row)

    intervals_key = os.getenv("INTERVALS_API_KEY")
    if intervals_key:
        print("Integracja Intervals.icu do ewentualnego wykorzystania.")

if __name__ == "__main__":
    main()
