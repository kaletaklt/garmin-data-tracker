import os
import requests

class AlertSender:
    def __init__(self):
        # np. Discord / Slack / Telegram Webhook URL
        self.webhook_url = os.getenv("WEBHOOK_URL")

    def send_notification(self, title, message):
        """Wysyła payload z notyfikacją pod wskazany webhook."""
        if not self.webhook_url:
            print("WEBHOOK_URL nie jest ustawiony, pomijam powiadomienie.")
            return

        payload = {
            "content": f"**{title}**\n{message}"  # Format zgodny m.in. z Discordem
        }

        try:
            response = requests.post(self.webhook_url, json=payload)
            response.raise_for_status()
            print("Powiadomienie zostało wysłane.")
        except Exception as e:
            print(f"Błąd wysyłania powiadomienia: {e}")

def main():
    sender = AlertSender()
    sender.send_notification(
        title="Raport Garmin Data Tracker", 
        message="Workflow zakończony. Dane zostały zsynchronizowane do Google Sheets."
    )

if __name__ == "__main__":
    main()
