import datetime
import json
import os
from garminconnect import Garmin

DAYS_TO_FETCH = 10


def extract_val(d, *keys, nested_dicts=('userDailySummary', 'stats')):
  """Wyciąga wartości z korzenia lub zagnieżdżonych struktur API Garmina."""
  if not isinstance(d, dict):
    return None
  for k in keys:
    if d.get(k) is not None:
      return d.get(k)
  for n_key in nested_dicts:
    sub = d.get(n_key)
    if isinstance(sub, dict):
      for k in keys:
        if sub.get(k) is not None:
          return sub.get(k)
  return None


def safe_num(val, scale=1.0, divisor=1.0, round_digits=2):
  """Bezpieczne przeliczanie wartości z zabezpieczeniem przed None."""
  if isinstance(val, (int, float)) and val > 0:
    res = (val / divisor) * scale
    return round(res, round_digits) if round_digits is not None else res
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

    daily_sleep = sleep_resp.get('dailySleepDTO') or {}
    sleep_score = (
        daily_sleep.get('sleepScores', {}).get('overall', {}).get('value')
        or sleep_resp.get('sleepScores', {}).get('overall', {}).get('value')
    )

    sleep_sec = daily_sleep.get('sleepTimeSeconds') or sleep_resp.get(
        'sleepTimeSeconds'
    )
    deep_sec = daily_sleep.get('deepSleepSeconds') or sleep_resp.get(
        'deepSleepSeconds'
    )
    light_sec = daily_sleep.get('lightSleepSeconds') or sleep_resp.get(
        'lightSleepSeconds'
    )
    rem_sec = daily_sleep.get('remSleepSeconds') or sleep_resp.get(
        'remSleepSeconds'
    )
    awake_sec = daily_sleep.get('awakeSleepSeconds') or sleep_resp.get(
        'awakeSleepSeconds'
    )

    hrv_summary = hrv_resp.get('hrvSummary') or {}

    record = {
        'Data': date_str,
        'Tetno_Spoczynkowe': extract_val(stats, 'restingHeartRate'),
        'Tetno_Maksymalne': extract_val(stats, 'maxHeartRate'),
        'HRV_rMSSD': extract_val(hrv_summary, 'lastNightAvg'),
        'HRV_Status': extract_val(hrv_summary, 'status'),
        'Sen_Wynik': sleep_score,
        'Sen_Godziny': safe_num(sleep_sec, divisor=3600, round_digits=2),
        'Sen_Gleboki_Min': safe_num(deep_sec, divisor=60, round_digits=0),
        'Sen_Lekki_Min': safe_num(light_sec, divisor=60, round_digits=0),
        'Sen_REM_Min': safe_num(rem_sec, divisor=60, round_digits=0),
        'Sen_Czuwanie_Min': safe_num(awake_sec, divisor=60, round_digits=0),
        'SpO2_Srednie': extract_val(stats, 'averageSpO2'),
        'SpO2_Min': extract_val(stats, 'lowestSpO2'),
        'Oddech_Noc_rpm': (
            sleep_resp_val
            or extract_val(
                stats,
                'sleepingRespiration',
                'averageRespirationValue',
                'averageRespiration',
            )
        ),
        'BodyBattery_Max': extract_val(
            stats,
            'bodyBatteryHighestValue',
            'highestBodyBatteryValue',
            'maxBodyBattery',
        ),
        'BodyBattery_Min': extract_val(
            stats,
            'bodyBatteryLowestValue',
            'lowestBodyBatteryValue',
            'minBodyBattery',
        ),
        'Stres_Sredni': extract_val(stats, 'averageStressLevel'),
        'Stres_Czas_Odpoczynku_Min': safe_num(
            extract_val(
                stats,
                'restStressDuration',
                'restStressSeconds',
                'restStressDurationInSeconds',
            ),
            divisor=60,
            round_digits=0,
        ),
        'Stres_Czas_Wysokiego_Min': safe_num(
            extract_val(
                stats,
                'highStressDuration',
                'highStressSeconds',
                'highStressDurationInSeconds',
            ),
            divisor=60,
            round_digits=0,
        ),
        'Kroki': extract_val(stats, 'totalSteps', 'steps') or 0,
        'Piętra_W_Gore': extract_val(stats, 'floorsAscended', 'floors') or 0,
        'Kalorie_Aktywne': extract_val(
            stats, 'activeKilocalories', 'activeCalories'
        )
        or 0,
        'Kalorie_Spoczynkowe': extract_val(
            stats, 'bmrKilocalories', 'restingKilocalories', 'bmrCalories'
        )
        or 0,
        'Minuty_Intensywne': extract_val(
            stats, 'vigorousIntensityMinutes', 'intensityMinutes'
        )
        or 0,
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
