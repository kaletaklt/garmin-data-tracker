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


def safe_num(val, scale=1.0, divisor=1.0, round_digits=2):
  """Bezpieczne przeliczanie wartości numerycznych z ochroną przed None."""
  if isinstance(val, (int, float)) and val > 0:
    res = (val / divisor) * scale
    return round(res, round_digits) if round_digits is not None else res
  return None


def collect_activities():
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
  start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH)

  print(f'Pobieranie aktywności od {start_date} do {end_date}...')
  try:
    activities_summary = (
        client.get_activities_by_date(
            start_date.isoformat(), end_date.isoformat(), ''
        )
        or []
    )
  except Exception as e:
    print(f'❌ Błąd pobierania listy aktywności: {e}')
    activities_summary = []

  rows = []
  for summary in activities_summary:
    if not isinstance(summary, dict):
      continue

    act_id = summary.get('activityId')
    if not act_id:
      continue

    try:
      act = client.get_activity(act_id) or summary
    except Exception as e:
      print(f'⚠️ Nie udało się pobrać szczegółów aktywności {act_id}: {e}')
      act = summary

    if not isinstance(act, dict):
      act = summary if isinstance(summary, dict) else {}

    balance = act.get('avgLeftGroundContactBalance') or act.get('avgLeftBalance')
    if isinstance(balance, (int, float)):
      balance = round(balance, 1)
    else:
      balance = None

    record = {
        'ID_Aktywnosci': str(act_id),
        'Data': str(act.get('startTimeLocal', ''))[:10],
        'Godzina': str(act.get('startTimeLocal', ''))[11:16],
        'Nazwa': act.get('activityName'),
        'Typ': safe_nested_get(act, 'activityType', 'typeKey')
        or safe_nested_get(summary, 'activityType', 'typeKey'),
        'Czas_Ruchu_Min': safe_num(
            act.get('movingDuration'), divisor=60, round_digits=2
        ),
        'Dystans_Km': safe_num(
            act.get('distance'), divisor=1000, round_digits=2
        ),
        'Srednie_HR': act.get('averageHR'),
        'Max_HR': act.get('maxHR'),
        'Obciazenie_Treningowe_Load': (
            act.get('activityTrainingLoad')
            or act.get('trainingLoad')
            or summary.get('trainingLoad')
        ),
        'Kalorie': act.get('calories'),
        'Przewyzszenia_W_Gore_m': act.get('elevationGain'),
        'Kadencja_Srednia': act.get('averageRunningCadenceInStepsPerMinute'),
        'Dlugosc_Kroku_m': safe_num(
            act.get('avgStrideLength'), divisor=100, round_digits=2
        ),
        'Czas_Kontaktu_z_Podlozem_ms': act.get('avgGroundContactTime'),
        'Odchylenie_Pionowe_mm': safe_num(
            act.get('avgVerticalOscillation'),
            scale=10.0,
            divisor=1.0,
            round_digits=1,
        ),
        'Srednia_Moc_Biegowa_W': act.get('avgPower') or act.get('averagePower'),
        'VO2_Max_Treningu': act.get('vO2MaxValue'),
        'Balans_L_P': balance,
    }
    rows.append(record)

  with open('activities_data.json', 'w', encoding='utf-8') as f:
    json.dump(rows, f, ensure_ascii=False, indent=4)
  print(
      f'✅ Pomyślnie zapisano {len(rows)} aktywności do activities_data.json.'
  )


if __name__ == '__main__':
  collect_activities()
