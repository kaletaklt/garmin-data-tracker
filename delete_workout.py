import os
import sys
import datetime
from garmin_auth import GarminAuthenticator

def main():
    target_date = os.getenv("TARGET_DATE", "")
    workout_name = os.getenv("WORKOUT_NAME", "")
    
    if not target_date or not workout_name:
        print("Błąd: Brak daty lub nazwy treningu do usunięcia.")
        sys.exit(1)
        
    client = GarminAuthenticator().login()
    print(f"Szukanie treningu '{workout_name}' w dniu {target_date}...")
    
    try:
        date_obj = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        cal = client.get_training_calendar(date_obj.year, date_obj.month)
        
        workout_id_to_delete = None
        for item in cal:
            if item.get("date") == target_date and item.get("title") == workout_name:
                workout_id_to_delete = item.get("workoutId")
                break
        
        if workout_id_to_delete:
            client.delete_workout(workout_id_to_delete)
            print(f"SUKCES: Usunięto trening '{workout_name}' z Garmina.")
        else:
            print("Nie znaleziono pasującego treningu w kalendarzu.")
            
    except Exception as e:
        print(f"Wystąpił błąd podczas usuwania: {e}")

if __name__ == "__main__":
    main()