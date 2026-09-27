import json
import os
import sys
import requests

ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")


def upload_workout(workout_json):
  if not ATHLETE_ID or not API_KEY:
    print("Brak INTERVALS_ATHLETE_ID lub INTERVALS_API_KEY w sekretach.")
    sys.exit(1)

  try:
    data = json.loads(workout_json)
    # Obsługa zarówno pojedynczego obiektu dict {}, jak i listy z jednym elementem [{}]
    if isinstance(data, list):
      if not data:
        print("Przekazano pustą listę treningów.")
        sys.exit(0)
      workout = data[0]
    elif isinstance(data, dict):
      workout = data
    else:
      print("Niepoprawny format danych (oczekiwano obiektu JSON).")
      sys.exit(1)
  except Exception as e:
    print(f"Błąd parsowania formatu JSON: {e}")
    sys.exit(1)

  date_str = workout.get("date")
  name = workout.get("name")
  description = workout.get("desc", "")

  if not date_str or not name:
    print("Błąd: Trening musi zawierać przynajmniej pola 'date' oraz 'name'.")
    sys.exit(1)

  url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/events"

  payload = {
      "category": "WORKOUT",
      "start_date_local": f"{date_str}T07:00:00",
      "type": "Run",
      "name": name,
      "description": description,
  }

  response = requests.post(url, auth=("API_KEY", API_KEY), json=payload)

  if response.status_code in [200, 201]:
    print(f"✅ Dodano trening: {date_str} - {name}")
  else:
    print(
        f"❌ Błąd dla {date_str} ({name}):"
        f" {response.status_code} - {response.text}"
    )


if __name__ == "__main__":
  # Domyślnie oczekuje pojedynczego słownika w zmiennej WORKOUT_PLAN
  raw_input = os.environ.get("WORKOUT_PLAN", "{}")
  upload_workout(raw_input)
