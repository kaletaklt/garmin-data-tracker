import json
import os
import re
import sys
from garminconnect import Garmin


def parse_simple_text_to_garmin_workout(text_input):
  """Tłumaczy opis treningu na strukturę Garmin API.

  Obsługuje zarówno wpisy wielowierszowe, jak i jednoliniowe spłaszczone przez
  formularz WWW / HTTP Shortcuts.
  """
  if not text_input or not text_input.strip():
    raise ValueError('Przekazano pusty tekst treningu.')

  text_input = text_input.strip()
  if (text_input.startswith('"') and text_input.endswith('"')) or (
      text_input.startswith("'") and text_input.endswith("'")
  ):
    text_input = text_input[1:-1].strip()

  text_input = text_input.replace('\\n', '\n')

  lines = [l.strip() for l in text_input.split('\n') if l.strip()]

  # Obsługa jednoliniowego wejścia z formularza WWW / HTTP Shortcuts
  if len(lines) == 1:
    single_line = lines[0]
    date_match = re.match(r'^(\d{4}-\d{2}-\d{2})\s+(.*)', single_line)
    if date_match:
      date_str = date_match.group(1)
      rest = date_match.group(2)

      parts = re.split(r'\s+-\s+|\s+-', rest)
      workout_name = parts[0].strip()
      step_lines = [f'- {p.strip()}' for p in parts[1:] if p.strip()]

      lines = [date_str, workout_name] + step_lines

  if len(lines) < 3:
    raise ValueError(
        f'Za mało linii/kroków w opisie treningu (wykryto {len(lines)}'
        ' elementów).\nWymagane min. 3: Data, Nazwa, Kroki.\nOtrzymana'
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
                'stepTypeId': 3,
                'stepTypeKey': 'interval',
            },
            'endCondition': {
                'conditionTypeId': 3,
                'conditionTypeKey': 'distance',
            },
            'endConditionValue': distance_meters,
        }
        workout_dict['workoutSegments'][0]['workoutSteps'].append(step)
        step_order += 1

  return workout_dict, date_str


def save_workout_to_garmin(client, workout_dict):
  """Tworzy trening w Garmin Connect przy użyciu endpointu /workout-service/workout."""
  url_path = '/workout-service/workout'

  # 1. Próba przez client.connectapi(..., json=...)
  try:
    res = client.connectapi(url_path, json=workout_dict)
    if isinstance(res, dict) and (res.get('workoutId') or res.get('id')):
      return res.get('workoutId') or res.get('id')
  except Exception as e:
    print(f'⚠️ connectapi(json=...) note: {e}')

  # 2. Próba przez client.connectapi(..., post=...)
  try:
    res = client.connectapi(url_path, post=workout_dict)
    if isinstance(res, dict) and (res.get('workoutId') or res.get('id')):
      return res.get('workoutId') or res.get('id')
  except Exception as e:
    print(f'⚠️ connectapi(post=...) note: {e}')

  # 3. Próba bezpośrednio przez garth
  try:
    if hasattr(client, 'garth'):
      res = client.garth.post(
          'workout-service', url_path, json=workout_dict
      ).json()
      if isinstance(res, dict) and (res.get('workoutId') or res.get('id')):
        return res.get('workoutId') or res.get('id')
  except Exception as e:
    print(f'⚠️ garth.post note: {e}')

  raise RuntimeError(
      'Nie udało się utworzyć treningu w Garmin Connect (wszystkie metody'
      ' zapytania API zawiodły).'
  )


def schedule_workout_on_garmin(client, workout_id, date_str):
  """Przypisuje utwór w kalendarzu Garmin Connect do wyznaczonego dnia."""
  url_path = f'/workout-service/schedule/{workout_id}'
  payload = {'date': date_str}

  try:
    client.connectapi(url_path, json=payload)
    return True
  except Exception:
    pass

  try:
    client.connectapi(url_path, post=payload)
    return True
  except Exception:
    pass

  try:
    if hasattr(client, 'garth'):
      client.garth.post('workout-service', url_path, json=payload)
      return True
  except Exception as e:
    print(f'⚠️ Błąd przypisywania do kalendarza: {e}')

  return False


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

    workout_id = save_workout_to_garmin(client, workout_dict)
    print(f'✅ Utworzono trening w Garmin Connect. (ID: {workout_id})')

    if workout_id:
      if schedule_workout_on_garmin(client, workout_id, date_str):
        print(f'✅ Przypisano trening do kalendarza na dzień: {date_str}')
      else:
        print(
            f'⚠️ Utworzono trening (ID: {workout_id}), ale nie udało się go'
            ' przypisać do kalendarza.'
        )
    else:
      print('⚠️ Nie udało się odczytać ID utworzonego treningu.')

  except Exception as e:
    print(f'❌ Wystąpił błąd podczas dodawania treningu do Garmina: {e}')
    sys.exit(1)


if __name__ == '__main__':
  raw_input = os.environ.get('WORKOUT_PLAN', '')
  add_workout_to_garmin(raw_input)
