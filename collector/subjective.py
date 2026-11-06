"""Zapis subiektywnych raportów samopoczucia (energia, RPE, DOMS, dyskomfort) do zakładki Dziennik_Subiektywny."""
import datetime
import os

import gspread

from common.config import SHEET_SUBJECTIVE
from common.google_auth import get_spreadsheet

SUBJECTIVE_HEADERS = [
    "Data", "Godzina", "Typ_Raportu", "Energia_Rano_1_5",
    "RPE_Treningu_1_10", "DOMS_Bolesnosc", "Dyskomfort_Kontuzje",
    "Notatka_Glosowa_Tekstowa", "Reakcja_AI_Coach",
]


def ensure_subjective_sheet(spreadsheet):
    try:
        return spreadsheet.worksheet(SHEET_SUBJECTIVE)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=SHEET_SUBJECTIVE, rows=500, cols=9)
        ws.append_row(SUBJECTIVE_HEADERS)
        return ws


def read_subjective_env(default_report_type="Rano_CheckIn"):
    return {
        "report_type": os.getenv("REPORT_TYPE", default_report_type).strip() or default_report_type,
        "energy": os.getenv("ENERGY_1_5", "").strip(),
        "rpe": os.getenv("RPE_1_10", "").strip(),
        "doms": os.getenv("DOMS_INFO", "Brak").strip() or "Brak",
        "pain": os.getenv("PAIN_INFO", "Brak").strip() or "Brak",
        "note": os.getenv("USER_NOTE", "").strip(),
        "trigger_replan": os.getenv("TRIGGER_REPLAN", "auto").strip().lower(),
    }


def has_subjective_payload(sub):
    """Sprawdza, czy użytkownik przekazał jakiekolwiek dane ankietowe (np. z Taskera)."""
    if sub.get("energy") or sub.get("rpe") or sub.get("note"):
        return True
    if sub.get("doms", "Brak").lower() not in ("", "brak"):
        return True
    if sub.get("pain", "Brak").lower() not in ("", "brak"):
        return True
    return False


def format_subjective_context_note(sub, date_str=None, time_str=None):
    now_pl = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1)))
    d_str = date_str or now_pl.strftime("%Y-%m-%d")
    t_str = time_str or now_pl.strftime("%H:%M:%S")
    return (
        f"[{sub['report_type']} {d_str} {t_str}] "
        f"Energia: {sub['energy'] or '-'}/5 | RPE: {sub['rpe'] or '-'}/10 | "
        f"DOMS: {sub['doms']} | Dyskomfort: {sub['pain']} | Uwagi: {sub['note']}"
    )


def log_subjective_entry(spreadsheet, sub, ai_reaction):
    ws = ensure_subjective_sheet(spreadsheet)
    now_pl = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1)))
    date_str = now_pl.strftime("%Y-%m-%d")
    time_str = now_pl.strftime("%H:%M:%S")

    new_row = [
        date_str, time_str, sub["report_type"], sub["energy"],
        sub["rpe"], sub["doms"], sub["pain"], sub["note"], ai_reaction,
    ]
    ws.append_row(new_row)
    print(f"Zapisano raport w {SHEET_SUBJECTIVE}: {new_row}")
    return format_subjective_context_note(sub, date_str, time_str)
