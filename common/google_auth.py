"""Jedno miejsce uwierzytelniania kontem usługi Google (Sheets + Calendar)."""
import json
import os

import gspread
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from common.config import SPREADSHEET_ID

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_credentials(scopes):
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("Brak zmiennej GSPREAD_CREDENTIALS")
    return service_account.Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes)


def get_spreadsheet():
    if not SPREADSHEET_ID:
        raise ValueError("Brak zmiennej GOOGLE_SHEET_ID")
    return gspread.authorize(get_credentials(SHEETS_SCOPES)).open_by_key(SPREADSHEET_ID)


def calendar_headers():
    creds = get_credentials(CALENDAR_SCOPES)
    creds.refresh(Request())
    return {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}


def calendar_events_url(calendar_id):
    return f"https://www.googleapis.com/calendar/v3/calendars/{requests.utils.quote(calendar_id)}/events"
