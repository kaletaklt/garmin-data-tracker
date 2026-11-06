"""Powiadomienia push na telefon: Join -> Tasker."""
import requests

from common.config import JOIN_API_KEY, JOIN_DEVICE_ID

JOIN_URL = "https://joinjoaomgcd.appspot.com/_ah/api/messaging/v1/sendPush"


def send_join_push(text):
    if not JOIN_API_KEY or not JOIN_DEVICE_ID:
        print(f"Pominięto push Join (brak JOIN_API_KEY / JOIN_DEVICE_ID): {text}")
        return False
    try:
        requests.get(JOIN_URL, params={"apikey": JOIN_API_KEY, "deviceId": JOIN_DEVICE_ID, "text": text}, timeout=10)
        return True
    except Exception as e:
        print(f"Błąd wysyłania push Join: {e}")
        return False


def send_garmin_conflict_alert(date_str, workout_name):
    """Prośba do Taskera o usunięcie treningu z kalendarza Garmin (format oczekiwany przez profil Taskera)."""
    if send_join_push(f"garmin_alert=:={date_str}=:={workout_name}"):
        print(f"Wysłano do Taskera prośbę o usunięcie treningu: {workout_name} ({date_str})")
