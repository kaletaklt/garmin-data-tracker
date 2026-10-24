import os
import sys
from garminconnect import Garmin

class GarminAuthenticator:
    def __init__(self):
        # Pobiera zmienne środowiskowe skonfigurowane np. w GitHub Actions
        self.email = os.getenv("GARMIN_EMAIL")
        self.password = os.getenv("GARMIN_PASSWORD")
        self.client = None

    def login(self):
        """Loguje użytkownika i zwraca aktywną sesję klienta."""
        if not self.email or not self.password:
            raise ValueError("Brak danych logowania. Skonfiguruj GARMIN_EMAIL i GARMIN_PASSWORD.")

        try:
            print("Nawiązywanie połączenia z Garmin Connect...")
            self.client = Garmin(self.email, self.password)
            self.client.login()
            print("Pomyślnie zalogowano.")
            return self.client
        except Exception as e:
            print(f"Błąd uwierzytelniania Garmin API: {e}")
            sys.exit(1)
