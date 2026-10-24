import os
import datetime
from garmin_auth import GarminAuthenticator
from gsheets_updater import GSheetsUpdater

# Zdefiniowanie typów aktywności stacjonarnych jako stałej, aby nie obciążać pętli
NON_DISTANCE_TYPES = {
    "strength_training", "yoga", "pilates", "meditation", 
    "breathwork", "stretching", "indoor_cardio", "fitness_equipment",
    "elliptical", "stair_climbing", "indoor_cycling", "treadmill_running"
}

class ActivityCollector:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def fetch_recent_activities(self, limit: int = 100) -> list:
        """Pobiera określoną liczbę najnowszych aktywności z Garmin Connect."""
        try:
            print(f"Pobieranie bazy {limit} ostatnich aktywności z Garmina...")
            return self.client.get_activities(0, limit)
        except Exception as e:
            print(f"Błąd pobierania aktywności: {e}")
            return []

    @staticmethod
    def _round_safe(val, digits=2):
        """Bezpiecznie zaokrągla wartości liczbowe, omijając puste pola i None."""
        return round(val, digits) if isinstance(val, (int, float)) else ""

    def extract_activity_data(self, activity: dict) -> list:
        """Mapuje surowy JSON aktywności na wiersz w formacie Google Sheets."""
        
        type_info = activity.get("activityType", {})
        type_key = type_info.get("typeKey", type_info.get("typeId", ""))
        
        # Wykluczenie dystansu dla stacjonarnych aktywności
        distance_val = ""
        if type_key not in NON_DISTANCE_TYPES:
            dist = activity.get("distance")
            if dist:
                distance_val = self._round_safe(dist / 1000)

        # Pobieranie specyficznych metryk, zabezpieczone na wypadek różnego nazewnictwa kluczy
        training_load = activity.get("activityTrainingLoad", activity.get("trainingLoad", ""))
        left_balance = activity.get("avgGroundContactBalance", activity.get("avgLeftBalance", activity.get("leftBalance", "")))
        avg_power = activity.get("avgPower", activity.get("averagePower", ""))
        norm_power = activity.get("normPower", activity.get("normalizedPower", ""))
        avg_temp = activity.get("avgTemperature", activity.get("averageTemperature", ""))
        vo2_max = activity.get("vO2MaxValue", activity.get("vo2MaxValue", ""))

        # Formatowanie balansu z ułamka np. 50.5 na 50,5
        if isinstance(left_balance, (float, int)):
            left_balance = round(left_balance, 2)

        return [
            str(activity.get("activityId", "")),
            activity.get("startTimeLocal", "")[:10],
            activity.get("startTimeLocal", "")[11:16],
            activity.get("activityName", "Aktywność"),
            type_key,
            self._round_safe((activity.get("movingDuration") or 0) / 60),
            self._round_safe((activity.get("duration") or 0) / 60),
            distance_val,
            activity.get("averageHR", ""),
            activity.get("maxHR", ""),
            activity.get("aerobicTrainingEffect", ""),
            activity.get("anaerobicTrainingEffect", ""),
            training_load,
            activity.get("calories", ""),
            self._round_safe(activity.get("elevationGain")),
            self._round_safe(activity.get("elevationLoss")),
            activity.get("averageRunningCadenceInStepsPerMinute", activity.get("averageBikingCadenceInRevPerMinute", "")),
            self._round_safe((activity.get("avgStrideLength") or 0) / 100) if activity.get("avgStrideLength") else "",
            activity.get("avgGroundContactTime", ""),
            activity.get("avgVerticalOscillation", ""),
            left_balance,
            avg_power,
            norm_power,
            vo2_max,
            avg_temp
        ]

def main():
    # 1. Autoryzacja i inicjalizacja usług
    garmin_client = GarminAuthenticator().login()
    collector = ActivityCollector(garmin_client)
    
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("Brak klucza GOOGLE_SHEET_ID w zmiennych środowiskowych.")
        
    updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Aktywnosci")

    # 2. Pobranie ostatnich aktywności
    activities = collector.fetch_recent_activities(limit=100)
    if not activities:
        print("Brak aktywności do przetworzenia.")
        return
    
    # 3. Ustalenie okresu synchronizacji (30 dni)
    cutoff_date = datetime.date.today() - datetime.timedelta(days=30)
    print(f"Analiza treningów po dacie: {cutoff_date}...")
    
    # 4. Przetwarzanie i wysyłanie danych w kolejności chronologicznej (od najstarszej)
    for activity in reversed(activities):
        activity_id = str(activity.get("activityId", ""))
        start_date_str = activity.get("startTimeLocal", "")[:10]
        
        if not activity_id or not start_date_str:
            continue
            
        try:
            act_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
            if act_date < cutoff_date:
                continue
        except ValueError:
            print(f"Pominięto błędny format daty dla aktywności {activity_id}.")
            continue
            
        row = collector.extract_activity_data(activity)
        updater.upsert_row(identifier=activity_id, col_index=1, row_data=row)

    print("Zakończono pomyślnie synchronizację z Google Sheets.")

if __name__ == "__main__":
    main()
