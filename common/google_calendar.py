"""Google Calendar API: odczyt wydarzeń i wspólne reguły interpretacji tytułów."""
import datetime
import re

import requests

from common.google_auth import calendar_events_url, calendar_headers

GYM_KEYWORDS = ("gym", "siłownia", "silownia")


def _rfc3339(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_events(calendar_id, time_min, time_max, headers=None, max_results=250):
    params = {
        "timeMin": _rfc3339(time_min),
        "timeMax": _rfc3339(time_max),
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": max_results,
    }
    r = requests.get(calendar_events_url(calendar_id), headers=headers or calendar_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("items", [])


def delete_event(calendar_id, event_id, headers):
    requests.delete(f"{calendar_events_url(calendar_id)}/{event_id}", headers=headers, timeout=10)


def event_date(ev):
    start = ev.get("start", {})
    return str(start.get("dateTime", start.get("date", "")))[:10]


def my_response_status(ev):
    for att in ev.get("attendees", []):
        if att.get("self"):
            return att.get("responseStatus", "needsAction")
    return "accepted"


def is_relevant_for_me(ev):
    """Własne wydarzenia lub cudze zaakceptowane przeze mnie (np. Terapia 'tentative' jest ignorowana)."""
    return ev.get("organizer", {}).get("self", False) or my_response_status(ev) == "accepted"


def is_gym_title(title):
    s = str(title).lower()
    return any(k in s for k in GYM_KEYWORDS)


def strip_leading_icon(title):
    """'🏋️ Gym A (nogi)' -> 'Gym A (nogi)'"""
    return re.sub(r"^[^\w\[(]+", "", str(title)).strip()
