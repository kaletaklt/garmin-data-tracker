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

            # --- BEZPIECZNE POBIERANIE WYNIKU SNU ---
            sleep_score = ""
            if "sleepScores" in dto and "overall" in dto["sleepScores"]:
                sleep_score = dto["sleepScores"]["overall"].get("value", "")
            elif "sleepScores" in sleep and "overall" in sleep["sleepScores"]:
                sleep_score = sleep["sleepScores"]["overall"].get("value", "")
            elif "sleepScore" in dto:
                score_data = dto["sleepScore"]
                sleep_score = score_data.get("value", "") if isinstance(score_data, dict) else score_data

            # --- BEZPIECZNE POBIERANIE KALORII SPOCZYNKOWYCH ---
            active_kcal = stats.get("activeKilocalories") or 0
            total_kcal = stats.get("totalKilocalories") or 0
            # Garmin zazwyczaj używa 'bmrKilocalories'
            resting_kcal = stats.get("bmrKilocalories")
            
            # Jeśli API nie zwróci BMR, liczymy ręcznie: Całkowite - Aktywne
            if not resting_kcal and total_kcal > 0:
                resting_kcal = total_kcal - active_kcal
                
            # --- MINUTY INTENSYWNE ---
            mod = stats.get("moderateIntensityMinutes", 0) or 0
            vig = stats.get("vigorousIntensityMinutes", 0) or 0
            intensity_mins = mod + (vig * 2)

            return [
                date_iso,                                   # 1. Data
                stats.get("restingHeartRate", ""),          # 2. Tetno_Spoczynkowe
                stats.get("maxHeartRate", ""),              # 3. Tetno_Maksymalne
                hrv_sum.get("lastNightAvg", ""),            # 4. HRV_rMSSD
                hrv_sum.get("status", ""),                  # 5. HRV_Status
                sleep_score,                                # 6. Sen_Wynik
                to_hours(dto.get("sleepTimeSeconds", 0)),   # 7. Sen_Godziny
                to_mins(dto.get("deepSleepSeconds", 0)),    # 8. Sen_Gleboki_Min
                to_mins(dto.get("lightSleepSeconds", 0)),   # 9. Sen_Lekki_Min
                to_mins(dto.get("remSleepSeconds", 0)),     # 10. Sen_REM_Min
                to_mins(dto.get("awakeSleepSeconds", 0)),   # 11. Sen_Czuwanie_Min
                dto.get("averageSpO2Value", ""),            # 12. SpO2_Srednie
                dto.get("lowestSpO2Value", ""),             # 13. SpO2_Min
                dto.get("averageRespirationValue", ""),     # 14. Oddech_Noc_Sredni
                stats.get("bodyBatteryHighestValue", ""),   # 15. BodyBattery_Max
                stats.get("bodyBatteryLowestValue", ""),    # 16. BodyBattery_Min
                stats.get("averageStressLevel", ""),        # 17. Stres_Sredni
                to_mins(stats.get("restStressDuration", 0)),# 18. Stres_Czas_Odpoczynku_Min
                to_mins(stats.get("highStressDuration", 0)),# 19. Stres_Czas_Wysokiego_Min
                stats.get("totalSteps", ""),                # 20. Kroki
                stats.get("floorsAscended", ""),            # 21. Piętra_W_Gore
                active_kcal if active_kcal > 0 else "",     # 22. Kalorie_Aktywne
                resting_kcal if resting_kcal else "",       # 23. Kalorie_Spoczynkowe
                intensity_mins if intensity_mins > 0 else ""# 24. Minuty_Intensywne
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
