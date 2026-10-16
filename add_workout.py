import json
import os
import re
import sys
from garminconnect import Garmin

# Tętno maksymalne do przeliczania zakresów procentowych (%HR)
HR_MAX = 188


def parse_hr_target(target_str):
  """Rozpoznaje zapis tętna i zwraca wartości (targetValueLow, targetValueHigh)."""
  target_str = target_str.strip()

  # Zakres w bpm: np. "133-143bpm" lub "133-143"
  match_range = re.match(r"^(\d+)-(\d+)\s*bpm$", target_str, re.IGNORECASE)
  if match_range:
    return int(match_range.group(1)), int(match_range.group(2))

  # Poniżej tętna: np. "<133bpm" lub "<133"
  match_lt = re.match(r"^<(\d+)\s*bpm$", target_str, re.IGNORECASE)
  if match_lt:
    return 30, int(match_lt.group(1))

  # Zakres procentowy HRmax: np. "85-95%HR" lub "85-95%"
  match_pct = re.match(r"^(\d+)-(\d+)%\s*(?:HR)?$", target_str, re.IGNORECASE)
  if match_pct:
    pct_low = int(match_pct.group(1)) / 100.0
    pct_high = int(match_pct.group(2)) / 100.0
    return int(round(HR_MAX * pct_low)), int(round(HR_MAX * pct_high))

  return None, None


def parse_simple_text_to_garmin_workout(text_input):
  """Tłumaczy prosty tekst z pop-upu na pełną strukturę Garmin Workout DTO z celami tętna."""
  if not text_input or not text_input.strip():
    raise ValueError("Przekazano pusty tekst treningu.")

  text_input = text_input.strip()
  if (text_input.startswith('"') and text_input.endswith('"')) or (
      text_input.startswith("'") and text_input.endswith("'")
  ):
    text_input = text_input[1:-1].strip()

  text_input = text_input.replace("\\n", "\n")
  lines = [l.strip() for l in text_input.split("\n") if l.strip()]

  # Obsługa wejścia jednoliniowego z formularza
  if len(lines) == 1:
    single_line = lines[0]
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(.*)", single_line)
    if date_match:
      date_str = date_match.group(1)
      rest = date_match.group(2)
      parts = re.split(r"\s+-\s+|\s+-", rest)
      workout_name = parts[0].strip()
      step_lines = [f"- {p.strip()}" for p in parts[1:] if p.strip()]
      lines = [date_str, workout_name] + step_lines

  if len(lines) < 3:
    raise ValueError(
        f"Za mało linii w opisie treningu (wykryto {len(lines)})."
        " Wymagane min. 3: Data, Nazwa, Kroki."
    )

  date_str = lines[0]
  workout_name = lines[1]
  sport_running = {"sportTypeId": 1, "sportTypeKey": "running"}

  workout_dict = {
      "workoutName": workout_name,
      "sportType": sport_running,
      "workoutSegments": [{
          "segmentOrder": 1,
          "sportType": sport_running,
          "workoutSteps": [],
      }],
  }

  step_order = 1
  for line in lines[2:]:
    if line.startswith("-"):
      parts = line[1:].strip().split()
      if len(parts) >= 2:
        dist_str = parts[0].replace("km", "")
        target_str = parts[1]

        try:
          distance_meters = int(float(dist_str) * 1000)
        except ValueError:
          continue

        hr_low, hr_high = parse_hr_target(target_str)

        step = {
            "type": "ExecutableStepDTO",
            "stepId": None,
            "stepOrder": step_order,
            "childStepId": None,
            "description": None,  # Czyszczenie pola notatki
            "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
            "endCondition": {
                "conditionTypeId": 3,
                "conditionTypeKey": "distance",
            },
            "endConditionValue": distance_meters,
        }

        if hr_low is not None and hr_high is not None:
          # Ustawienie prawdziwego celu tętna w Garmin Connect
          step["targetType"] = {
              "workoutTargetTypeId": 4,
              "workoutTargetTypeKey": "heart.rate",
          }
          step["targetValueLow"] = hr_low
          step["targetValueHigh"] = hr_high
        else:
          step["targetType"] = {
              "workoutTargetTypeId": 1,
              "workoutTargetTypeKey": "no.target",
          }
          step["description"] = target_str

        workout_dict["workoutSegments"][0]["workoutSteps"].append(step)
        step_order += 1

  return workout_dict, date_str


def save_workout_to_garmin(client, workout_dict):
  """Wysyła żądanie utworzenia treningu przez connectapi / garth."""
  target = client.client if hasattr(client, "client") else client
  url_path = "/workout-service/workout"

  if hasattr(target, "_run_request"):
    try:
      resp = target._run_request("POST", url_path, json=workout_dict)
      res = resp.json()
      if isinstance(res, dict) and (res.get("workoutId") or res.get("id")):
        return res.get("workoutId") or res.get("id")
    except Exception as e:
      print(f"⚠️ _run_request note: {e}")

  if hasattr(client, "garth"):
    try:
      res = client.garth.post("connectapi", url_path, json=workout_dict).json()
      if isinstance(res, dict) and (res.get("workoutId") or res.get("id")):
        return res.get("workoutId") or res.get("id")
    except Exception as e:
      print(f"⚠️ garth note: {e}")

  raise RuntimeError("Nie udało się utworzyć treningu w Garmin Connect.")


def schedule_workout_on_garmin(client, workout_id, date_str):
  """Przypisuje utworzony trening do dnia w kalendarzu."""
  target = client.client if hasattr(client, "client") else client
  url_path = f"/workout-service/schedule/{workout_id}"
  payload = {"date": date_str}

  if hasattr(target, "_run_request"):
    try:
      target._run_request("POST", url_path, json=payload)
      return True
    except Exception:
      pass

  if hasattr(client, "garth"):
    try:
      client.garth.post("connectapi", url_path, json=payload)
      return True
    except Exception:
      pass

  return False


def add_workout_to_garmin(workout_text):
  email = os.environ.get("GARMIN_EMAIL")
  password = os.environ.get("GARMIN_PASSWORD")

  if not email or not password:
    print("❌ Błąd: Brak GARMIN_EMAIL lub GARMIN_PASSWORD.")
    sys.exit(1)

  try:
    client = Garmin(email, password)
    client.login(".")
    print("✅ Pomyślnie zalogowano do serwerów Garmin Connect.")

    workout_dict, date_str = parse_simple_text_to_garmin_workout(workout_text)

    workout_id = save_workout_to_garmin(client, workout_dict)
    print(f"✅ Utworzono trening w Garmin Connect. (ID: {workout_id})")

    if workout_id:
      if schedule_workout_on_garmin(client, workout_id, date_str):
        print(f"✅ Przypisano trening do kalendarza na dzień: {date_str}")
      else:
        print("⚠️ Nie udało się przypisać treningu do kalendarza.")

  except Exception as e:
    print(f"❌ Wystąpił błąd: {e}")
    sys.exit(1)


if __name__ == "__main__":
  raw_input = os.environ.get("WORKOUT_PLAN", "")
  add_workout_to_garmin(raw_input)
