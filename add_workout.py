import re
import os
import sys
import garth  # Omijamy garminconnect i korzystamy bezpośrednio z głównej biblioteki sesji!
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

        time_match = self.time_re.search(parsed["description"])
        if time_match:
            val = float(time_match.group(1))
            unit = time_match.group(2).lower()
            parsed["condition_type"] = "time"
            parsed["condition_value"] = int(val * 60) if unit == 'min' else int(val)
            parsed["description"] = self.time_re.sub('', parsed["description"]).strip()

        dist_match = self.dist_re.search(parsed["description"])
        if dist_match:
            val = float(dist_match.group(1))
            unit = dist_match.group(2).lower()
            parsed["condition_type"] = "distance"
            parsed["condition_value"] = int(val * 1000) if unit == 'km' else int(val)
            parsed["description"] = self.dist_re.sub('', parsed["description"]).strip()

        hr_match = self.hr_re.search(parsed["description"])
        if hr_match:
            hr1 = int(hr_match.group(1))
            hr2 = int(hr_match.group(2))
            parsed["target_type"] = "heart.rate.bpm"
            # Garmin wymaga rosnących wartości
            parsed["target_value_1"] = min(hr1, hr2)
            parsed["target_value_2"] = max(hr1, hr2)
            parsed["description"] = self.hr_re.sub('', parsed["description"]).strip()

        pace_match = self.pace_re.search(parsed["description"])
        if pace_match:
            parsed["target_type"] = "pace"
            sec_per_km_1 = int(pace_match.group(1)) * 60 + int(pace_match.group(2))
            sec_per_km_2 = int(pace_match.group(3)) * 60 + int(pace_match.group(4))
            
            if sec_per_km_1 > 0 and sec_per_km_2 > 0:
                v1 = round(1000.0 / sec_per_km_1, 3) 
                v2 = round(1000.0 / sec_per_km_2, 3) 
                parsed["target_value_1"] = min(v1, v2)
                parsed["target_value_2"] = max(v1, v2)
            
            parsed["description"] = self.pace_re.sub('', parsed["description"]).strip()

        parsed["description"] = re.sub(r'\s+', ' ', parsed["description"]).strip()
        if not parsed["description"]:
            parsed["description"] = None

        return parsed


class GarminWorkoutBuilder:
    def __init__(self, workout_name: str, sport="running"):
        self.workout = {
            "workoutName": workout_name,
            "sportType": {
                "sportTypeId": 1,
                "sportTypeKey": sport
            },
            "workoutSegments": [{"segmentOrder": 1, "sportType": {"sportTypeId": 1, "sportTypeKey": sport}, "workoutSteps": []}]
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
            "description": parsed_data["description"]
        }

        # Wstrzykujemy target wyłącznie jeśli istnieje, by nie drażnić API Garmina
        if parsed_data["target_type"] != "no.target":
            step["targetType"] = {
                "workoutTargetTypeId": target_map.get(parsed_data["target_type"], 1),
                "workoutTargetTypeKey": parsed_data["target_type"]
            }
            step["targetValueOne"] = parsed_data["target_value_1"]
            step["targetValueTwo"] = parsed_data["target_value_2"]
        else:
            step["targetType"] = None
            step["targetValueOne"] = None
            step["targetValueTwo"] = None

        self.workout["workoutSegments"][0]["workoutSteps"].append(step)
        self.step_order += 1

    def get_payload(self) -> dict:
        return self.workout


class WorkoutManager:
    def __init__(self, garmin_client):
        self.client = garmin_client # Obiekt autoryzacji podtrzymujący sesję

    def _post_garmin_api(self, url_path: str, payload: dict):
        """Wysyła surowe żądanie HTTP przez globalną, już zautoryzowaną sesję garth."""
        try:
            # Upewniamy się, że url zaczyna się od '/'
            if not url_path.startswith('/'):
                url_path = '/' + url_path
            
            return garth.client.post("connect", url_path, json=payload)
        except Exception as e:
            # Garth HTTP Error często zawiera w sobie powód odrzucenia przez Garmina
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                print(f"API Garmina odrzuciło żądanie. Kod błędu: {e.response.status_code}. Treść: {e.response.text}")
            raise e

    def upload_and_schedule(self, workout_payload: dict, target_date: str):
        try:
            print(f"Zapisywanie treningu: '{workout_payload['workoutName']}' w bibliotece Garmina...")
            
            response = self._post_garmin_api("/workout-service/workout", workout_payload)
            
            workout_id = None
            if isinstance(response, dict):
                workout_id = response.get("workoutId")
            elif hasattr(response, 'json'):
                workout_id = response.json().get("workoutId")
            
            if not workout_id:
                print(f"ODPOWIEDŹ Z SERWERA GARMIN: {response}")
                raise ValueError("Serwer Garmina przyjął JSON-a, ale nie zwrócił ID treningu.")
            
            print(f"Trening pomyślnie zapisany (ID: {workout_id}). Przypisywanie do kalendarza na dzień {target_date}...")
            
            # Wysłanie żądania przypisania do kalendarza
            self._post_garmin_api(f"/workout-service/schedule/{workout_id}", {"date": target_date})
            print(f"SUKCES! Trening dodano i przypisano do kalendarza na dzień: {target_date}")
            
        except Exception as e:
            print(f"Błąd krytyczny komunikacji z API: {e}")
            sys.exit(1)


def main():
    raw_workout_code = os.getenv("WORKOUT_CODE", "")
    
    if not raw_workout_code:
        print("Błąd: Brak kodu treningu. Puste pole.")
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
    workout_name = prefix.replace(target_date, '').strip()
    
    if not workout_name:
        workout_name = "Nowy Trening Biegowy"

    garmin_client = GarminAuthenticator().login()
    manager = WorkoutManager(garmin_client)
    parser = WorkoutStepParser()
    builder = GarminWorkoutBuilder(workout_name)

    for i in range(1, len(parts), 2):
        step_type = parts[i].lower()
        text = parts[i+1]
        parsed_step = parser.parse(step_type, text)
        builder.add_step(parsed_step)

    manager.upload_and_schedule(builder.get_payload(), target_date)


if __name__ == "__main__":
    main()
