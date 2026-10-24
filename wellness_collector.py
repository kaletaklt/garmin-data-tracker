import datetime
import os
from garmin_auth import GarminAuthenticator
from gsheets_updater import GSheetsUpdater

class WellnessCollector:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def get_safe(self, d, keys, default=""):
        for key in keys:
            if isinstance(d, dict) and key in d:
                d = d[key]
            else:
                return default
        return d if d is not None else default

    def fetch_daily_stats(self, target_date):
        date_iso = target_date.isoformat()
        try:
            print(f"Pobieranie i mapowanie statystyk wellness dla {date_iso}...")
            stats = self.client.get_stats(date_iso) or {}
            
            try:
                sleep = self.client.get_sleep_data(date_iso) or {}
            except Exception:
                sleep = {}
                
            try:
                hrv = self.client.get_hrv_data(date_iso) or {}
            except Exception:
                hrv = {}

            dto = sleep.get("dailySleepDTO", sleep)
            hrv_sum = hrv.get("hrvSummary", hrv)

            def to_hours(seconds):
                return round((seconds or 0) / 3600, 2) if seconds else ""
            def to_mins(seconds):
                return round((seconds or 0) / 60, 2) if seconds else ""

            # Obsługa wyniku snu
            score_data = dto.get("sleepScore")
            if isinstance(score_data, dict):
                sleep_score = score_data.get("value", "")
            else:
                sleep_score = score_data if score_data is not None else ""

            # Minuty intensywne (Garmin: umiarkowane + 2x intensywne)
            mod = stats.get("moderateIntensityMinutes", 0) or 0
            vig = stats.get("vigorousIntensityMinutes", 0) or 0
            intensity_mins = mod + (vig * 2)

            return [
                date_iso,
                stats.get("restingHeartRate", ""),
                stats.get("maxHeartRate", ""),
                hrv_sum.get("lastNightAvg", ""),
                hrv_sum.get("status", ""),
                sleep_score,  # Poprawione
                to_hours(dto.get("sleepTimeSeconds", 0)),
                to_mins(dto.get("deepSleepSeconds", 0)),
                to_mins(dto.get("lightSleepSeconds", 0)),
                to_mins(dto.get("remSleepSeconds", 0)),
                to_mins(dto.get("awakeSleepSeconds", 0)),
                dto.get("averageSpO2Value", ""),
                dto.get("lowestSpO2Value", ""),
                dto.get("averageRespirationValue", ""),
                stats.get("bodyBatteryHighestValue", ""),
                stats.get("bodyBatteryLowestValue", ""),
                stats.get("averageStressLevel", ""),
                to_mins(stats.get("restStressDuration", 0)),
                to_mins(stats.get("highStressDuration", 0)),
                stats.get("totalSteps", ""),
                stats.get("floorsAscended", ""),
                stats.get("activeKilocalories", ""),
                stats.get("bmr", stats.get("restingKilocalories", "")),  # Poprawiona literówka BMR
                intensity_mins if intensity_mins > 0 else ""  # Pełna liczba całkowita
            ]
        except Exception as e:
            print(f"Błąd pobierania danych dla {date_iso}: {e}")
            return None

def main():
    garmin_client = GarminAuthenticator().login()
    collector = WellnessCollector(garmin_client)
    
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("Brak GOOGLE_SHEET_ID.")
        
    updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Wellness")
    
    # Przechodzimy przez ostatnie 7 dni ORAZ dzień dzisiejszy (od 7 do 0)
    for i in range(7, -1, -1):
        target_date = datetime.date.today() - datetime.timedelta(days=i)
        row = collector.fetch_daily_stats(target_date)
        
        if row:
            # Upsert - zaktualizuje istniejacy lub doda nowy
            updater.upsert_row(identifier=row[0], col_index=1, row_data=row)

if __name__ == "__main__":
    main()
