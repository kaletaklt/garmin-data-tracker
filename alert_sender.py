import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class AlertSender:
    def __init__(self):
        self.sender = os.getenv("EMAIL_SENDER")
        self.password = os.getenv("EMAIL_PASSWORD")
        self.receiver = os.getenv("EMAIL_RECEIVER")

    def send_notification(self, title, message):
        if not all([self.sender, self.password, self.receiver]):
            print("Brak pełnych danych e-mail w zmiennych środowiskowych. Pomijam wysyłanie.")
            return

        msg = MIMEMultipart()
        msg['From'] = self.sender
        msg['To'] = self.receiver
        msg['Subject'] = title
        msg.attach(MIMEText(message, 'plain'))

        try:
            # Domyślne ustawienia dla Gmail / port 587
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.sender, self.password)
            server.send_message(msg)
            server.quit()
            print("Powiadomienie e-mail wysłane pomyślnie.")
        except Exception as e:
            print(f"Błąd wysyłania e-maila: {e}")

if __name__ == "__main__":
    sender = AlertSender()
    sender.send_notification("Raport Garmin", "Pomyślnie zsynchronizowano dane.")
