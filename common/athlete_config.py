"""Odczyt wierszy KONFIGURACJA z zakładki Cele_i_Strategia (wspólny dla modułów)."""
from common.config import GOOGLE_CALENDAR_ID, SHEET_GOALS


def load_konfiguracja(spreadsheet):
    try:
        rows = spreadsheet.worksheet(SHEET_GOALS).get_all_values()
    except Exception as e:
        print(f"Nie udało się odczytać {SHEET_GOALS}: {e}")
        return {}
    return {
        r[1].strip(): (r[2].strip() if len(r) > 2 else "")
        for r in rows
        if len(r) > 1 and r[0].strip().upper() == "KONFIGURACJA" and r[1].strip()
    }


def resolve_calendar_id(konfiguracja):
    return konfiguracja.get("Kalendarz_Email") or GOOGLE_CALENDAR_ID
