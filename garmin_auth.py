import os
from garminconnect import Garmin

def authenticate_garmin():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    
    if not email or not password:
        print("Błąd: Brak poświadczeń GARMIN_EMAIL lub GARMIN_PASSWORD.")
        exit(1)

    try:
        # session_data_dir="." sprawia, że skrypt zapisuje pliki sesji w głównym folderze
        client = Garmin(email, password, session_data_dir=".")
        client.login()
        print("✅ Pomyślnie zalogowano do serwerów Garmin Connect. Wygenerowano tokeny sesji.")
    except Exception as e:
        print(f"❌ Błąd autoryzacji z Garmin Connect: {e}")
        exit(1)

if __name__ == "__main__":
    authenticate_garmin()
