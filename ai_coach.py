import os
import json
import datetime
import gspread

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")

def get_worksheet(sheet_name):
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("Brak zmiennej GSPREAD_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    gc = gspread.service_account_from_dict(creds_dict)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(sheet_name)

def generate_workout_code(workout_type):
    """
    Zwraca składnię treningu zrozumiałą dla naszego parsera Garmina.
    Pace docelowe pod złamanie 1:30 w HM to ok. 4:15 min/km (tempo progowe).
    """
    if workout_type == "Tempo":
        return (
            "warmup, 2km\n"
            "interval, 5km, 4:10-4:20\n"
            "cooldown, 2km"
        )
    elif workout_type == "Intervals":
        return (
            "warmup, 3km\n"
            "interval, 1km, 3:55-4:05\n"
            "recovery, 3min\n"
            "interval, 1km, 3:55-4:05\n"
            "recovery, 3min\n"
            "interval, 1km, 3:55-4:05\n"
            "cooldown, 2km"
        )
    elif workout_type == "LongRun":
        return (
            "interval, 16km, 4:50-5:10"
        )
    else: # Base / Recovery
        return (
            "interval, 8km, 5:10-5:30"
        )

def main():
    print("Łączenie z Google Sheets...")
    wellness_sheet = get_worksheet("Wellness")
    treningi_sheet = get_worksheet("Treningi")
    
    # 1. Pobranie wczorajszych/dzisiejszych parametrów organizmu
    records = wellness_sheet.get_all_records()
    if not records:
        print("Brak danych Wellness!")
        return
        
    last_wellness = records[-1] # Bierzemy najświeższy wiersz
    
    try:
        sleep_score = int(last_wellness.get("Sen_Wynik", 0))
    except ValueError:
        sleep_score = 0
        
    hrv_status = str(last_wellness.get("HRV_Status", "")).lower()
    
    # 2. Logika Trenera (Reguły decyzyjne)
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    target_date = tomorrow.isoformat()
    day_of_week = tomorrow.weekday() # 0 = Pon, 6 = Niedz
    
    print(f"Dane z wczoraj: Sen = {sleep_score}, HRV = {hrv_status}")
    print(f"Generowanie planu na jutro ({target_date})...")

    # Sprawdzamy, czy jutro nie ma już zapisanego treningu w arkuszu
    planned_records = treningi_sheet.get_all_records()
    for row in planned_records:
        if str(row.get("Data", "")) == target_date:
            print("Trening na jutro jest już zaplanowany w Arkuszu. Pomijam.")
            return

    # Jeśli jest niedziela -> Długie wybieganie, chyba że jesteśmy zniszczeni
    if day_of_week == 6:
        if sleep_score < 60 or "unbalanced" in hrv_status or "poor" in hrv_status:
            workout_name = "Recovery Long Run (Zmęczenie)"
            workout_type = "Base"
        else:
            workout_name = "Niedzielne Wybieganie (Sub 1:30 HM)"
            workout_type = "LongRun"
            
    # Dni w tygodniu: Decyduje gotowość organizmu
    else:
        if sleep_score >= 75 and ("balanced" in hrv_status or "zrównoważony" in hrv_status):
            # Organizm wypoczęty -> Mocny Akcent
            # Możemy tu na przemian robić interwały i tempo
            workout_name = "Mocny Akcent (Tempo HM)"
            workout_type = "Tempo"
        else:
            # Słabsza regeneracja -> Luźna baza (nabijanie objętości tlenowej)
            workout_name = "Spokojna Baza Tlenowa"
            workout_type = "Base"

    kod_treningu = generate_workout_code(workout_type)

    # 3. Zapisanie wygenerowanego treningu do zakładki "Treningi"
    new_row = [
        target_date,
        workout_name,
        kod_treningu,
        "Zaplanowane"
    ]
    
    treningi_sheet.append_row(new_row)
    print(f"SUKCES: Zapisano nowy trening w arkuszu -> {workout_name}")

if __name__ == "__main__":
    main()
