"""Usuwanie treningu z kalendarza Garmin Connect po dacie i nazwie (wywoływane z Taskera po alercie Join)."""
import datetime
import os
import sys

from common.garmin_auth import GarminAuthenticator
from common.garmin_calendar import delete_workout, get_calendar_items


def main():
    target_date = os.getenv("TARGET_DATE", "").strip()
    workout_name = os.getenv("WORKOUT_NAME", "").strip()

    if not target_date or not workout_name:
        print("Błąd: Brak daty (TARGET_DATE) lub nazwy treningu (WORKOUT_NAME) do usunięcia.")
        sys.exit(1)

    client = GarminAuthenticator().login()
    print(f"Szukanie treningu '{workout_name}' w dniu {target_date}...")

    try:
        date_obj = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
        cal_items = get_calendar_items(client, date_obj.year, date_obj.month)

        workout_id_to_delete = None
        for item in cal_items:
            if item.get("itemType") == "workout" and item.get("date") == target_date and item.get("title") == workout_name:
                workout_id_to_delete = item.get("workoutId")
                break

        if workout_id_to_delete:
            delete_workout(client, workout_id_to_delete)
            print(f"SUKCES: Usunięto trening '{workout_name}' z Garmina ({target_date}).")
        else:
            print("Nie znaleziono pasującego treningu w kalendarzu Garmin.")
    except Exception as e:
        print(f"Wystąpił błąd podczas usuwania: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
