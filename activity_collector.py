import os
from garmin_auth import GarminAuthenticator
from gsheets_updater import GSheetsUpdater

class ActivityCollector:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def fetch_recent_activities(self, limit=1):
        try:
            return self.client.get_activities(0, limit)
        except Exception as e:
            print(f"Błąd pobierania aktywności: {e}")
            return []

def main():
    garmin_client = GarminAuthenticator().login()
    collector = ActivityCollector(garmin_client)
    activities = collector.fetch_recent_activities(limit=1)

    if not activities:
        print("Brak nowych aktywności.")
        return

    latest = activities[0]
    row_to_insert = [
        latest.get("startTimeLocal", "")[:10],
        latest.get("activityName", "Aktywność"),
        round(latest.get("distance", 0) / 1000, 2),
        round(latest.get("duration", 0) / 60, 2)
    ]

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if sheet_id:
        updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Aktywności")
        updater.append_data(row_to_insert)

    # Przywrócenie odwołania do Intervals API
    intervals_key = os.getenv("INTERVALS_API_KEY")
    if intervals_key:
        print("Miejsce na oryginalny kod API przesyłający pliki .fit do serwerów Intervals")

if __name__ == "__main__":
    main()
