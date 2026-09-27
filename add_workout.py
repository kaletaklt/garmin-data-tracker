import os
import sys
import json
import requests

ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")

def upload_workouts(weekly_plan_json):
    if not ATHLETE_ID or not API_KEY:
        print("Brak INTERVALS_ATHLETE_ID lub INTERVALS_API_KEY w sekretach.")
        sys.exit(1)

    try:
        workouts = json.loads(weekly_plan_json)
    except Exception as e:
        print(f"Błąd parsowania formatu JSON: {e}")
        sys.exit(1)

    url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/events"

    for w in workouts:
        date_str = w.get("date")
        name = w.get("name")
        description = w.get("desc")

        payload = {
            "category": "WORKOUT",
            "start_date_local": f"{date_str}T07:00:00",
            "type": "Run",
            "name": name,
            "description": description
        }

        response = requests.post(url, auth=("API_KEY", API_KEY), json=payload)

        if response.status_code in [200, 201]:
            print(f"✅ Dodano: {date_str} - {name}")
        else:
            print(f"❌ Błąd dla {date_str} ({name}): {response.status_code} - {response.text}")

if __name__ == "__main__":
    raw_input = os.environ.get("WEEKLY_PLAN", "[]")
    upload_workouts(raw_input)
