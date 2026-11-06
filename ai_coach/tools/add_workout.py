"""Ręczne wgranie pojedynczego treningu biegowego do kalendarza Garmin Connect (workflow add_workout.yml)."""
import os
import re
import sys

from common.garmin_auth import GarminAuthenticator
from common.garmin_calendar import upload_and_schedule
from common.workout_parser import GarminWorkoutBuilder, WorkoutStepParser


def main():
    raw_workout_code = os.getenv("WORKOUT_CODE", "")
    if not raw_workout_code:
        print("Błąd: Brak kodu treningu. Puste pole WORKOUT_CODE.")
        sys.exit(1)

    parts = re.split(r'\b(warmup|interval|recovery|cooldown)\s*,', raw_workout_code, flags=re.IGNORECASE)
    if len(parts) < 3:
        print("Błąd: Nie rozpoznano segmentów. Oczekiwano identyfikatorów np. 'warmup,' lub 'interval,'.")
        sys.exit(1)

    prefix = parts[0].strip()
    date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', prefix)
    if not date_match:
        print("Błąd: Nie znaleziono daty w formacie YYYY-MM-DD.")
        sys.exit(1)

    target_date = date_match.group(1)
    workout_name = prefix.replace(target_date, "").strip() or "Nowy Trening Biegowy"

    garmin_client = GarminAuthenticator().login()
    parser = WorkoutStepParser()
    builder = GarminWorkoutBuilder(workout_name)

    for i in range(1, len(parts), 2):
        step_type = parts[i].lower()
        text = parts[i + 1]
        builder.add_step(parser.parse(step_type, text))

    upload_and_schedule(garmin_client, builder.get_payload(), target_date)


if __name__ == "__main__":
    main()
