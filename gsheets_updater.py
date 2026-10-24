import os
import json
import gspread

class GSheetsUpdater:
    def __init__(self, spreadsheet_id, sheet_name="Sheet1"):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.client = self._authenticate()
        self.sheet = self.client.open_by_key(self.spreadsheet_id).worksheet(self.sheet_name)

    def _authenticate(self):
        creds_json = os.getenv("GSPREAD_CREDENTIALS")
        if not creds_json:
            raise ValueError("Brak poświadczeń. Upewnij się, że zmienna GSPREAD_CREDENTIALS jest ustawiona.")
        try:
            creds_dict = json.loads(creds_json)
            client = gspread.service_account_from_dict(creds_dict)
            return client
        except Exception as e:
            print(f"Błąd autoryzacji Google Sheets: {e}")
            raise e

    def upsert_row(self, identifier: str, col_index: int, row_data: list):
        """Aktualizuje wiersz jeśli identifier (Data/ID) istnieje, w przeciwnym razie dodaje nowy na końcu."""
        try:
            # Szukamy czy identyfikator już istnieje (np. dzisiejsza data)
            cell = self.sheet.find(str(identifier), in_column=col_index)
            
            # Próba aktualizacji wiersza (obsługa różnych wersji biblioteki gspread)
            try:
                self.sheet.update(values=[row_data], range_name=f"A{cell.row}")
            except TypeError:
                self.sheet.update(f"A{cell.row}", [row_data])
                
            print(f"Zaktualizowano istniejący wpis dla: {identifier} (Wiersz {cell.row}).")
            
        except gspread.exceptions.CellNotFound:
            # Jeśli data/ID nie istnieje - dodajemy nowy wiersz
            self.sheet.append_row(row_data)
            print(f"Dodano całkowicie nowy wpis dla: {identifier}.")
        except Exception as e:
            if "not found" in str(e).lower():
                self.sheet.append_row(row_data)
                print(f"Dodano całkowicie nowy wpis dla: {identifier}.")
            else:
                print(f"Błąd podczas zapisu dla {identifier}: {e}")
