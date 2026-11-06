"""Centralna konfiguracja: zmienne środowiskowe, nazwy zakładek i znaczniki."""
import os

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GEMINI_API_KEY = os.getenv("GEMINI_LLM_API_KEY")
GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")
# Pusty sekret w GitHub Actions daje "", dlatego `or` zamiast domyślnej wartości getenv.
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID") or GARMIN_EMAIL or ""
JOIN_API_KEY = os.getenv("JOIN_API_KEY")
JOIN_DEVICE_ID = os.getenv("JOIN_DEVICE_ID")

TIMEZONE = "Europe/Warsaw"

# Zakładki Google Sheets
SHEET_WELLNESS = "Wellness"
SHEET_ACTIVITIES = "Aktywnosci"
SHEET_TRAININGS = "Treningi"
SHEET_GOALS = "Cele_i_Strategia"
SHEET_SUBJECTIVE = "Dziennik_Subiektywny"

# Liczba "prawdziwych" kolumn (za nimi są formuły MA7/MA30 - zawsze tnij)
WELLNESS_COLS = 24
ACTIVITY_COLS = 25

# Znaczniki w tytułach wydarzeń / treningów
AI_COACH_TAG = "[AI Coach]"   # wydarzenie w Google Calendar będące lustrem treningu z Garmina
GCAL_TAG = "[GCal]"           # trening w Garminie skopiowany z Google Calendar (gym A/B)
