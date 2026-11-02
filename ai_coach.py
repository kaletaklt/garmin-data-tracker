import os
import json
import datetime
import requests
import gspread

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GEMINI_API_KEY = os.getenv("GEMINI_LLM_API_KEY")
USER_NOTES = os.getenv("USER_NOTES", "Brak dodatkowych uwag, samopoczucie w normie.")

def get_spreadsheet():
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("Brak zmiennej GSPREAD_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    gc = gspread.service_account_from_dict(creds_dict)
    return gc.open_by_key(SPREADSHEET_ID)

def ask_gemini_coach(wellness_history, recent_activities, user_notes, target_date, day_name):
    if not GEMINI_API_KEY:
        raise ValueError("Brak klucza GEMINI_LLM_API_KEY w zmiennych środowiskowych!")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    prompt = f"""
Jesteś zaawansowanym trenerem biegania i przygotowania motorycznego.
Twój zawodnik to sportowiec hybrydowy (bieganie + siłownia 2x w tygodniu).
Główny cel: Złamanie 1:30:00 w półmaratonie (tempo docelowe ok. 4:15 min/km).

Zaplanuj trening biegowy na jutro: {target_date} ({day_name}).

1. SUBIEKTYWNE SAMOPOCZUCIE I UWAGI ZAWODNIKA Z DZIŚ:
"{user_notes}"

2. OSTATNIE 7 DNI WELLNESS (Sen, HRV, Body Battery, Stres, Tętno spoczynkowe):
{json.dumps(wellness_history, ensure_ascii=False, indent=2)}

3. OSTATNIE AKTYWNOŚCI (Obciążenie, Dystans, Typ, Tętno):
{json.dumps(recent_activities, ensure_ascii=False, indent=2)}

ZASADY TWORZENIA KODU TRENINGU (KRYTYCZNE DLA PARSERA GARMINA):
Każdy krok treningu musi być w osobnej linii i zaczynać się od jednego ze słów kluczowych:
warmup, interval, recovery, cooldown
Po przecinku podaj dystans (np. 2km lub 500m) LUB czas (np. 10min lub 90s).
Opcjonalnie po kolejnym przecinku podaj widełki tempa (np. 4:10-4:20) LUB tętna (np. 135-150bpm).
Nie używaj pętli typu "3x" - jeśli planujesz powtórzenia interwałów, rozpisz każdy interval i recovery w osobnej linii.

Przykład poprawnego formatu steps:
warmup, 2km, 5:15-5:35
interval, 1km, 4:00-4:10
recovery, 2min
interval, 1km, 4:00-4:10
cooldown, 1.5km, 5:20-5:40

Zwróć odpowiedź WYŁĄCZNIE jako czysty obiekt JSON w formacie:
{{
  "workout_name": "Krótka nazwa treningu + krótkie uzasadnienie w nawiasie",
  "steps": "wieloliniowy tekst z krokami treningu zgodny z zasadami powyżej"
}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3
        }
    }

    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(raw_text)

def main():
    print("Łączenie z Google Sheets...")
    sh = get_spreadsheet()
    
    wellness_sheet = sh.worksheet("Wellness")
    activities_sheet = sh.worksheet("Aktywnosci")
    treningi_sheet = sh.worksheet("Treningi")
    
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    target_date = tomorrow.isoformat()
    days_pl = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
    day_name = days_pl[tomorrow.weekday()]

    # Sprawdzamy, czy na jutro nie ma już zaplanowanego treningu
    planned_records = treningi_sheet.get_all_records()
    for row in planned_records:
        if str(row.get("Data", "")).strip() == target_date:
            print(f"Trening na jutro ({target_date}) już istnieje w arkuszu. Pomijam.")
            return

    # Pobieramy kontekst (tylko ostatnie wiersze, aby nie przekroczyć limitu tokenów)
    wellness_records = wellness_sheet.get_all_records()[-7:]
    activity_records = activities_sheet.get_all_records()[-10:]

    print(f"Wysyłanie danych do Gemini AI (Uwagi: {USER_NOTES})...")
    ai_plan = ask_gemini_coach(wellness_records, activity_records, USER_NOTES, target_date, day_name)

    workout_name = ai_plan.get("workout_name", "Trening AI")
    steps_code = ai_plan.get("steps", "interval, 8km, 5:10-5:30").strip()

    # Dodajemy nagłówek w 1. linii, którego wymaga sync_calendar.py (lines[1:])
    full_workout_code = f"{target_date} {workout_name}\n{steps_code}"

    # Status "Do wgrania" sprawi, że sync_calendar.py od razu wyśle trening do Garmina
    new_row = [
        target_date,
        workout_name,
        full_workout_code,
        "Do wgrania"
    ]
    
    treningi_sheet.append_row(new_row)
    print(f"SUKCES: Gemini zaplanowało trening -> {workout_name}")

if __name__ == "__main__":
    main()
