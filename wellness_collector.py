import datetime
import json
import os
from garminconnect import Garmin

DAYS_TO_FETCH = 10


def safe_nested_get(d, *keys, default=None):
  """Bezpiecznie wyciąga wartości z głęboko zagnieżdżonych słowników."""
  curr = d
  for k in keys:
    if not isinstance(curr, dict):
      return default
    curr = curr.get(k)
    if curr is None:
      return default
  return curr


def to_hours(seconds):
  if isinstance(seconds, (int, float)) and seconds > 0:
    return round(seconds / 3600, 2)
  return None


def to_minutes(seconds):
  if isinstance(seconds, (int, float)) and seconds > 0:
    return round(seconds / 60)
  return None


def collect_wellness():
  email = os.environ.get('GARMIN_EMAIL')
  password = os.environ.get('GARMIN_PASSWORD')

  if not email or not password:
    print('❌ Błąd: Brak danych logowania GARMIN_EMAIL lub GARMIN_PASSWORD.')
    return

  try:
    client = Garmin(email, password)
    client.login('.')
    print('✅ Pomyślnie połączono z Garmin Connect.')
  except Exception as e:
    print(f'❌ Błąd logowania do Garmin Connect: {e}')
    return

  end_date = datetime.date.today()
  start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH - 1)

  rows = []
  curr_date = start_date

  while curr_date <= end_date:
    date_str = curr_date.isoformat()
    print(f'Pobieranie statystyk zdrowotnych dla: {date_str}...')

    try:
      stats = client.get_stats(date_str) or {}
    except Exception as e:
      print(f'⚠️ Nie udało się pobrać stats dla {date_str}: {e}')
      stats = {}

    try:
      sleep_resp = client.get_sleep_data(date_str) or {}
    except Exception as e:
      print(f'⚠️ Nie udało się pobrać sleep dla {date_str}: {e}')
      sleep_resp = {}

    try:
      hrv_resp = client.get_hrv_data(date_str) or {}
    except Exception as e:
      print(f'⚠️ Nie udało się pobrać hrv dla {date_str}: {e}')
      hrv_resp = {}

    try:
      resp_data = client.get_respiration_data(date_str) or {}
      sleep_resp_val = resp_data.get('sleepAvgValue')
    except Exception:
      sleep_resp_val = None

    sleep_score = safe_nested_get(
        sleep_resp, 'dailySleepDTO', 'sleepScores', 'overall', 'value'
    ) or safe_nested_get(sleep_resp, 'sleepScores', 'overall', 'value')
    sleep_sec = safe_nested_get(sleep_resp, 'dailySleepDTO', 'sleepTimeSeconds')
    deep_sec = safe_nested_get(sleep_resp, 'dailySleepDTO', 'deepSleepSeconds')
    light_sec = safe_nested_get(
        sleep_resp, 'dailySleepDTO', 'lightSleepSeconds'
    )
    rem_sec = safe_nested_get(sleep_resp, 'dailySleepDTO', 'remSleepSeconds')
    awake_sec = safe_nested_get(
        sleep_resp, 'dailySleepDTO', 'awakeSleepSeconds'
    )

    record = {
        'Data': date_str,
        'Tetno_Spoczynkowe': stats.get('restingHeartRate'),
        'Tetno_Maksymalne': stats.get('maxHeartRate'),
        'HRV_rMSSD': safe_nested_get(hrv_resp, 'hrvSummary', 'lastNightAvg'),
        'Sen_Wynik': sleep_score,
        'Sen_Godziny': to_hours(sleep_sec),
        'Sen_Gleboki_Min': to_minutes(deep_sec),
        'Sen_Lekki_Min': to_minutes(light_sec),
        'Sen_REM_Min': to_minutes(rem_sec),
        'Sen_Czuwanie_Min': to_minutes(awake_sec),
        'Oddech_Noc_rpm': (
            sleep_resp_val
            or stats.get('sleepingRespiration')
            or stats.get('averageRespirationValue')
        ),
        'BodyBattery_Max': (
            stats.get('bodyBatteryHighestValue')
            or stats.get('highestBodyBatteryValue')
            or stats.get('maxBodyBattery')
        ),
        'BodyBattery_Min': (
            stats.get('bodyBatteryLowestValue')
            or stats.get('lowestBodyBatteryValue')
            or stats.get('minBodyBattery')
        ),
        'Stres_Sredni': stats.get('averageStressLevel'),
        'Kroki': stats.get('totalSteps', 0),
        'Kalorie_Aktywne': stats.get('activeKilocalories', 0),
        'Minuty_Intensywne': stats.get('vigorousIntensityMinutes', 0),
    }
    rows.append(record)
    curr_date += datetime.timedelta(days=1)

  with open('wellness_data.json', 'w', encoding='utf-8') as f:
    json.dump(rows, f, ensure_ascii=False, indent=4)
  print(
      f'✅ Pomyślnie zapisano dane Wellness ({len(rows)} dni) do'
      ' wellness_data.json.'
  )


if __name__ == '__main__':
  collect_wellness()
