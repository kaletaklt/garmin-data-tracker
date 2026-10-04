import os
from garminconnect import Garmin

def login():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    
    if not email or not password:
        print("Brak danych logowania Garmin w Secrets.")
        exit(1)

    try:
        client = Garmin(email, password, session_data_dir=".")
        client.login()
        print("Zalogowano do Garmin Connect.")
    except Exception as e:
        print(f"Błąd logowania: {e}")
        exit(1)

if __name__ == "__main__":
    login()
