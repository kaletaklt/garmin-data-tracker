"""Zapis wierszy do Google Sheets (upsert po identyfikatorze)."""
from common.google_auth import get_spreadsheet


class GSheetsUpdater:
    def __init__(self, sheet_name, spreadsheet=None):
        self.sheet = (spreadsheet or get_spreadsheet()).worksheet(sheet_name)

    def upsert_row(self, identifier: str, col_index: int, row_data: list):
        """Aktualizuje wiersz, jeśli identifier (Data/ID) istnieje, w przeciwnym razie dodaje nowy na końcu."""
        try:
            # W gspread 6.0+ find() zwraca None, jeśli komórka nie istnieje
            cell = self.sheet.find(str(identifier), in_column=col_index)
            if cell is None:
                self.sheet.append_row(row_data)
                print(f"Dodano całkowicie nowy wpis dla: {identifier}.")
            else:
                try:
                    self.sheet.update(values=[row_data], range_name=f"A{cell.row}")
                except TypeError:
                    # Fallback dla starszych wersji gspread
                    self.sheet.update(f"A{cell.row}", [row_data])
                print(f"Zaktualizowano istniejący wpis dla: {identifier} (Wiersz {cell.row}).")
        except Exception as e:
            print(f"Błąd podczas zapisu dla {identifier}: {e}")
