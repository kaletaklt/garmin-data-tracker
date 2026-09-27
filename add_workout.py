import os
import sys
import argparse
import requests

ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")

def add_workout(date_str, name, description):
    if not ATHLETE_ID or not API_KEY:
        print("Brak INTERVALS_ATHLETE_ID lub INTERVALS_API_KEY w sekretach.")
        sys.exit(1)

    url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/events"
    
    payload = {
        "category": "WORKOUT",
        "start_date_local": f"{date_str}T07:00:00",
        "type": "Run",
        "name": name,
        "description": description
    }
    
    response = requests.post(url, auth=("API_KEY", API_KEY), json=payload)
    
    if response.status_code in [200, 201]:
        print(f"Pomyślnie dodano trening '{name}' na dzień {date_str} do Intervals.icu!")
    else:
        print(f"Błąd wysyłania: {response.status_code} - {response.text}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Data YYYY-MM-DD")
    parser.add_argument("--name", required=True, help="Nazwa treningu")
    parser.add_argument("--desc", required=True, help="Struktura treningu")
    
    args = parser.parse_args()
    add_workout(args.date, args.name, args.desc)
