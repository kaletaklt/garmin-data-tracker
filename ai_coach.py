import os
import re
import json
import datetime
import requests
import gspread

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GEMINI_API_KEY = (os.getenv("GEMINI_LLM_API_KEY") or "").strip()
USER_NOTES = os.getenv("USER_NOTES", "Brak dodatkowych uwag, samopoczucie w normie.")

def get_spreadsheet():
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("Brak zmiennej GSPREAD_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    gc = gspread.service_account_from_dict(creds_dict)
    return gc.open_by_key(SPREADSHEET_ID)

def rows_to_dicts(sheet, max_cols, tail_count):
    """Bezpiecznie zamienia ostatnie wiersze arkusza na listę słowników, ignorując dodatkowe kolumny."""
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        return []
    headers = all_values[0][:max_cols]
    data_rows = all_values[1:][-tail_count:]
    result = []
    for row in data_rows:
        padded = row[:max_cols] + [""] * max(0, max_cols - len(row))
        result.append(dict(zip(headers, padded)))
    return result

def ensure_treningi_headers(treningi_sheet):
    """Upewnia się, że zakładka Treningi ma poprawne nagłówki w wierszu 1 (A1:D1)."""
    expected = ["Data", "Nazwa", "Kod Treningu", "Status"]
    all_values = treningi_sheet.get_all_values()
    if not all_values or all_values[0][:4] != expected:
        print("Naprawianie nagłówków w zakładce 'Treningi'...")
        treningi_sheet.clear()
        treningi_sheet.append_row(expected)
        return []
    return all_values[1:]

def get_best_gemini_model(api_key):
    """Pobiera listę dostępnych modeli dla klucza API i wybiera najlepszy model tekstowy Flash."""
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    resp = requests.get(list_url, timeout=15)
    if not resp.ok:
        raise RuntimeError(f"Błąd pobierania listy modeli Gemini ({resp.status_code}): {resp.text}")
        
    models_data = resp.json().get("models", [])
    available = []
    skip_keywords = ["tts", "image", "embedding", "aqa", "vision", "veo", "imagen", "audio", "robotics"]
    
    for m in models_data:
        name = m.get("name", "")
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods and "gemini" in name.lower():
            if not any(kw in name.lower() for kw in skip_keywords):
                available.append(name)
                
    if not available:
        raise ValueError(f"Brak modeli wspierających generateContent. Zwrócone modele: {[m.get('name') for m in models_data]}")
        
    print(f"Wykryte modele Gemini na kl
