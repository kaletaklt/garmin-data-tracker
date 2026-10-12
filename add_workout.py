import json
import os
import sys
from garminconnect import Garmin


def parse_simple_text_to_garmin_workout(text_input):
  """Tłumaczy prosty tekst z pop-upu na strukturę wymaganą przez Garmin API.

  Automatycznie obsługuje zarówna prawdziwe przejścia do nowej linii, jak i
  eskapowane znaki '\\n' przesłane przez JSON/HTTP Shortcuts.
  """
  if not text_input or not text_input.strip():
    raise ValueError('Przekazano pusty tekst treningu.')

  # Normalizacja znaków nowej linii oraz cudzysłowów z JSON
  text_input = text_input.replace('\\n', '\n').strip()
  if (text_input.startswith('"') and text_input.endswith('"')) or (
      text_input.startswith("'") and text_input.endswith("'")
  ):
    text_input = text_input[1:-1].strip()
    text_input = text_input.replace('\\n', '\n')

  lines = [line.strip() for line in text_input.split('\n') if line.strip()]

  if len(lines) < 3:
    raise ValueError(
        f'Za mało linii w opisie treningu (wykryto {len(lines)} lines).'
        ' Wymagane min. 3 linie: Data, Nazwa, Kroki.\nOtrzymana'
        f' treść:\n{repr(text_input)}'
    )

  date_str = lines[0]
  workout_name = lines[1]

  workout_dict = {
      'workoutName': workout_name,
      'sport': 'RUNNING',
      'workoutSegments': [{
          'segmentOrder': 1,
          'sport': 'RUNNING',
          'workoutSteps': [],
      }],
  }

  step_order = 1
  for line in lines[2:]:
    if line.startswith('-'):
      parts = line[1:].strip().split()
      if len(parts) >= 2:
        dist_str = parts[0].replace('km', '')
        target_str = parts[1]

        try:
          distance_meters = int(float(dist_str) * 1000)
        except ValueError:
          continue

        step = {
            'type': 'ExecutableStepDTO',
            'stepId': None,
            'stepOrder': step_order,
            'childStepId': None,
            'description': target_str,
            'stepType': {
                'stepTypeId': 3,  # Active / Interval
                'stepTypeKey': 'interval',
            },
            'endCondition': {
                'conditionTypeId': 3,  # Distance
                'conditionTypeKey': 'distance',
            },
            'endConditionValue': distance_meters,
        }
        workout_dict['workoutSegments'][0]['workoutSteps'].append(step)
        step_order += 1

  return workout_dict, date_str


def add_workout_to_garmin(workout_text):
  email = os.environ.get('GARMIN_EMAIL')
  password = os.environ.get('GARMIN_PASSWORD')

  if not email or not password:
    print(
        '❌ Błąd: Brak GARMIN_EMAIL lub GARMIN_PASSWORD w sekretach GitHub'
        ' Actions.'
    )
    sys.exit(1)

  try:
    client = Garmin(email, password)
    client.login('.')
    print('✅ Pomyślnie zalogowano do serwerów Garmin Connect.')

    workout_dict, date_str = parse_simple_text_to_garmin_workout(workout_text)

    saved_workout = client.save_workout(workout_dict)
    workout_id = saved_workout.get('workoutId')
    print(f'✅ Utworzono trening w Garmin Connect. (ID: {workout_id})')

    client.schedule_workout(workout_id, date_str)
    print(f'✅ Przypisano trening do kalendarza na dzień: {date_str}')

  except Exception as e:
    print(f'❌ Wystąpił błąd podczas dodawania treningu do Garmina: {e}')
    sys.exit(1)


if __name__ == '__main__':
  raw_input = os.environ.get('WORKOUT_PLAN', '')
  add_workout_to_garmin(raw_input)
