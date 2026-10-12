import datetime
import json
import os
from garminconnect import Garmin

DAYS_TO_FETCH = 10


def extract_val(
    d, summary=None, *keys, nested_dicts=('summaryDTO', 'metadataDTO')
):
  """Przeszukuje powierzchowne oraz głębokie struktury (summaryDTO) szczegółów aktywności."""
  if isinstance(d, dict):
    for k in keys:
      if d.get(k) is not None:
        return d.get(k)
    for n_key in nested_dicts:
      sub = d.get(n_key)
      if isinstance(sub, dict):
        for k in keys:
          if sub.get(k) is not None:
            return sub.get(k)
  if isinstance(summary, dict):
    for k in keys:
      if summary.get(k) is not None:
        return summary.get(k)
  return None


def safe_num(val, scale=1.0, divisor=1.0, round_digits=2):
  """Bezpieczne dzielenie i zaokrąglanie wartości numerycznych."""
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

    balance = extract_val(
        act,
        summary,
        'avgLeftGroundContactBalance',
        'avgLeftBalance',
        'leftBalance',
    )
    if isinstance(balance, (int, float)):
      balance = round(balance, 1)
    else:
      balance = None

    start_time_local = extract_val(act, summary, 'startTimeLocal') or ''

    record = {
        'ID_Aktywnosci': str(act_id),
        'Data': str(start_time_local)[:10],
        'Godzina': str(start_time_local)[11:16],
        'Nazwa': extract_val(act, summary, 'activityName', 'name'),
        'Typ': extract_val(
            act, summary, 'typeKey', nested_dicts=('activityType', 'summaryDTO')
        ),
        'Czas_Ruchu_Min': safe_num(
            extract_val(act, summary, 'movingDuration', 'movingTime'),
            divisor=60,
            round_digits=2,
        ),
        'Czas_Calkowity_Min': safe_num(
            extract_val(
                act, summary, 'elapsedDuration', 'elapsedTime', 'duration'
            ),
            divisor=60,
            round_digits=2,
        ),
        'Dystans_Km': safe_num(
            extract_val(act, summary, 'distance'), divisor=1000, round_digits=2
        ),
        'Srednie_HR': extract_val(
            act, summary, 'averageHR', 'averageHeartRate'
        ),
        'Max_HR': extract_val(act, summary, 'maxHR', 'maxHeartRate'),
        'Efekt_Tlenowy': extract_val(act, summary, 'aerobicTrainingEffect'),
        'Efekt_Beztlenowy': extract_val(
            act, summary, 'anaerobicTrainingEffect'
        ),
        'Obciazenie_Treningowe_Load': extract_val(
            act, summary, 'activityTrainingLoad', 'trainingLoad'
        ),
        'Kalorie': extract_val(act, summary, 'calories'),
        'Przewyzszenia_W_Gore_m': extract_val(act, summary, 'elevationGain'),
        'Przewyzszenia_W_Dol_m': extract_val(act, summary, 'elevationLoss'),
        'Kadencja_Srednia': extract_val(
            act,
            summary,
            'averageRunningCadenceInStepsPerMinute',
            'averageBikingCadenceInRevPerMinute',
            'averageCadence',
        ),
        'Dlugosc_Kroku_m': safe_num(
            extract_val(act, summary, 'avgStrideLength', 'strideLength'),
            divisor=100,
            round_digits=2,
        ),
        'Czas_Kontaktu_z_Podlozem_ms': extract_val(
            act, summary, 'avgGroundContactTime', 'groundContactTime'
        ),
        'Odchylenie_Pionowe_mm': safe_num(
            extract_val(
                act, summary, 'avgVerticalOscillation', 'verticalOscillation'
            ),
            scale=10.0,
            divisor=1.0,
            round_digits=1,
        ),
        'Balans_L_P': balance,
        'Srednia_Moc_W': extract_val(act, summary, 'avgPower', 'averagePower'),
        'Znormalizowana_Moc_W': extract_val(
            act, summary, 'normPower', 'normalizedPower'
        ),
        'VO2_Max_Treningu': extract_val(act, summary, 'vO2MaxValue'),
        'Temperatura_Srednia_C': extract_val(
            act, summary, 'averageTemperature', 'minTemperature'
        ),
    }
    rows.append(record)

  with open('activities_data.json', 'w', encoding='utf-8') as f:
    json.dump(rows, f, ensure_ascii=False, indent=4)
  print(
      f'✅ Pomyślnie zapisano {len(rows)} aktywności do activities_data.json.'
  )


if __name__ == '__main__':
  collect_activities()
