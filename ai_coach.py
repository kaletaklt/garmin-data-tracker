import os
import re
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


def rows_to_dicts(sheet, max_cols, tail_count):
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return []
    headers = all_values[0][:max_cols]
    data_rows = all_values[1:][-tail_count:]
    result = []
    for row in data_rows:
        padded = row[:max_cols] + [""] * max(0, max_cols - len(row))
        result.append(dict(zip(headers, padded)))
    return result


def ensure_treningi_headers(treningi_sheet):
    expected = ["Data", "Nazwa", "Kod Treningu", "Status"]
    all_values = treningi_sheet.get_all_values()
    if not all_values or all_values[0][:4] != expected:
        print("Naprawianie nagłówków w zakładce 'Treningi'...")
        treningi_sheet.clear()
        treningi_sheet.append_row(expected)
        return []
    return all_values[1:]


def get_candidate_models():
    preferred_order = [
        "gemini-flash-latest",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-4-argon",
        "gemini-pro-latest",
        "gemini-3.1-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.5-flash"
    ]
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        models_data = r.json().get("models", [])
        available = [
            m["name"].replace("models/", "")
            for m in models_data
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        candidates = [m for m in preferred_order if m in available]
        for m in available:
            if m not in candidates and "tts" not in m and "image" not in m and "lyria" not in m:
                candidates.append(m)
        return candidates if candidates else preferred_order
    except Exception as e:
        print(f"Nie udało się pobrać listy modeli ({e}), używam listy domyślnej.")
        return preferred_order


def parse_json_response(raw_text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned)


def ask_gemini_coach(wellness_history, recent_activities, user_notes, target_date, day_name):
    if not GEMINI_API_KEY:
        raise ValueError("Brak klucza GEMINI_LLM_API_KEY w zmiennych środowiskowych!")

    prompt = f"""Jesteś zaawansowanym trenerem biegania i przygotowania motorycznego.
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
}}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3
        }
    }

    candidates = get_candidate_models()
    last_error = None

    for model_name in candidates:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        print(f"Próba wywołania modelu: {model_name}...")
        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"Sukces z modelem: {model_name}")
                return parse_json_response(raw_text)
            else:
                print(f"Model {model_name} zwrócił kod {response.status_code}: {response.text[:200]}")
                last_error = f"{response.status_code}: {response.text}"
        except Exception as e:
            print(f"Błąd przy modelu {model_name}: {e}")
            last_error = str(e)

    raise RuntimeError(f"Wszystkie modele Gemini zawiodły. Ostatni błąd: {last_error}")


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

    existing_rows = ensure_treningi_headers(treningi_sheet)
    for row in existing_rows:
        if row and str(row[0]).strip() == target_date:
            print(f"Trening na jutro ({target_date}) już istnieje w arkuszu. Pomijam.")
            return

    wellness_records = rows_to_dicts(wellness_sheet, max_cols=24, tail_count=7)
    activity_records = rows_to_dicts(activities_sheet, max_cols=25, tail_count=10)

    print(f"Wysyłanie danych do Gemini AI (Uwagi: {USER_NOTES})...")
    ai_plan = ask_gemini_coach(wellness_records, activity_records, USER_NOTES, target_date, day_name)

    workout_name = ai_plan.get("workout_name", "Trening AI")
    steps_code = ai_plan.get("steps", "interval, 8km, 5:10-5:30").strip()

    full_workout_code = f"{target_date} {workout_name}\n{steps_code}"

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
