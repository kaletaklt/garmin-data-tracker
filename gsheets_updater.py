import os
import json
import gspread
from google.oauth2.service_account import Credentials

class GSheetsUpdater:
    def __init__(self, spreadsheet_id, sheet_name="Sheet1"):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.client = self._authenticate()

    def _authenticate(self):
        """Uwierzytelnia w Google za pomocą poświadczeń service account."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        try:
            # 1. Próba wczytania z pliku (lokalne środowisko)
            if os.path.exists("credentials.json"):
                creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
                print("Użyto lokalnego pliku credentials.json")
                
            # 2. Próba wczytania ze zmiennej środowiskowej (GitHub Actions)
            elif "GOOGLE_CREDENTIALS_JSON" in os.environ:
                creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
                creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                print("Użyto poświadczeń ze zmiennej środowiskowej GOOGLE_CREDENTIALS_JSON")
                
            else:
                raise ValueError("Brak poświadczeń. Upewnij się, że plik credentials.json istnieje "
                                 "lub zmienna GOOGLE_CREDENTIALS_JSON jest ustawiona.")

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
