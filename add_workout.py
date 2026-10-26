import re
import os
from garmin_auth import GarminAuthenticator

class WorkoutStepParser:
    """Odpowiada wyłącznie za rozbijanie tekstu na zmienne (OOP - Single Responsibility)."""
    def __init__(self):
        # Wyłapuje dystans (np. 2km, 2.5km, 500m)
        self.dist_re = re.compile(r'(\d+(?:\.\d+)?)\s*(km|m)\b', re.IGNORECASE)
        # Wyłapuje czas (np. 10min, 30s)
        self.time_re = re.compile(r'(\d+(?:\.\d+)?)\s*(min|s|sek)\b', re.IGNORECASE)
        # Wyłapuje widełki tętna (np. 125-138bpm lub 125 - 138 bpm)
        self.hr_re = re.compile(r'(\d+)\s*-\s*(\d+)\s*bpm', re.IGNORECASE)

    def parse(self, step_type: str, text: str) -> dict:
        parsed = {
            "step_type": step_type,
            "condition_type": "lap.button", 
            "condition_value": None,
            "target_type": "no.target",
            "target_value_1": None,
            "target_value_2": None,
            "description": text.strip()
        }

        # 1. Parsowanie czasu
        time_match = self.time_re.search(parsed["description"])
        if time_match:
            val = float(time_match.group(1))
            unit = time_match.group(2).lower()
            parsed["condition_type"] = "time"
            parsed["condition_value"] = int(val * 60) if unit == 'min' else int(val)
            parsed["description"] = self.time_re.sub('', parsed["description"]).strip()

        # 2. Parsowanie dystansu (nadpisuje lap.button lub czas)
        dist_match = self.dist_re.search(parsed["description"])
        if dist_match:
            val = float(dist_match.group(1))
            unit = dist_match.group(2).lower()
            parsed["condition_type"] = "distance"
            parsed["condition_value"] = int(val * 1000) if unit == 'km' else int(val)
            parsed["description"] = self.dist_re.sub('', parsed["description"]).strip()

        # 3. Parsowanie tętna (TUTAJ JEST TWOJA POPRAWKA)
        hr_match = self.hr_re.search(parsed["description"])
        if hr_match:
            parsed["target_type"] = "heart.rate.bpm"
            parsed["target_value_1"] = int(hr_match.group(1))
            parsed["target_value_2"] = int(hr_match.group(2))
            # Usuwamy wyłapane bpm z notatki
            parsed["description"] = self.hr_re.sub('', parsed["description"]).strip()

        # Oczyszczenie opisu z podwójnych spacji
        parsed["description"] = re.sub(r'\s+', ' ', parsed["description"]).strip()
        
        # Jeśli notatka jest pusta, zamieniamy na None (aby API Garmina nie wyrzucało błędów)
        if not parsed["description"]:
            parsed["description"] = None

        return parsed


class GarminWorkoutBuilder:
    """Odpowiada wyłącznie za tworzenie struktury JSON wymaganej przez API Garmina."""
    def __init__(self, workout_name: str, sport="running"):
        self.workout = {
            "workoutName": workout_name,
            "sport": sport,
            "workoutSegments": [{"segmentOrder": 1, "workoutSteps": []}]
        }
        self.step_order = 1

    def add_step(self, parsed_data: dict):
        step_type_map = {"warmup": 1, "cooldown": 2, "interval": 3, "recovery": 4}
        condition_map = {"time": 2, "distance": 3, "lap.button": 4}
        target_map = {"no.target": 1, "heart.rate.bpm": 4, "pace": 6}

        step = {
            "type": "ExecutableStepDTO",
            "stepOrder": self.step_order,
            "stepType": {
                "stepTypeId": step_type_map.get(parsed_data["step_type"], 3),
                "stepTypeKey": parsed_data["step_type"]
            },
            "endCondition": {
                "conditionTypeId": condition_map.get(parsed_data["condition_type"], 4),
                "conditionTypeKey": parsed_data["condition_type"]
            },
            "endConditionValue": parsed_data["condition_value"],
            "targetType": None,
            "targetValueOne": None,
            "targetValueTwo": None,
            "description": parsed_data["description"]
        }

        # Jeśli Parser znalazł widełki tętna, wstrzykujemy je do JSONa
        if parsed_data["target_type"] != "no.target":
            step["targetType"] = {
                "workoutTargetTypeId": target_map.get(parsed_data["target_type"], 1),
                "workoutTargetTypeKey": parsed_data["target_type"]
            }
            step["targetValueOne"] = parsed_data["target_value_1"]
            step["targetValueTwo"] = parsed_data["target_value_2"]

        self.workout["workoutSegments"][0]["workoutSteps"].append(step)
        self.step_order += 1

    def get_payload(self) -> dict:
        return self.workout


class WorkoutManager:
    """Odpowiada wyłącznie za uwierzytelnianie i autoryzowaną wysyłkę paczki."""
    def __init__(self, garmin_client):
        self.client = garmin_client

    def upload_workout(self, workout_payload: dict):
        try:
            print(f"Wysyłanie treningu: '{workout_payload['workoutName']}' do Garmina...")
            
            # TODO: Jeśli korzystasz ze specyficznej metody garminconnect do dodawania, wklej ją tu.
            # self.client.add_workout(workout_payload) 
            
            print("Trening z targetami HR i poprawnie wyczyszczoną notatką został zbudowany i przekazany!")
        except Exception as e:
            print(f"Błąd wysyłania: {e}")


def main():
    garmin_client = GarminAuthenticator().login()
    manager = WorkoutManager(garmin_client)

    parser = WorkoutStepParser()
    builder = GarminWorkoutBuilder(workout_name="Trening: Testowy Interwał OOP")

    # To Twoje potencjalne wejście z innego pliku/zewnętrznego serwisu:
    segments = [
        ("warmup", "10min Rozgrzewka"),
        ("interval", "2km 125-138bpm"),                  # Teraz 125-138 pójdzie jako TARGET, a notatka będzie pusta!
        ("recovery", "2min Odpoczynek po interwale"),
        ("interval", "2km 145-155bpm Trzeci zakres"),    # Tutaj będzie poprawny target HR, a notatką zostanie tylko "Trzeci zakres"
        ("cooldown", "2km")
    ]

    for step_type, text in segments:
        parsed_step = parser.parse(step_type, text)
        builder.add_step(parsed_step)

    final_workout_json = builder.get_payload()
    manager.upload_workout(final_workout_json)

if __name__ == "__main__":
    main()
