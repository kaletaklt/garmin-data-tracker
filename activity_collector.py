import datetime
from garmin_auth import GarminAuthenticator
from gsheets_updater import GSheetsUpdater

class ActivityCollector:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def fetch_recent_activities(self, limit=1):
        """Pobiera określoną liczbę ostatnich aktywności."""
        try:
            print(f"Pobieranie ostatnich {limit} aktywności z Garmin...")
            activities = self.client.get_activities(0, limit)
            return activities
        except Exception as e:
            print(f"Błąd pobierania aktywności: {e}")
            return []

def main():
    # 1. Pobranie klienta Garmin
    garmin_client = GarminAuthenticator().login()
    
    # 2. Pobranie aktywności
    collector = ActivityCollector(garmin_client)
    activities = collector.fetch_recent_activities(limit=1)

    if not activities:
        print("Brak nowych aktywności.")
        return

    # 3. Przygotowanie danych (parsowanie)
    latest = activities[0]
    date = latest.get("startTimeLocal", "")[:10]
    name = latest.get("activityName", "Aktywność")
    distance_km = round(latest.get("distance", 0) / 1000, 2)
    duration_min = round(latest.get("duration", 0) / 60, 2)
    
    row_to_insert = [date, name, distance_km, duration_min]
    print(f"Wyciągnięte dane: {row_to_insert}")

    # 4. Zapis do GSheets (Wymaga zmiennej ze Spreadsheet ID)
    sheet_id = os.getenv("SPREADSHEET_ID", "TUTAJ_WPISZ_DEFAULTOWY_ID")
    updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Aktywności")
    updater.append_data(row_to_insert)

if __name__ == "__main__":
    main()
