import os
import gspread
from google.oauth2.service_account import Credentials

class GSheetsUpdater:
    def __init__(self, spreadsheet_id, sheet_name="Sheet1"):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.client = self._authenticate()

    def _authenticate(self):
        """Uwierzytelnia w Google za pomocą pliku service account credentials."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        try:
            # Plik credentials.json powinien pochodzić z GitHub Secrets i być zapisany w runnerze
            creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
            client = gspread.authorize(creds)
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
