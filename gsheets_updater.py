import os
import json
import gspread
from google.oauth2.service_account import Credentials

def upsert(sheet, data_list, primary_key):
    if not data_list: return
    fieldnames = list(data_list[0].keys())
    existing = sheet.get_all_values()
    
    if not existing:
        sheet.append_row(fieldnames)
        existing_map = {}
    else:
        if len(existing[0]) < len(fieldnames): 
            sheet.update(range_name='A1', values=[fieldnames])
        key_idx = fieldnames.index(primary_key)
        existing_map = {row[key_idx]: i + 1 for i, row in enumerate(existing) if len(row) > key_idx}

    for record in data_list:
        row_vals = [("" if record.get(k) is None else record.get(k)) for k in fieldnames]
        key_val = record.get(primary_key)
        
        if key_val in existing_map:
            sheet.update(range_name=f"A{existing_map[key_val]}", values=[row_vals])
        else:
            sheet.append_row(row_vals)

def update_sheets():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ.get("GSPREAD_CREDENTIALS")), 
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(os.environ.get("GOOGLE_SHEET_ID"))

    if os.path.exists("wellness_data.json"):
        with open("wellness_data.json", "r") as f: data = json.load(f)
        try: sheet = spreadsheet.worksheet("Wellness")
        except: sheet = spreadsheet.add_worksheet(title="Wellness", rows="1000", cols="20")
        upsert(sheet, data, "Data")
        print("Zaktualizowano arkusz Wellness.")

    if os.path.exists("activities_data.json"):
        with open("activities_data.json", "r") as f: data = json.load(f)
        try: sheet = spreadsheet.worksheet("Aktywnosci")
        except: sheet = spreadsheet.add_worksheet(title="Aktywnosci", rows="1000", cols="20")
        upsert(sheet, data, "ID_Aktywnosci")
        print("Zaktualizowano arkusz Aktywności.")

if __name__ == "__main__":
    update_sheets()
