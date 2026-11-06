"""Kalendarz Garmin Connect: odczyt zaplanowanych treningów, wgrywanie i usuwanie."""
import datetime


def get_calendar_items(client, year, month):
    """Elementy kalendarza Garmin dla miesiąca 1-12 (API Garmina indeksuje miesiące od 0)."""
    data = client.connectapi(f"/calendar-service/year/{year}/month/{month - 1}")
    return data.get("calendarItems", []) if isinstance(data, dict) else []


def _months_between(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def get_workout_details(client, workout_id):
    try:
        return client.connectapi(f"/workout-service/workout/{workout_id}") or {}
    except Exception:
        return {}


def _resolve_sport_key(client, item, cache):
    key = item.get("sportTypeKey") or (item.get("sportType") or {}).get("sportTypeKey")
    if key:
        return str(key).lower()
    wid = item.get("workoutId")
    if not wid:
        return "unknown"
    if wid not in cache:
        details = get_workout_details(client, wid)
        cache[wid] = str((details.get("sportType") or {}).get("sportTypeKey", "unknown")).lower()
    return cache[wid]


def get_planned_workouts(client, start_date, end_date):
    """
    Zaplanowane treningi (itemType == 'workout') w zakresie dat (włącznie).
    Ukończone aktywności (np. wrzucone przez LiftTrack) mają inny itemType i są pomijane.
    Zwraca listę: {date, title, workout_id, sport, is_run}.
    """
    result, seen, sport_cache = [], set(), {}
    for year, month in _months_between(start_date, end_date):
        for item in get_calendar_items(client, year, month):
            if item.get("itemType") != "workout":
                continue
            d_str = str(item.get("date", ""))[:10]
            try:
                d = datetime.date.fromisoformat(d_str)
            except ValueError:
                continue
            if not (start_date <= d <= end_date):
                continue
            key = (item.get("id"), item.get("workoutId"), d_str)
            if key in seen:
                continue
            seen.add(key)
            sport = _resolve_sport_key(client, item, sport_cache)
            result.append({
                "date": d_str,
                "title": str(item.get("title") or ""),
                "workout_id": str(item.get("workoutId") or ""),
                "sport": sport,
                "is_run": "running" in sport,
            })
    return sorted(result, key=lambda w: w["date"])


def group_by_date(workouts):
    grouped = {}
    for w in workouts:
        grouped.setdefault(w["date"], []).append(w)
    return grouped


def upload_and_schedule(client, workout_payload, target_date):
    """Zapisuje trening w bibliotece Garmina i przypisuje go do dnia. Zwraca workoutId (str)."""
    name = workout_payload["workoutName"]
    print(f"Zapisywanie treningu '{name}' w bibliotece Garmina...")
    response = client.upload_workout(workout_payload)

    workout_id = None
    if isinstance(response, dict):
        workout_id = response.get("workoutId")
    elif hasattr(response, "json"):
        try:
            workout_id = response.json().get("workoutId")
        except Exception:
            pass

    if not workout_id:
        print("Brak bezpośredniego zwrotu ID. Szukanie treningu na liście...")
        for w in client.get_workouts() or []:
            if w.get("workoutName") == name:
                workout_id = w.get("workoutId")
                break

    if not workout_id:
        raise ValueError("Serwer przyjął trening, ale nie udało się odzyskać jego ID potrzebnego do kalendarza.")

    client.schedule_workout(workout_id, target_date)
    print(f"Trening '{name}' (ID: {workout_id}) zaplanowany na {target_date}.")
    return str(workout_id)


def delete_workout(client, workout_id):
    client.connectapi(f"/workout-service/workout/{workout_id}", method="DELETE")
    print(f"Usunięto trening z Garmina (ID: {workout_id}).")
