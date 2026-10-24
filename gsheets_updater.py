import os
import json
import gspread

class GSheetsUpdater:
    def __init__(self, spreadsheet_id, sheet_name="Sheet1"):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.client = self._authenticate()
        # Inicjalizacja konkretnego arkusza już na starcie
        self.sheet = self.client.open_by_key(self.spreadsheet_id).worksheet(self.sheet_name)

    def _authenticate(self):
        """Uwierzytelnia w Google pobierając dane z GitHub Secrets w postaci stringa JSON."""
        creds_json = os.getenv("GSPREAD_CREDENTIALS")

        if not creds_json:
            raise ValueError("Brak poświadczeń. Upewnij się, że zmienna GSPREAD_CREDENTIALS jest ustawiona w YML.")

        try:
            creds_dict = json.loads(creds_json)
            client = gspread.service_account_from_dict(creds_dict)
            return client
        except Exception as e:
            print(f"Błąd autoryzacji Google Sheets: {e}")
            raise e

    def get_existing_identifiers(self, col_index=1):
        """Pobiera listę unikalnych wartości (Daty lub ID) z zadanej kolumny, by unikać duplikatów."""
        try:
            return self.sheet.col_values(col_index)
        except Exception as e:
            print(f"Błąd pobierania istniejących danych z kolumny {col_index}: {e}")
            return []

    def append_rows(self, rows_data: list):
        """Dopisuje wiele wierszy naraz na końcu wybranego arkusza."""
        if not rows_data:
            print(f"Brak nowych danych do zapisu w arkuszu {self.sheet_name}.")
            return
            
        try:
            self.sheet.append_rows(rows_data)
            print(f"Pomyślnie dodano {len(rows_data)} nowych wierszy do arkusza {self.sheet_name}.")
        except Exception as e:
            print(f"Błąd podczas zapisu do arkusza: {e}")
