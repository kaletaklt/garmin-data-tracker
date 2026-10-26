class WorkoutManager:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def upload_and_schedule(self, workout_payload: dict, target_date: str):
        try:
            print(f"Zapisywanie treningu: '{workout_payload['workoutName']}' w bibliotece...")
            # 1. Zapisanie treningu (Garmin API zwraca z powrotem dodany obiekt wraz z jego nowym ID)
            # saved_workout = self.client.add_workout(workout_payload)
            # workout_id = saved_workout.get("workoutId")
            
            # 2. Przypisanie zapisanego treningu do konkretnej daty w kalendarzu
            # if workout_id and target_date:
            #     self.client.schedule_workout(workout_id, target_date)
            #     print(f"Sukces! Trening przypisano do kalendarza na dzień: {target_date}")
                
        except Exception as e:
            print(f"Błąd wysyłania do kalendarza: {e}")

def main():
    # Pobieranie danych wysłanych z Taskera
    target_date = os.getenv("TARGET_DATE")
    workout_name = os.getenv("WORKOUT_NAME", "Nowy Trening z Taskera")
    raw_workout_code = os.getenv("WORKOUT_CODE")

    if not raw_workout_code or not target_date:
        print("Brak kodu treningu lub daty. Uruchom skrypt podając parametry wejściowe.")
        return

    garmin_client = GarminAuthenticator().login()
    manager = WorkoutManager(garmin_client)
    parser = WorkoutStepParser()
    builder = GarminWorkoutBuilder(workout_name)

    # Parsowanie linijka po linijce z Taskera
    for line in raw_workout_code.strip().split('\n'):
        if ',' not in line:
            continue
        step_type, text = line.split(',', 1)
        parsed_step = parser.parse(step_type, text)
        builder.add_step(parsed_step)

    # Przekazanie paczki JSON oraz Daty
    manager.upload_and_schedule(builder.get_payload(), target_date)

if __name__ == "__main__":
    main()
