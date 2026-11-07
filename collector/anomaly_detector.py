"""
Detektor nieprawidłowości (anomalii) w ankietach subiektywnych oraz statystykach z zegarka.
Decyduje, czy po zebraniu danych należy uruchomić pełne przeplanowanie w ai_coach.
"""
import datetime

from common.config import ACTIVITY_COLS, SHEET_ACTIVITIES, SHEET_TRAININGS, SHEET_WELLNESS, WELLNESS_COLS
from common.workout_parser import is_rest_code, planned_distance_km

NEUTRAL_VALUES = {
    "", "brak", "nie", "0", "ok", "norma",
    "brak dolegliwości", "brak dolegliwosci",
    "wszystko świeże", "wszystko swieze"
}
DEFAULT_NOTES = {
    "",
    "brak",
    "samopoczucie w normie, brak dolegliwości.",
    "samopoczucie w normie, brak dolegliwosci.",
    "brak dodatkowych uwag, samopoczucie w normie.",
}


def _to_float(val):
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", ".").strip())
    except ValueError:
        return None


def detect_subjective_anomalies(sub):
    """Sprawdza ankietę poranną lub potreningową pod kątem odchyleń wymagających adaptacji planu."""
    reasons = []

    energy = _to_float(sub.get("energy"))
    if energy is not None and energy <= 2:
        reasons.append(f"Niska energia poranna ({int(energy)}/5)")

    rpe = _to_float(sub.get("rpe"))
    if rpe is not None and rpe >= 9:
        reasons.append(f"Bardzo wysokie RPE po treningu ({int(rpe)}/10)")

    pain = str(sub.get("pain", "")).strip()
    if pain.lower() not in NEUTRAL_VALUES:
        reasons.append(f"Zgłoszony dyskomfort/kontuzja: {pain}")

    doms = str(sub.get("doms", "")).strip()
    if doms.lower() not in NEUTRAL_VALUES and "lekki" not in doms.lower():
        reasons.append(f"Zgłoszona bolesność mięśniowa DOMS: {doms}")

    note = str(sub.get("note", "")).strip()
    if note.lower() not in DEFAULT_NOTES:
        reasons.append(f"Nowa uwaga od zawodnika: {note}")

    return reasons


def detect_wellness_anomalies(spreadsheet):
    """Porównuje dzisiejszy odczyt Wellness z bazą 60-dniową (HRV, RHR, Sen, Body Battery)."""
    reasons = []
    try:
        rows = spreadsheet.worksheet(SHEET_WELLNESS).get_all_values()
    except Exception as e:
        print(f"Nie udało się odczytać {SHEET_WELLNESS} do detekcji anomalii: {e}")
        return reasons

    if len(rows) < 2:
        return reasons

    headers = rows[0][:WELLNESS_COLS]
    data_rows = rows[1:]
    today = datetime.date.today()

    hrv_60, rhr_60 = [], []
    latest_dict = None

    for r in data_rows[-90:]:
        padded = r[:WELLNESS_COLS] + [""] * max(0, WELLNESS_COLS - len(r))
        d = dict(zip(headers, padded))
        try:
            dt = datetime.date.fromisoformat(str(d.get("Data", "")).strip())
        except ValueError:
            continue
        days_ago = (today - dt).days
        if 1 <= days_ago <= 60:
            hrv = _to_float(d.get("HRV_rMSSD"))
            rhr = _to_float(d.get("Tetno_Spoczynkowe"))
            if hrv:
                hrv_60.append(hrv)
            if rhr:
                rhr_60.append(rhr)
        if days_ago == 0:
            latest_dict = d

    if not latest_dict:
        return reasons

    today_hrv = _to_float(latest_dict.get("HRV_rMSSD"))
    hrv_status = str(latest_dict.get("HRV_Status", "")).strip().upper()
    today_rhr = _to_float(latest_dict.get("Tetno_Spoczynkowe"))
    sleep_score = _to_float(latest_dict.get("Sen_Wynik"))
    bb_max = _to_float(latest_dict.get("BodyBattery_Max"))

    if hrv_status in {"UNBALANCED", "LOW", "POOR"}:
        reasons.append(f"Status HRV z zegarka: {hrv_status}")

    if today_hrv and len(hrv_60) >= 7:
        base_hrv = sum(hrv_60) / len(hrv_60)
        if today_hrv < base_hrv * 0.88:
            reasons.append(f"Spadek HRV ({today_hrv:.0f} ms vs baza 60d {base_hrv:.1f} ms)")

    if today_rhr and len(rhr_60) >= 7:
        base_rhr = sum(rhr_60) / len(rhr_60)
        if today_rhr >= base_rhr + 5:
            reasons.append(f"Podwyższone tętno spoczynkowe RHR ({today_rhr:.0f} bpm vs baza 60d {base_rhr:.1f} bpm)")

    if sleep_score is not None and sleep_score < 60:
        reasons.append(f"Niski wynik snu ({int(sleep_score)}/100)")

    if bb_max is not None and bb_max < 50:
        reasons.append(f"Niskie naładowanie Body Battery rano ({int(bb_max)}/100)")

    return reasons


def detect_plan_or_execution_anomalies(spreadsheet):
    """
    Sprawdza:
    1. Czy w zakładce Treningi brakuje planu na dowolny z kolejnych 7 dni.
    2. Czy dzisiejsza zarejestrowana aktywność odbiega od planu (np. bieg w dzień REST lub odchylenie dystansu >25%).
    """
    reasons = []
    today = datetime.date.today()
    today_str = today.isoformat()

    try:
        t_rows = spreadsheet.worksheet(SHEET_TRAININGS).get_all_values()
    except Exception:
        return ["Brak zakładki Treningi – wymagane wygenerowanie planu"]

    planned_by_date = {}
    for r in t_rows[1:]:
        if r and r[0].strip():
            planned_by_date[r[0].strip()] = {
                "name": r[1].strip() if len(r) > 1 else "",
                "code": r[2].strip() if len(r) > 2 else "",
                "status": r[3].strip() if len(r) > 3 else "",
            }

    missing_horizon = [
        (today + datetime.timedelta(days=offset)).isoformat()
        for offset in range(1, 8)
        if (today + datetime.timedelta(days=offset)).isoformat() not in planned_by_date
    ]
    if missing_horizon:
        reasons.append(f"Brak zaplanowanych dni w horyzoncie 7-dniowym ({len(missing_horizon)} dni)")

    # Sprawdzenie dzisiejszego wykonania względem planu
    if today_str in planned_by_date:
        plan = planned_by_date[today_str]
        try:
            a_rows = spreadsheet.worksheet(SHEET_ACTIVITIES).get_all_values()
        except Exception:
            a_rows = []

        if len(a_rows) > 1:
            a_headers = a_rows[0][:ACTIVITY_COLS]
            today_acts = []
            for r in a_rows[1:]:
                padded = r[:ACTIVITY_COLS] + [""] * max(0, ACTIVITY_COLS - len(r))
                act = dict(zip(a_headers, padded))
                if str(act.get("Data", "")).strip() == today_str:
                    today_acts.append(act)

            if today_acts:
                is_planned_run = not is_rest_code(plan["code"])
                runs = [a for a in today_acts if "running" in str(a.get("Typ", "")).lower()]
                if is_planned_run and not runs:
                    reasons.append(f"W dniu planowanego biegu ({plan['name']}) zarejestrowano inną aktywność")
                elif is_planned_run and runs:
                    act_km = sum(_to_float(r.get("Dystans_Km")) or 0.0 for r in runs)
                    plan_km = planned_distance_km(plan["code"])
                    if plan_km > 0:
                        ratio = act_km / plan_km
                        if ratio < 0.75 or ratio > 1.35:
                            reasons.append(f"Odchylenie dystansu biegu od planu ({act_km:.1f} km vs plan {plan_km:.1f} km)")
                elif not is_planned_run and runs:
                    reasons.append(f"Wykonano niezaplanowany bieg w dniu bez biegania ({plan['name']})")

    return reasons


def evaluate_replan_need(spreadsheet, sub):
    """
    Zwraca (should_replan: bool, reasons: list[str]).
    Obsługuje tryb TRIGGER_REPLAN:
    - 'false' / '0' / 'no' -> nigdy nie uruchamia replanu
    - 'true' / '1' / 'force' -> wymusza replan jeśli wykryto jakąkolwiek nieprawidłowość lub brakujące dni (albo na żądanie)
    - 'auto' (domyślny) -> uruchamia replan wyłącznie przy wykryciu nieprawidłowości w ankietach, statystykach lub brakach planu
    """
    mode = str(sub.get("trigger_replan", "auto")).strip().lower()
    if mode in {"false", "0", "no"}:
        return False, ["Replan wyłączony parametrem TRIGGER_REPLAN=false"]

    reasons = []
    reasons.extend(detect_subjective_anomalies(sub))
    reasons.extend(detect_wellness_anomalies(spreadsheet))
    reasons.extend(detect_plan_or_execution_anomalies(spreadsheet))

    if mode in {"force", "always"} and not reasons:
        reasons.append("Wymuszono pełny replan (TRIGGER_REPLAN=force)")

    return bool(reasons), reasons
