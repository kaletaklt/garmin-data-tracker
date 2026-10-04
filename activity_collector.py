import os
import json
import datetime
from garminconnect import Garmin

def collect_activities():
    client = Garmin(os.environ.get("GARMIN_EMAIL"), os.environ.get("GARMIN_PASSWORD"))
    client.login(".")

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=7)
    
    activities = client.get_activities_by_date(start_date.isoformat(), end_date.isoformat(), "")
    rows = []
    
    for act in activities:
        act_id = act.get("activityId")
        if not act_id: continue
        
        # Garmin inaczej nazywa balans dla biegu (GroundContactBalance) i roweru (LeftBalance)
        balance = act.get("avgLeftGroundContactBalance") or act.get("avgLeftBalance")
        if balance:
            balance = round(balance, 1)
        
record = {
            "ID_Aktywnosci": str(act_id),
            "Data": act.get("startTimeLocal", "")[:10],
            "Godzina": act.get("startTimeLocal", "")[11:16],
            "Nazwa": act.get("activityName"),
            "Typ": act.get("activityType", {}).get("typeKey"),
            "Czas_Ruchu_Min": round((act.get("movingDuration") or 0) / 60, 2) or None,
            "Czas_Calkowity_Min": round((act.get("elapsedDuration") or 0) / 60, 2) or None,
            "Dystans_Km": round((act.get("distance") or 0) / 1000, 2) or None,
            "Srednie_HR": act.get("averageHR"),
            "Max_HR": act.get("maxHR"),
            "Efekt_Tlenowy": act.get("aerobicTrainingEffect"),
            "Efekt_Beztlenowy": act.get("anaerobicTrainingEffect"),
            "Obciazenie_Treningowe_Load": act.get("activityTrainingLoad") or act.get("trainingLoad"),
            "Kalorie": act.get("calories"),
            "Przewyzszenia_W_Gore_m": act.get("elevationGain"),
            "Przewyzszenia_W_Dol_m": act.get("elevationLoss"),
            "Kadencja_Srednia": act.get("averageRunningCadenceInStepsPerMinute") or act.get("averageBikingCadenceInRevPerMinute"),
            "Dlugosc_Kroku_m": round((act.get("avgStrideLength") or 0) / 100, 2) if act.get("avgStrideLength") else None,
            "Czas_Kontaktu_z_Podlozem_ms": act.get("avgGroundContactTime"),
            "Odchylenie_Pionowe_mm": round((act.get("avgVerticalOscillation") or 0) * 10, 1) if act.get("avgVerticalOscillation") else None,
            "Balans_L_P": act.get("balance"),
            "Srednia_Moc_W": act.get("avgPower") or act.get("averagePower"),
            "Znormalizowana_Moc_W": act.get("normPower") or act.get("normalizedPower"),
            "VO2_Max_Treningu": act.get("vO2MaxValue"),
            "Temperatura_Srednia_C": act.get("averageTemperature") or act.get("minTemperature")
        }
        rows.append(record)

    with open("activities_data.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=4)
    print(f"Pobrano {len(rows)} rozszerzonych aktywności.")

if __name__ == "__main__":
    collect_activities()
