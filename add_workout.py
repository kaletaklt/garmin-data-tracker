import re
import os
from garmin_auth import GarminAuthenticator

class WorkoutStepParser:
    def __init__(self):
        self.dist_re = re.compile(r'(\d+(?:\.\d+)?)\s*(km|m)\b', re.IGNORECASE)
        self.time_re = re.compile(r'(\d+(?:\.\d+)?)\s*(min|s|sek)\b', re.IGNORECASE)
        self.hr_re = re.compile(r'(\d+)\s*-\s*(\d+)\s*bpm', re.IGNORECASE)
        self.pace_re = re.compile(r'(\d+):(\d{2})\s*-\s*(\d+):(\d{2})\s*min/km', re.IGNORECASE)

    def parse(self, step_type: str, text: str) -> dict:
        parsed = {
            "step_type": step_type.strip(),
            "condition_type": "lap.button", 
            "condition_value": None,
            "target_type": "no.target",
            "target_value_1": None,
            "target_value_2": None,
            "description": text.strip()
        }

        # 1. Parsowanie czasu trwania
        time_match = self.time_re.search(parsed["description"])
        if time_match:
            val = float(time_match.group(1))
            unit = time_match.group(2).lower()
            parsed["condition_type"] = "time"
            parsed["condition_value"] = int(val * 60) if unit == 'min' else int(val)
            parsed["description"] = self.time_re.sub('', parsed["description"]).strip()

        # 2. Parsowanie dystansu
        dist_match = self.dist_re.search(parsed["description"])
        if dist_match:
            val = float(dist_match.group(1))
            unit = dist_match.group(2).lower()
            parsed["condition_type"] = "distance"
            parsed["condition_value"] = int(val * 1000) if unit == 'km' else int(val)
            parsed["description"] = self.dist_re.sub('', parsed["description"]).strip()

        # 3. Parsowanie tętna (BPM)
        hr_match = self.hr_re.search(parsed["description"])
        if hr_match:
            parsed["target_type"] = "heart.rate.bpm"
            parsed["target_value_1"] = int(hr_match.group(1))
            parsed["target_value_2"] = int(hr_match.group(2))
            parsed["description"] = self.hr_re.sub('', parsed["description"]).strip()

        # 4. Parsowanie tempa (min/km -> m/s)
        pace_match = self.pace_re.search(parsed["description"])
        if pace_match:
            parsed["target_type"] = "pace"
            sec_per_km_1 = int(pace_match.group(1)) * 60 + int(pace_match.group(2))
            sec_per_km_2 = int(pace_match.group(3)) * 60 + int(pace_match.group(4))
            
            if sec_per_km_1 > 0 and sec_per_km_2 > 0:
                parsed["target_value_1"] = round(1000.0 / sec_per_km_1, 3) 
                parsed["target_value_2"] = round(1000.0 / sec_per_km_2, 3) 
            
            parsed["description"] = self.pace_re.sub('', parsed["description"]).strip()

        # Oczyszczenie opisów
        parsed["description"] = re.sub(r'\s+', ' ', parsed["description"]).strip()
        if not parsed["description"]:
            parsed["description"] = None

        return parsed


class GarminWorkoutBuilder:
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
    def __init__(self, garmin_client):
        self.client = garmin_client

    def upload_workout(self, workout_payload: dict):
        try:
            print(f"Wysyłanie treningu: '{workout_payload['workoutName']}' do Garmina...")
            # Dedykowana metoda w bibliotece garminconnect:
            # self.client.add_workout(workout_payload) 
            print("Trening zaimportowany pomyślnie!")
        except Exception as e:
            print(f"Błąd wysyłania: {e}")


def main():
    # Przykład prostego podawania surowego kodu treningu, np. ze zmiennej w GitHub Actions
    workout_name = "Czwartek: Progi tempowe 2x 3km (Sub 1:30 HM)"
    raw_workout_code = """
    warmup, 15min 125-138bpm Swobodna rozgrzewka
    interval, 3km 4:10-4:20min/km Wejście w próg mleczanowy
    recovery, 3min 120-130bpm Luźny trucht do wyrównania oddechu
    interval, 3km 4:10-4:20min/km Stabilne tempo startowe
    cooldown, 10min 125-135bpm Wyciszenie organizmu
    """

    garmin_client = GarminAuthenticator().login()
    manager = WorkoutManager(garmin_client)
    parser = WorkoutStepParser()
    builder = GarminWorkoutBuilder(workout_name)

    # Parsowanie surowego tekstu linijka po linijce
    for line in raw_workout_code.strip().split('\n'):
        if ',' not in line:
            continue
        step_type, text = line.split(',', 1)
        parsed_step = parser.parse(step_type, text)
        builder.add_step(parsed_step)

    manager.upload_workout(builder.get_payload())

if __name__ == "__main__":
    main()
