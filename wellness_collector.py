import datetime
import os
from garmin_auth import GarminAuthenticator
from gsheets_updater import GSheetsUpdater

class WellnessCollector:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def fetch_daily_stats(self, target_date):
        date_iso = target_date.isoformat()
        try:
            stats = self.client.get_stats(date_iso)
            return [date_iso, stats.get('totalSteps', 0), stats.get('restingHeartRate', 0)]
        except Exception as e:
            print(f"Błąd pobierania danych: {e}")
            return []

def main():
    garmin_client = GarminAuthenticator().login()
    collector = WellnessCollector(garmin_client)
    
    target_date = datetime.date.today() - datetime.timedelta(days=1)
    health_data = collector.fetch_daily_stats(target_date)

    if health_data:
        sheet_id = os.getenv("GOOGLE_SHEET_ID")
        if not sheet_id:
            raise ValueError("Brak GOOGLE_SHEET_ID. Skonfiguruj YML zgodnie z krokami naprawczymi.")
        
        updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Wellness")
        updater.append_data(health_data)

if __name__ == "__main__":
    main()
