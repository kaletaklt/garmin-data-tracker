import os
from garmin_auth import GarminAuthenticator
from gsheets_updater import GSheetsUpdater

class ActivityCollector:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def fetch_recent_activities(self, limit=20):
        try:
            return self.client.get_activities(0, limit)
        except Exception as e:
            print(f"Błąd pobierania aktywności: {e}")
            return []

    def extract_activity_data(self, activity):
        def round_safe(val, digits=2):
            return round(val, digits) if val is not None else ""

        return [
            str(activity.get("activityId", "")),
            activity.get("startTimeLocal", "")[:10],
            activity.get("startTimeLocal", "")[11:16],
            activity.get("activityName", "Aktywność"),
            activity.get("activityType", {}).get("typeKey", ""),
            round_safe((activity.get("movingDuration") or 0) / 60),
            round_safe((activity.get("duration") or 0) / 60),
            round_safe((activity.get("distance") or 0) / 1000),
            activity.get("averageHR", ""),
            activity.get("maxHR", ""),
            activity.get("aerobicTrainingEffect", ""),
            activity.get("anaerobicTrainingEffect", ""),
            activity.get("trainingLoad", ""),
            activity.get("calories", ""),
            round_safe(activity.get("elevationGain")),
            round_safe(activity.get("elevationLoss")),
            activity.get("averageRunningCadenceInStepsPerMinute", activity.get("averageBikingCadenceInRevPerMinute", "")),
            round_safe((activity.get("avgStrideLength") or 0) / 100) if activity.get("avgStrideLength") else "",
            activity.get("avgGroundContactTime", ""),
            activity.get("avgVerticalOscillation", ""),
            activity.get("avgLeftBalance", ""),
            activity.get("averagePower", ""),
            activity.get("normalizedPower", ""),
            activity.get("vO2MaxValue", ""),
            activity.get("averageTemperature", "")
        ]

def main():
    garmin_client = GarminAuthenticator().login()
    collector = ActivityCollector(garmin_client)
    
    activities = collector.fetch_recent_activities(limit=20)
    if not activities:
        print("Brak nowych aktywności do przetworzenia.")
        return

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("Brak GOOGLE_SHEET_ID.")

    # ZMieniona nazwa zakładki na "Aktywnosci" (bez 'ś')
    updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Aktywnosci")
    
    for activity in reversed(activities):
        activity_id = str(activity.get("activityId", ""))
        if not activity_id:
            continue
            
        row = collector.extract_activity_data(activity)
        updater.upsert_row(identifier=activity_id, col_index=1, row_data=row)

    intervals_key = os.getenv("INTERVALS_API_KEY")
    if intervals_key:
        print("Integracja Intervals.icu do ewentualnego wykorzystania.")

if __name__ == "__main__":
    main()
