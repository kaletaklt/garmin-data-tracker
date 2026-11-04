import os
import re
import json
import datetime
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

GEMINI_API_KEY = os.getenv("GEMINI_LLM_API_KEY")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", os.getenv("GARMIN_EMAIL", ""))

# Mapowanie kategorii na Twoją paletę kolorów (Google Calendar Event colorId 1-11) oraz ikony
CATEGORY_STYLE = {
    "BASEN":        {"colorId": "1",  "icon": "🏊"},  # Twoja etykieta: Basen
    "CZAS_PRACY":   {"colorId": "2",  "icon": "💻"},  # Twoja etykieta: Czas pracy (Brzoza/Szałwia)
    "ROWER":        {"colorId": "3",  "icon": "🚴"},  # Twoja etykieta: Rower
    "SILOWNIA":     {"colorId": "4",  "icon": "🏋️"},  # Twoja etykieta: Siłownia (Kwiat wiśni)
    "SPOTKANIA":    {"colorId": "5",  "icon": "👥"},  # Twoja etykieta: Spotkania (Cytryna)
    "BIURO":        {"colorId": "6",  "icon": "🏢"},  # Twoja etykieta: Biuro (Kakao)
    "INFORMACYJNE": {"colorId": "8",  "icon": "ℹ️"},  # Twoja etykieta: Informacyjne (Grafit)
    "LEKARZ":       {"colorId": "9",  "icon": "🩺"},  # Lekarz (lub "2" / "10" zależnie od Twojej etykiety)
    "BIEGANIE":     {"colorId": "10", "icon": "🏃"},  # Bieganie (Bazylia)
    "URLOP":        {"colorId": "11", "icon": "✈️"},  # Urlop / Wyjazdy (Pomidor)
}

KNOWN_ICONS = {v["icon"] for v in CATEGORY_STYLE.values()} | {"🧘", "🔥", "⚽"}


def get_calendar_headers():
    creds_json = os.getenv("GSPREAD_CREDENTIALS")
    if not creds_json:
        raise ValueError("Brak zmiennej GSPREAD_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    creds.refresh(Request())
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json"
    }


def rule_based_category(summary, is_self_organizer, my_status, transparency):
    """Szybka kategoryzacja na podstawie słów kluczowych i statusu uczestnictwa."""
    s_low = summary.lower()

    # Cudze wydarzenia ze statusem 'tentative' (Może) lub 'transparent' -> Informacyjne (Grafit)
    if not is_self_organizer and my_status != "accepted":
        return "INFORMACYJNE"
    if any(k in s_low for k in ["terapia", "mecz", "info:", "informacyjnie"]):
        return "INFORMACYJNE"
    if "biuro" in s_low:
        return "BIURO"
    if any(k in s_low for k in ["czas pracy", "praca zdalna", "work", "dyżur"]):
        return "CZAS_PRACY"
    if any(k in s_low for k in ["lekarz", "odczulanie", "dentysta", "badania", "fizjo", "ortopeda", "wizyta dr"]):
        return "LEKARZ"
    if any(k in s_low for k in ["basen", "pływanie", "swim"]):
        return "BASEN"
    if any(k in s_low for k in ["siłownia", "silownia", "gym a", "gym b", "gym c", "trening siłowy", "gym"]):
        return "SILOWNIA"
    if any(k in s_low for k in ["bieg", "run", "interwały", "półmaraton"]):
        return "BIEGANIE"
    if any(k in s_low for k in ["rower", "gravel", "szosa"]):
        return "ROWER"
    if any(k in s_low for k in ["urlop", "wyjazd", "wakacje", "lot ", "rzym"]):
        return "URLOP"
    if any(k in s_low for k in ["spotkanie", "kolacja", "randka", "kino", "urodziny", "kawa", "obiad", "claudia", "kwiatuszek"]):
        return "SPOTKANIA"

    return None


def classify_with_gemini(unclassified_events):
    """Używa Gemini do sklasyfikowania nieoczywistych tytułów spotkań i poprawy ich nazwy."""
    if not GEMINI_API_KEY or not unclassified_events:
        return {}

    prompt = f"""Jesteś asystentem organizującym Kalendarz Google.
Przypisz każde z poniższych wydarzeń do DOKŁADNIE JEDNEJ kategorii z listy:
[LEKARZ, BASEN, INFORMACYJNE, SILOWNIA, CZAS_PRACY, SPOTKANIA, BIURO, BIEGANIE, ROWER, URLOP]

Jeśli nazwa wydarzenia jest chaotyczna (np. pisana z małej litery), zaproponuj czystą, estetyczną nazwę w polu "clean_title" (bez ikony emoji na początku - ikonę doda skrypt).

Wydarzenia do analizy:
{json.dumps(unclassified_events, ensure_ascii=False)}

Zwróć wyłącznie obiekt JSON w formacie:
{{
  "id_wydarzenia": {{"category": "NAZWA_KATEGORII", "clean_title": "Poprawiona nazwa"}}
}}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }

    for model in ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3.5-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code == 200:
                raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
                return json.loads(cleaned)
        except Exception:
            continue
    return {}


def has_category_icon(title):
    return any(title.strip().startswith(ic) for ic in KNOWN_ICONS)


def main():
    if not CALENDAR_ID or "@" not in CALENDAR_ID:
        raise ValueError("Brak poprawnego adresu GOOGLE_CALENDAR_ID / GARMIN_EMAIL.")

    headers = get_calendar_headers()
    now = datetime.datetime.now(datetime.timezone.utc)
    time_min = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max = (now + datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    base_url = f"https://www.googleapis.com/calendar/v3/calendars/{requests.utils.quote(CALENDAR_ID)}/events"
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": 150
    }

    print("Pobieranie wydarzeń z Google Calendar do segregacji...")
    r = requests.get(base_url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("items", [])

    to_ai_classify = []
    planned_updates = {}

    for ev in items:
        ev_id = ev.get("id")
        summary = ev.get("summary", "").strip()
        if not summary or "[AI Coach]" in summary:
            continue

        is_self_organizer = ev.get("organizer", {}).get("self", False)
        if not is_self_organizer:
            # Nie modyfikujemy tytułów cudzych wydarzeń, na które jesteśmy tylko zaproszeni
            continue

        attendees = ev.get("attendees", [])
        my_status = "accepted"
        for att in attendees:
            if att.get("self"):
                my_status = att.get("responseStatus", "accepted")
                break

        transparency = ev.get("transparency", "opaque")
        cat = rule_based_category(summary, is_self_organizer, my_status, transparency)

        if cat:
            planned_updates[ev_id] = {"event": ev, "category": cat, "clean_title": summary}
        elif not has_category_icon(summary):
            to_ai_classify.append({"id": ev_id, "title": summary})

    if to_ai_classify:
        print(f"Klasyfikacja {len(to_ai_classify)} nieoczywistych spotkań przez Gemini AI...")
        ai_results = classify_with_gemini(to_ai_classify)
        for item in to_ai_classify:
            ev_id = item["id"]
            if ev_id in ai_results and ai_results[ev_id].get("category") in CATEGORY_STYLE:
                ev_obj = next(x for x in items if x.get("id") == ev_id)
                planned_updates[ev_id] = {
                    "event": ev_obj,
                    "category": ai_results[ev_id]["category"],
                    "clean_title": ai_results[ev_id].get("clean_title", item["title"])
                }

    updated_count = 0
    for ev_id, info in planned_updates.items():
        ev = info["event"]
        cat = info["category"]
        style = CATEGORY_STYLE[cat]
        target_color = style["colorId"]
        target_icon = style["icon"]

        current_title = ev.get("summary", "").strip()
        clean_title = info["clean_title"].strip()

        # Dodajemy ikonę na początku tytułu, jeśli jeszcze jej nie ma
        if not has_category_icon(current_title):
            new_title = f"{target_icon} {clean_title}"
        else:
            new_title = current_title

        current_color = ev.get("colorId", "")
        if new_title != current_title or current_color != target_color:
            patch_body = {"summary": new_title, "colorId": target_color}
            resp = requests.patch(f"{base_url}/{ev_id}", headers=headers, json=patch_body, timeout=10)
            if resp.status_code == 200:
                updated_count += 1
                print(f"Zaktualizowano: '{current_title}' -> '{new_title}' (Kategoria: {cat}, Kolor: {target_color})")

    print(f"Zakończono porządkowanie kalendarza. Zaktualizowano wydarzeń: {updated_count}.")


if __name__ == "__main__":
    main()
