"""Parser kroków treningowych (`Kod Treningu`) i budowniczy payloadu Garmin ExecutableStepDTO."""
import re

STEP_TYPES = ("warmup", "interval", "recovery", "cooldown")
SPORT_TYPE_IDS = {"running": 1, "cycling": 2, "other": 3, "swimming": 4, "strength_training": 5}


class WorkoutStepParser:
    def __init__(self):
        self.dist_re = re.compile(r'(\d+(?:\.\d+)?)\s*(km|m)\b', re.IGNORECASE)
        self.time_re = re.compile(r'(\d+(?:\.\d+)?)\s*(min|s|sek)\b', re.IGNORECASE)
        self.hr_re = re.compile(r'(\d+)\s*-\s*(\d+)\s*bpm', re.IGNORECASE)
        # Obsługuje pełny zapis (3:45-4:20) oraz ucięte/uproszczone warianty (np. 3:45-4:/km)
        self.pace_re = re.compile(r'(\d+):(\d{2})\s*-\s*(\d+):(\d{0,2})\s*(?:min/km|/km)?', re.IGNORECASE)

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
            parsed["target_value_1"] = min(hr1, hr2)
            parsed["target_value_2"] = max(hr1, hr2)
            parsed["description"] = self.hr_re.sub('', parsed["description"]).strip()

        pace_match = self.pace_re.search(parsed["description"])
        if pace_match:
            parsed["target_type"] = "pace"
            m1, s1 = int(pace_match.group(1)), int(pace_match.group(2))
            m2, s2_str = pace_match.group(3), pace_match.group(4)
            # Bezpieczne obsłużenie pustych lub uciętych sekund (np. gdy zczyta "4:")
            s2 = int(s2_str) if s2_str else 0

            sec_per_km_1 = m1 * 60 + s1
            sec_per_km_2 = int(m2) * 60 + s2
            if sec_per_km_1 > 0 and sec_per_km_2 > 0:
                v1 = round(1000.0 / sec_per_km_1, 3)
                v2 = round(1000.0 / sec_per_km_2, 3)
                parsed["target_value_1"] = min(v1, v2)
                parsed["target_value_2"] = max(v1, v2)

            parsed["description"] = re.sub(r'\d+:\d{0,2}\s*-\s*\d+:\d{0,2}\s*(?:min/km|/km)?', '', parsed["description"]).strip()

        parsed["description"] = re.sub(r'\s+', ' ', parsed["description"]).strip()
        if not parsed["description"]:
            parsed["description"] = None

        return parsed


class GarminWorkoutBuilder:
    def __init__(self, workout_name: str, sport="running"):
        sport_type = {"sportTypeId": SPORT_TYPE_IDS.get(sport, 1), "sportTypeKey": sport}
        self.workout = {
            "workoutName": workout_name,
            "sportType": sport_type,
            "workoutSegments": [{"segmentOrder": 1, "sportType": dict(sport_type), "workoutSteps": []}]
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


def iter_step_lines(code_str):
    """Zwraca pary (typ_kroku, tekst) z `Kod Treningu`. Linia nagłówka `YYYY-MM-DD Nazwa` jest pomijana."""
    raw = (code_str or "").replace(r'\n', '\n')
    for line in raw.split('\n'):
        line = line.strip().lstrip(', ').strip()
        parts = re.split(r'[\s,]+', line, maxsplit=1)
        if len(parts) < 2:
            continue
        step_type = parts[0].lower()
        if step_type in STEP_TYPES:
            yield step_type, parts[1].lstrip(', ').strip()


def build_running_workout(workout_name, code_str):
    parser = WorkoutStepParser()
    builder = GarminWorkoutBuilder(workout_name)
    for step_type, text in iter_step_lines(code_str):
        builder.add_step(parser.parse(step_type, text))
    if builder.step_order == 1:
        raise ValueError(f"Kod treningu '{workout_name}' nie zawiera żadnego kroku warmup/interval/recovery/cooldown.")
    return builder.get_payload()


def build_strength_workout(workout_name, description="Sesja siłowa z Google Calendar"):
    """Minimalny trening siłowy (jeden krok do przycisku Lap) - znacznik zajętego dnia w kalendarzu Garmin."""
    builder = GarminWorkoutBuilder(workout_name, sport="strength_training")
    builder.add_step({
        "step_type": "interval", "condition_type": "lap.button", "condition_value": None,
        "target_type": "no.target", "target_value_1": None, "target_value_2": None,
        "description": description,
    })
    return builder.get_payload()


def is_rest_code(code_str):
    code = (code_str or "").strip().upper()
    return not code or code.startswith("REST")


def planned_distance_km(code_str):
    """Suma zaplanowanych kilometrów w krokach treningu (0.0 dla REST)."""
    total = 0.0
    if is_rest_code(code_str):
        return total
    for _, text in iter_step_lines(code_str):
        m_km = re.search(r"(\d+(?:\.\d+)?)\s*km\b", text, re.IGNORECASE)
        m_m = re.search(r"(\d+)\s*m\b", text, re.IGNORECASE)
        if m_km:
            total += float(m_km.group(1))
        elif m_m:
            total += float(m_m.group(1)) / 1000.0
    return round(total, 2)
