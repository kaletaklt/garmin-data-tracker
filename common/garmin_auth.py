"""Logowanie do Garmin Connect z cache tokenów (unika blokady 429 IP Rate Limit)."""
import os

from garminconnect import Garmin

from common.config import GARMIN_EMAIL, GARMIN_PASSWORD

TOKEN_DIR = "/tmp/garmin_tokens"


class GarminAuthenticator:
    def __init__(self):
        self.email = GARMIN_EMAIL
        self.password = GARMIN_PASSWORD
        self.client = None

    def login(self):
        """Loguje użytkownika i zapisuje token sesji w /tmp. Rzuca RuntimeError przy niepowodzeniu."""
        if not self.email or not self.password:
            raise RuntimeError("Brak danych logowania. Skonfiguruj GARMIN_EMAIL i GARMIN_PASSWORD.")

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
            raise RuntimeError(f"Błąd uwierzytelniania Garmin API: {e}") from e
