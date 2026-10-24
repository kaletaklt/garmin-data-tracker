import os
from garminconnect import Garmin

class GarminAuthenticator:
    def __init__(self):
        # Pobieranie danych uwierzytelniających ze zmiennych środowiskowych
        self.email = os.getenv("GARMIN_EMAIL")
        self.password = os.getenv("GARMIN_PASSWORD")
        self.client = None

    def login(self):
        """Loguje użytkownika i zwraca aktywną sesję klienta Garmin."""
        if not self.email or not self.password:
            raise ValueError("Brak danych logowania. Sprawdź zmienne środowiskowe.")

        try:
            self.client = Garmin(self.email, self.password)
            self.client.login()
            print("Pomyślnie zalogowano do Garmin Connect.")
            return self.client
        except Exception as e:
            print(f"Błąd autoryzacji z API Garmin: {e}")
            raise e
