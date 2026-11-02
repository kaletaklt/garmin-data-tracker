import os
import sys
from garminconnect import Garmin

TOKEN_DIR = "/tmp/garmin_tokens"


class GarminAuthenticator:
    def __init__(self):
        self.email = os.getenv("GARMIN_EMAIL")
        self.password = os.getenv("GARMIN_PASSWORD")
        self.client = None

    def login(self):
        """Loguje użytkownika i zapisuje token sesji w /tmp, aby uniknąć blokady 429 IP Rate Limit."""
        if not self.email or not self.password:
            raise ValueError("Brak danych logowania. Skonfiguruj GARMIN_EMAIL i GARMIN_PASSWORD.")

        try:
            if os.path.exists(TOKEN_DIR):
                try:
                    print("Wczytywanie zapisanej sesji Garmin Connect...")
                    self.client = Garmin()
                    self.client.login(TOKEN_DIR)
                    print("Pomyślnie wznowiono sesję Garmin.")
                    return self.client
                except Exception:
                    print("Sesja wygasła, logowanie standardowe...")

            print("Nawiązywanie połączenia z Garmin Connect...")
            self.client = Garmin(self.email, self.password)
            self.client.login()
            try:
                self.client.garth.dump(TOKEN_DIR)
            except Exception:
                pass
            print("Pomyślnie zalogowano.")
            return self.client
        except Exception as e:
            print(f"Błąd uwierzytelniania Garmin API: {e}")
            sys.exit(1)
