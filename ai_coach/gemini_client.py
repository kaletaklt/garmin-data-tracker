"""Klient LLM i generator kroczącego planu 7-dniowego (TODO-05)."""
import json
import re
import time

import requests

from common.config import GEMINI_API_KEY


def clean_empty_values(data):
    if isinstance(data, list):
        return [clean_empty_values(v) for v in data]
    if isinstance(data, dict):
        return {k: clean_empty_values(v) for k, v in data.items() if v not in ["", None, [], {}]}
    return data


def get_dynamic_high_end_models():
    excluded = [
        "lite", "gemma", "tts", "image", "vision", "embedding",
        "transcribe", "robotics", "lyria", "banana", "computer-use",
        "customtools", "clip", "nano", "antigravity", "deep-research", "omni",
    ]
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        models_data = r.json().get("models", [])
        scored = []

        for m in models_data:
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            name = m["name"].replace("models/", "")
            n_low = name.lower()

            if not n_low.startswith("gemini-"):
                continue
            if any(bad in n_low for bad in excluded):
                continue

            ver_match = re.search(r"gemini-(\d+(?:\.\d+)?)", n_low)
            if ver_match:
                version = float(ver_match.group(1))
                if version < 3.0:
                    continue
            else:
                version = 3.5

            if "argon" in n_low or "ultra" in n_low:
                tier = 4
            elif "pro" in n_low:
                tier = 3
            elif "flash" in n_low:
                tier = 2
            else:
                tier = 1

            is_stable = 0 if ("preview" in n_low or "exp" in n_low) else 1
            scored.append(((tier, version, is_stable), name))

        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = [name for _, name in scored]
        if ranked:
            return ranked
    except Exception as e:
        print(f"Błąd pobierania katalogu modeli: {e}")

    return ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-flash-latest", "gemini-3.5-flash"]


def parse_json_response(raw_text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned)


def ask_holistic_7day_coach(context_payload, horizon_days):
    if not GEMINI_API_KEY:
        raise ValueError("Brak klucza GEMINI_LLM_API_KEY!")

    compact_context = clean_empty_values(context_payload)

    prompt = f"""Jesteś elitarnym, holistycznym trenerem personalnym AI (bieganie długodystansowe, przygotowanie siłowe Gym A/B, gravel, basen) prowadzącym zawodnika długofalowo.

ZADANIE (TODO-05 + TODO-06):
1. Przeanalizuj raport wykonania ostatnich treningów (`audyt_wykonania_planu_TODO_06`), trendy HRV/RHR/Snu, wskaźniki CTL/ATL/ACWR, plan mezocykli z `Cele_i_Strategia` oraz grafik w Google Calendar i kalendarzu Garmin.
2. Zaplanuj lub zaadaptuj KROCZĄCY PLAN 7-DNIOWY dla następujących dat:
{json.dumps(horizon_days, ensure_ascii=False)}

PEŁNY KONTEKST ZAWODNIKA (JSON):
{json.dumps(compact_context, ensure_ascii=False)}

BEZWZGLĘDNE WYTYCZNE TRENERSKIE:
1. STABILNOŚĆ PLANU VS ADAPTACJA:
   - Jeśli na dany dzień w `obecnie_zaplanowane_7_dni` istnieje już trening i nie koliduje on z nowym wydarzeniem w kalendarzu, a regeneracja (HRV/Sen) oraz uwagi zawodnika są w normie -> ZACHOWAJ dotychczasową koncepcję i parametry tego dnia, aby nie zmieniać planu bez powodu.
   - Jeśli jednak w kalendarzu pojawiła się kolizja (np. wpisana siłownia `Gym B` w piątek lub `Gym A` w poniedziałek), spadło HRV lub wczoraj pominięto jednostkę -> ZAADAPTUJ rozkład dni w tygodniu!
2. BIEGI SPOKOJNE NA TĘTNO (BPM), AKCENTY NA TEMPO (MIN/KM):
   - Dla WSZYSTKICH biegów spokojnych (Easy Run, Bieg Tlenowy, Recovery, spokojny Long Run) oraz dla rozgrzewek (`warmup`) i schłodzeń (`cooldown`) ZAWSZE podawaj cel jako ZAKRES TĘTNA w formacie `XXX-YYYbpm` (np. `warmup, 1km, 115-132bpm`, `interval, 4km, 125-145bpm`, `cooldown, 1km, 115-132bpm`). NIGDY nie podawaj tempa min/km dla biegów spokojnych!
   - Wyłącznie dla biegów jakościowych (Tempo HM, Próg, Interwały VO2max, Przebieżki) podawaj w odcinkach głównych (`interval`) widełki tempa `M:SS-M:SS` (np. `interval, 2km, 4:10-4:20`).
3. SZTYWNA SIŁOWNIA Z KALENDARZA I ZASADA MAX 3 DNI TRENINGOWYCH Z RZĘDU (NAJWAŻNIEJSZE!):
   - Zawodnik sam wpisuje sobie do kalendarza sesje siłowe (`Gym A`, `Gym B` - umówione z dziewczyną) lub inne treningi niebiegowe. Te dni masz podane w polu `sztywne_dni_silowni_z_kalendarza`. Są one NIENARUSZALNE – w te dni zawsze planuj tę siłownię (`steps: "REST"`), nigdy bieg.
   - NADRZĘDNA ZASADA WSZYSTKIEGO: NIGDY NIE PLANUJ WIĘCEJ NIŻ 3 DNI TRENINGOWE Z RZĘDU (wliczając w to bieganie, siłownię, rower i basen)!
   - Jeżeli wypadałby 4. dzień treningowy z rzędu (lub gdyby zaplanowanie biegu sprawiło, że kolejnego dnia sztywna siłownia z kalendarza stałaby się 4. dniem z rzędu), automatycznie wstaw w ten dzień pełny odpoczynek: `workout_name: "Dzień Regeneracji (Rest Day)"` oraz `steps: "REST"`.
4. SKŁADNIA PARSERA GARMINA (DLA DNI BIEGOWYCH):
   Każdy krok w osobnej linii zaczynający się od: `warmup`, `interval`, `recovery`, `cooldown`. Bez zapisu pętli typu "4x" (rozpisz każde powtórzenie w osobnej linii).

Zwróć odpowiedź WYŁĄCZNIE jako czysty obiekt JSON w formacie:
{{
  "weekly_strategy_summary": "Krótkie podsumowanie strategii na najbliższe 7 dni oraz wnioski z audytu ostatnich treningów (2-3 zdania)",
  "seven_day_plan": [
    {{
      "date": "YYYY-MM-DD",
      "workout_name": "Krótka nazwa treningu",
      "steps": "wieloliniowy kod kroków dla Garmina LUB słowo REST",
      "coach_memory_note": "Zwięzłe uzasadnienie jednostki na ten dzień (1-2 zdania)"
    }}
  ]
}}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    active_models = get_dynamic_high_end_models()
    permanently_blocked = set()

    max_wait_seconds = 900
    start_time = time.time()
    round_num = 1

    while (time.time() - start_time) < max_wait_seconds:
        models_to_try = [m for m in active_models if m not in permanently_blocked]
        if not models_to_try:
            permanently_blocked.clear()
            models_to_try = list(active_models)

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            print(f"[Runda {round_num}] Generowanie 7-dniowego planu przez model: {model_name}...")

            try:
                response = requests.post(url, json=payload, timeout=120)
                if response.status_code == 200:
                    data = response.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = parse_json_response(raw_text)
                    print(f"SUKCES! Plan 7-dniowy wygenerowany przez model: {model_name}.")
                    return parsed
                elif response.status_code == 429:
                    if "limit: 0" in response.text or "limit:0" in response.text:
                        permanently_blocked.add(model_name)
                elif response.status_code in [400, 404]:
                    permanently_blocked.add(model_name)
                elif response.status_code in [500, 502, 503, 504]:
                    time.sleep(6)
            except Exception as e:
                print(f"Błąd przy modelu {model_name}: {e}")

        time.sleep(min(15 * round_num, 45))
        round_num += 1

    raise RuntimeError("Przekroczono limit oczekiwania na odpowiedź modeli Gemini.")
