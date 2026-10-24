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
            str(activity.get("activityId", "")),  # 1. ID_Aktywnosci
            activity.get("startTimeLocal", "")[:10],  # 2. Data
            activity.get("startTimeLocal", "")[11:16],  # 3. Godzina
            activity.get("activityName", "Aktywność"),  # 4. Nazwa
            activity.get("activityType", {}).get("typeKey", ""),  # 5. Typ
            round_safe((activity.get("movingDuration") or 0) / 60),  # 6. Czas_Ruchu_Min
            round_safe((activity.get("duration") or 0) / 60),  # 7. Czas_Calkowity_Min
            round_safe((activity.get("distance") or 0) / 1000),  # 8. Dystans_Km
            activity.get("averageHR", ""),  # 9. Srednie_HR
            activity.get("maxHR", ""),  # 10. Max_HR
            activity.get("aerobicTrainingEffect", ""),  # 11. Efekt_Tlenowy
            activity.get("anaerobicTrainingEffect", ""),  # 12. Efekt_Beztlenowy
            activity.get("trainingLoad", ""),  # 13. Obciazenie_Treningowe_Load
            activity.get("calories", ""),  # 14. Kalorie
            round_safe(activity.get("elevationGain")),  # 15. Przewyzszenia_W_Gore_m
            round_safe(activity.get("elevationLoss")),  # 16. Przewyzszenia_W_Dol_m
            activity.get("averageRunningCadenceInStepsPerMinute", activity.get("averageBikingCadenceInRevPerMinute", "")),  # 17. Kadencja_Srednia
            round_safe((activity.get("avgStrideLength") or 0) / 100) if activity.get("avgStrideLength") else "",  # 18. Dlugosc_Kroku_m
            activity.get("avgGroundContactTime", ""),  # 19. Czas_Kontaktu_z_Podlozem_ms
            activity.get("avgVerticalOscillation", ""),  # 20. Odchylenie_Pionowe_mm
            activity.get("avgLeftBalance", ""),  # 21. Balans_L_P
            activity.get("averagePower", ""),  # 22. Srednia_Moc_W
            activity.get("normalizedPower", ""),  # 23. Znormalizowana_Moc_W
            activity.get("vO2MaxValue", ""),  # 24. VO2_Max_Treningu
            activity.get("averageTemperature", "")  # 25. Temperatura_Srednia_C
        ]

def main():
    garmin_client = GarminAuthenticator().login()
    collector = ActivityCollector(garmin_client)
    
    # Pobieramy 20 ostatnich aktywności
    activities = collector.fetch_recent_activities(limit=20)
    if not activities:
        print("Brak nowych aktywności do przetworzenia.")
        return

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("Brak GOOGLE_SHEET_ID.")

    updater = GSheetsUpdater(spreadsheet_id=sheet_id, sheet_name="Aktywności")
    
    # Pobieramy ID_Aktywnosci (kolumna 1), aby uniknąć duplikatów
    existing_ids = updater.get_existing_identifiers(col_index=1)
    
    new_rows = []
    # Przetwarzamy od najstarszej do najnowszej (aby wpisywało się w arkusz chronologicznie)
    for activity in reversed(activities):
        activity_id = str(activity.get("activityId", ""))
        
        # Omijamy aktywności, które już istnieją w arkuszu
        if not activity_id or activity_id in existing_ids:
            continue
            
        row = collector.extract_activity_data(activity)
        new_rows.append(row)

    # Zapisujemy tylko te aktywności, których brakowało
    updater.append_rows(new_rows)

    # Pozostałość po API Interval
    intervals_key = os.getenv("INTERVALS_API_KEY")
    if intervals_key:
        print("Integracja Intervals.icu do ewentualnego wykorzystania.")

if __name__ == "__main__":
    main()
