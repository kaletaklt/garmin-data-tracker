import os
import csv
import datetime
import requests

ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")

# Domyślnie pobiera 1 dzień (dzisiaj). 
# Zmienna DAYS_TO_FETCH pozwala pobrać historię wstecz (np. 365 dni).
DAYS_TO_FETCH = int(os.environ.get("DAYS_TO_FETCH", 1))

end_date = datetime.date.today()
start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH - 1)

# 1. Pobranie wszystkich aktywności z podanego zakresu dat naraz
activities_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/events?oldest={start_date.isoformat()}&newest={end_date.isoformat()}"
act_res = requests.get(activities_url, auth=("API_KEY", API_KEY))

activities_by_date = {}
if act_res.status_code == 200:
    for act in act_res.json():
        if act.get("type") != "Note":  # pomijamy zwykłe notatki w kalendarzu
            act_date = act.get("start_date_local", "")[:10]
            if act_date not in activities_by_date:
                activities_by_date[act_date] = []
            activities_by_date[act_date].append(act)

rows = []
curr_date = start_date

# 2. Pętla po poszczególnych dniach z zakresu
while curr_date <= end_date:
    date_str = curr_date.isoformat()
    
    # Pobranie danych Wellness z danego dnia
    well_url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness/{date_str}"
    well_res = requests.get(well_url, auth=("API_KEY", API_KEY))
    well_data = well_res.json() if well_res.status_code == 200 else {}
    
    # Aktywności z tego dnia
    day_acts = activities_by_date.get(date_str, [])
    
    act_names = ", ".join([a.get("name", "") for a in day_acts]) if day_acts else None
    act_types = ", ".join([a.get("type", "") for a in day_acts]) if day_acts else None
    total_moving_time = sum([a.get("moving_time", 0) for a in day_acts]) if day_acts else 0
    total_distance_km = round(sum([a.get("distance", 0) for a in day_acts]) / 1000, 2) if day_acts else 0
    total_load = sum([a.get("icu_training_load", 0) or 0 for a in day_acts]) if day_acts else 0
    
    hrs = [a.get("average_heartrate") for a in day_acts if a.get("average_heartrate")]
    avg_hr = round(sum(hrs) / len(hrs)) if hrs else None
    total_calories = sum([a.get("calories", 0) or 0 for a in day_acts]) if day_acts else 0

    ctl = well_data.get("ctl")
    atl = well_data.get("atl")
    tsb = round(ctl - atl, 2) if ctl is not None and atl is not None else None

    record = {
        "Data": date_str,
        
        # REGENERACJA & OGÓLNE (WELLNESS)
        "Tetno_Spoczynkowe": well_data.get("restingHR"),
        "HRV_SDNN": well_data.get("hrv"),
        "HRV_rMSSD": well_data.get("hrvRMSSD"),
        "Sen_Wynik": well_data.get("sleepScore"),
        "Sen_Godziny": round(well_data.get("sleepSecs", 0) / 3600, 2) if well_data.get("sleepSecs") else None,
        "Sen_Gleboki_Min": round((well_data.get("deepSleepSecs") or 0) / 60) if well_data.get("deepSleepSecs") else None,
        "Sen_REM_Min": round((well_data.get("remSleepSecs") or 0) / 60) if well_data.get("remSleepSecs") else None,
        "BodyBattery": well_data.get("bodyBattery"),
        "Stres_Sredni": well_data.get("avgStress"),
        "Waga_kg": well_data.get("weight"),
        "SpO2_Srednie": well_data.get("spO2"),
        "Kroki": well_data.get("steps"),
        
        # FORMA Z INTERVALS (FORM / FITNESS)
        "Forma_Fitness_CTL": ctl,
        "Zmeczenie_Fatigue_ATL": atl,
        "Swiezosc_Form_TSB": tsb,
        
        # TRENINGI & AKTYWNOŚCI
        "Trening_Liczba": len(day_acts),
        "Trening_Typy": act_types,
        "Trening_Nazwy": act_names,
        "Trening_Czas_Calkowity_Min": round(total_moving_time / 60, 1) if total_moving_time else 0,
        "Trening_Dystans_Km": total_distance_km,
        "Trening_Obciazenie_Load": total_load,
        "Trening_Srednie_HR": avg_hr,
        "Trening_Kalorie": total_calories
    }
    rows.append(record)
    curr_date += datetime.timedelta(days=1)

# Zapis do pliku CSV
file_exists = os.path.isfile("garmin_data.csv")
fieldnames = rows[0].keys() if rows else []

# Jeśli pobieramy 1 dzień, dopisujemy do istniejącego pliku. Jeśli pobieramy historię (>1 dnia), tworzymy/nadpisujemy kompletny plik.
mode = "w" if (DAYS_TO_FETCH > 1 or not file_exists) else "a"

with open("garmin_data.csv", mode=mode, newline="", encoding="utf-8") as file:
    writer = csv.DictWriter(file, fieldnames=fieldnames)
    if mode == "w":
        writer.writeheader()
    writer.writerows(rows)

print(f"Pomyślnie pobrano i zapisano dane dla {len(rows)} dni.")
