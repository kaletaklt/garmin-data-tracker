import datetime
from garmin_auth import GarminAuthenticator
from gsheets_updater import GSheetsUpdater
import os

class WellnessCollector:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def fetch_daily_stats(self, target_date):
        """Pobiera dane takie jak kroki, sen i tętno spoczynkowe."""
        date_iso = target_date.isoformat()
        try:
            print(f"Pobieranie statystyk zdrowotnych dla {date_iso}...")
            stats = self.client.get_stats(date_iso)
            
            steps = stats.get('totalSteps', 0)
            rhr = stats.get('restingHeartRate', 0)
            
            return [date_iso, steps, rhr]
        except Exception as e:
            print(f"Błąd pobierania danych wellness: {e}")
            return []

def main():
    garmin_client = GarminAuthenticator().login()
    collector = WellnessCollector(garmin_client)
    
    # Dane dla wczorajszego dnia, ponieważ dzisiejszy się jeszcze nie skończył
    target_date = datetime.date.today() - datetime.timedelta(days=1)
    health_data = collector.fetch_daily_stats(target_date)

    if health_data:
        sheet_id = os.getenv("SPREADSHEET_ID", "TUTAJ_WPISZ_DEFAULTOWY_ID")
        updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Wellness")
        updater.append_data(health_data)

if __name__ == "__main__":
    main()
