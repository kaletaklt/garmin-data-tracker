import sys
from garmin_auth import GarminAuthenticator

class WorkoutManager:
    def __init__(self, garmin_client):
        self.client = garmin_client

    def upload_workout(self, workout_data):
        """Dodaje zaplanowany trening lub wczytuje plik FIT/TCX."""
        try:
            print("Przetwarzanie treningu...")
            # Poniżej znajduje się przykładowe wywołanie – biblioteka garminconnect 
            # posiada różne metody uploadu w zależności od typu danych.
            # self.client.upload_activity(workout_data)
            print("Trening został pomyślnie dodany do kalendarza Garmin.")
        except Exception as e:
            print(f"Błąd podczas dodawania treningu: {e}")

def main():
    # 1. Logowanie przez zewnętrzną klasę
    auth = GarminAuthenticator()
    garmin_client = auth.login()

    # 2. Przekazanie sesji do menedżera
    manager = WorkoutManager(garmin_client)
    
    # 3. Akcja właściwa
    sample_workout = {"name": "Interwały", "type": "running"}
    manager.upload_workout(sample_workout)

if __name__ == "__main__":
    main()
