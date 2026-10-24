import os
import json
import gspread

class GSheetsUpdater:
    def __init__(self, spreadsheet_id, sheet_name="Sheet1"):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.client = self._authenticate()

    def _authenticate(self):
        """Uwierzytelnia w Google pobierając dane z GitHub Secrets w postaci stringa JSON."""
        creds_json = os.getenv("GSPREAD_CREDENTIALS")

        if not creds_json:
            raise ValueError("Brak poświadczeń. Upewnij się, że zmienna GSPREAD_CREDENTIALS jest ustawiona.")

        try:
            creds_dict = json.loads(creds_json)
            client = gspread.service_account_from_dict(creds_dict)
            print("Połączono z Google Sheets API.")
            return client
        except Exception as e:
            print(f"Błąd autoryzacji Google Sheets: {e}")
            raise e

    def append_data(self, row_data: list):
        """Dopisuje nowy wiersz danych na końcu wybranego arkusza."""
        try:
            sheet = self.client.open_by_key(self.spreadsheet_id).worksheet(self.sheet_name)
            sheet.append_row(row_data)
            print(f"Dane pomyślnie zapisane w arkuszu {self.sheet_name}.")
        except Exception as e:
            print(f"Błąd podczas zapisu do arkusza: {e}")
