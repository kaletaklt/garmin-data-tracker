import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_alerts():
    if not os.path.exists("wellness_data.json"): return
    with open("wellness_data.json", "r") as f: data = json.load(f)
    if len(data) < 2: return

    today = data[-1]
    yesterday = data[-2]
    alerts = []

    hrv = today.get("HRV_rMSSD")
    y_hrv = yesterday.get("HRV_rMSSD")
    if hrv and y_hrv and hrv < (y_hrv * 0.85):
        alerts.append(f"⚠️ Spadek HRV z {y_hrv} na {hrv} ms. Układ nerwowy jest przemęczony.")

    rhr = today.get("Tetno_Spoczynkowe")
    y_rhr = yesterday.get("Tetno_Spoczynkowe")
    if rhr and y_rhr and rhr >= (y_rhr + 5):
        alerts.append(f"⚠️ Podwyższone Tętno Spoczynkowe: {rhr} bpm (wzrost z {y_rhr}). Znak zmęczenia/infekcji.")

    if alerts:
        sender, pwd, receiver = os.environ.get("EMAIL_SENDER"), os.environ.get("EMAIL_PASSWORD"), os.environ.get("EMAIL_RECEIVER")
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = sender, receiver, f"🚨 ALERT REGENERACYJNY GARMIN [{today.get('Data')}]"
        msg.attach(MIMEText("Wykryto słabszą regenerację:\n\n" + "\n".join(alerts), 'plain', 'utf-8'))
        
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(sender, pwd)
                s.sendmail(sender, receiver, msg.as_string())
            print("Wysłano alert regeneracyjny.")
        except Exception as e:
            print(f"Błąd wysyłki e-mail: {e}")

if __name__ == "__main__":
    send_alerts()
