import json
import os
import sys
import requests

# Pobieranie sekretów/zmiennych środowiskowych
ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")


def add_workout_to_intervals(workout_json_str):
  if not ATHLETE_ID or not API_KEY:
    print(
        "❌ Błąd: Brak INTERVALS_ATHLETE_ID lub INTERVALS_API_KEY w"
        " sekretach/zmiennych środowiskowych."
    )
    sys.exit(1)

  # 1. Parsowanie wejścia JSON
  try:
    parsed_data = json.loads(workout_json_str)
  except json.JSONDecodeError as e:
    print(f"❌ Błąd parsowania formatu JSON: {e}")
    sys.exit(1)

  # Obsługa pojedynczego obiektu dict {} lub listy [{}]
  if isinstance(parsed_data, list):
    if not parsed_data:
      print("⚠️ Przekazana lista treningów jest pusta.")
      return
    workouts = parsed_data
  elif isinstance(parsed_data, dict):
    workouts = [parsed_data]
  else:
    print("❌ Niepoprawny format danych (oczekiwano obiektu JSON lub listy).")
    sys.exit(1)

  url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/events"

  # 2. Wysyłanie treningu do Intervals.icu
  for w in workouts:
    date_str = w.get("date")
    name = w.get("name")
    description = w.get("desc") or w.get("description", "")
    workout_type = w.get("type", "Run")  # Run, WeightTraining, Swim, Ride itp.
    start_time = w.get("time", "07:00:00")  # Domyślna godzina w kalendarzu

    if not date_str or not name:
      print("❌ Błąd: Trening musi zawierać pola 'date' oraz 'name'.")
      continue

    # Format ISO: YYYY-MM-DDTHH:MM:SS
    start_date_local = (
        f"{date_str}T{start_time}" if "T" not in date_str else date_str
    )

    payload = {
        "category": "WORKOUT",
        "start_date_local": start_date_local,
        "type": workout_type,
        "name": name,
        "description": description,
    }

    try:
      response = requests.post(
          url, auth=("API_KEY", API_KEY), json=payload, timeout=10
      )

      if response.status_code in [200, 201]:
        res_data = response.json()
        event_id = res_data.get("id", "N/A")
        print(f"✅ Dodano trening do Intervals.icu!")
        print(f"   📅 Data: {date_str} ({start_time})")
        print(f"   🏃 Nazwa: {name}")
        print(f"   🏷️ Typ: {workout_type}")
        print(f"   🆔 ID Zdarzenia: {event_id}")
      else:
        print(
            f"❌ Błąd API Intervals [{response.status_code}]: {response.text}"
        )

    except requests.RequestException as e:
      print(f"❌ Błąd połączenia z API: {e}")


if __name__ == "__main__":
  # Priorytetowo szuka zmiennej WORKOUT_PLAN, ew. WEEKLY_PLAN
  raw_input = os.environ.get("WORKOUT_PLAN") or os.environ.get(
      "WEEKLY_PLAN", "{}"
  )
  add_workout_to_intervals(raw_input)
