import re
import datetime
from coach_analytics import safe_float


# ==============================================================================
# TODO-06: AUTOMATYCZNY AUDYT WYKONANIA TRENINGU (PLAN VS WYKONANIE)
# ==============================================================================
def parse_planned_steps_summary(steps_code):
    if not steps_code or steps_code.strip().upper() == "REST":
        return {"is_run": False, "planned_km": 0.0, "hr_target": None, "pace_target": None}

    total_km = 0.0
    hr_targets = []
    pace_targets = []

    for line in steps_code.splitlines():
        l_strip = line.strip()
        if not any(l_strip.lower().startswith(k) for k in ["warmup", "interval", "recovery", "cooldown"]):
            continue
        m_km = re.search(r"(\d+(?:\.\d+)?)\s*km\b", l_strip, re.IGNORECASE)
        m_m = re.search(r"(\d+)\s*m\b", l_strip, re.IGNORECASE)
        m_hr = re.search(r"(\d+\s*-\s*\d+)\s*bpm", l_strip, re.IGNORECASE)
        m_pace = re.search(r"(\d+:\d{2}\s*-\s*\d+:\d{2})", l_strip)

        if m_km:
            total_km += float(m_km.group(1))
        elif m_m:
            total_km += float(m_m.group(1)) / 1000.0

        if "interval" in l_strip.lower():
            if m_hr:
                hr_targets.append(m_hr.group(1).replace(" ", "") + " bpm")
            if m_pace:
                pace_targets.append(m_pace.group(1).replace(" ", "") + "/km")

    return {
        "is_run": True,
        "planned_km": round(total_km, 2),
        "hr_target": hr_targets[0] if hr_targets else None,
        "pace_target": pace_targets[0] if pace_targets else None
    }


def format_pace_min_km(moving_mins, dist_km):
    if not moving_mins or not dist_km or dist_km <= 0:
        return "brak"
    pace_float = moving_mins / dist_km
    mins = int(pace_float)
    secs = int(round((pace_float - mins) * 60))
    if secs == 60:
        mins += 1
        secs = 0
    return f"{mins}:{secs:02d}/km"


def audit_past_workouts(treningi_sheet, existing_rows, activities_by_date):
    """
    TODO-06: Sprawdza zaplanowane treningi z przeszłości (oraz z dzisiaj, jeśli aktywność już wpadła),
    porównuje je z zakładką 'Aktywnosci' i zapisuje wynik audytu w kolumnach Status i Notatka_Trenera.
    """
    today = datetime.date.today()
    audit_reports = []

    for idx, row in enumerate(existing_rows):
        if len(row) < 4 or not row[0].strip():
            continue
        row_num = idx + 2
        d_str = row[0].strip()
        w_name = row[1].strip() if len(row) > 1 else ""
        w_code = row[2].strip() if len(row) > 2 else ""
        status = row[3].strip() if len(row) > 3 else ""
        coach_note = row[4].strip() if len(row) > 4 else ""

        try:
            w_date = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if w_date > today:
            continue

        # Jeśli wiersz był już wcześniej rozliczony, tylko przekazujemy go do kontekstu AI
        if any(status.startswith(prefix) for prefix in ["Zrealizowane", "Zmodyfikowane", "Pominięte"]):
            if (today - w_date).days <= 7:
                audit_reports.append({"data": d_str, "plan": w_name, "status": status, "notatka": coach_note})
            continue

        day_acts = activities_by_date.get(d_str, [])
        # Jeśli to dzisiejszy dzień i jeszcze nie ma zarejestrowanej aktywności, czekamy do wieczora/jutra
        if w_date == today and not day_acts:
            continue

        planned_info = parse_planned_steps_summary(w_code)
        w_low = w_name.lower()
        new_status = None
        audit_tag = ""

        if planned_info["is_run"]:
            runs = [a for a in day_acts if "running" in str(a.get("Typ", "")).lower()]
            if runs:
                run = runs[0]
                act_km = safe_float(run.get("Dystans_Km"), 0.0)
                act_min = safe_float(run.get("Czas_Ruchu_Min"), safe_float(run.get("Czas_Calkowity_Min"), 0.0))
                act_hr = safe_float(run.get("Srednie_HR"))
                max_hr = safe_float(run.get("Max_HR"))
                act_load = safe_float(run.get("Obciazenie_Treningowe_Load"))
                act_pace = format_pace_min_km(act_min, act_km)

                plan_km = planned_info["planned_km"]
                km_ratio = (act_km / plan_km) if plan_km > 0 else 1.0
                if 0.75 <= km_ratio <= 1.35:
                    new_status = "Zrealizowane ✅"
                else:
                    new_status = "Zmodyfikowane ⚠️"

                target_desc = planned_info["hr_target"] or planned_info["pace_target"] or "wg planu"
                audit_tag = (
                    f"[AUDYT WYKONANIA: Wykonano {act_km} km (plan: {plan_km} km), "
                    f"śr. tempo {act_pace}, śr. HR {int(act_hr) if act_hr else '?'} bpm "
                    f"(max {int(max_hr) if max_hr else '?'} bpm, cel: {target_desc}), "
                    f"Load: {round(act_load, 1) if act_load else '?'}]"
                )
            elif day_acts:
                other_types = ", ".join(str(a.get("Nazwa", a.get("Typ", ""))) for a in day_acts)
                new_status = "Zmodyfikowane ⚠️ (Inna aktywność)"
                audit_tag = f"[AUDYT WYKONANIA: Zamiast biegu wykonano: {other_types}]"
            else:
                new_status = "Pominięte ❌"
                audit_tag = "[AUDYT WYKONANIA: Brak zarejestrowanego biegu w Garminie w tym dniu]"

        else:
            # Planowany był dzień bez biegu (REST: Siłownia, Rower, Basen lub Regeneracja)
            if any(k in w_low for k in ["siłownia", "silownia", "gym", "siła"]):
                gyms = [a for a in day_acts if "strength" in str(a.get("Typ", "")).lower()]
                if gyms:
                    g = gyms[0]
                    dur = safe_float(g.get("Czas_Calkowity_Min"), 0.0)
                    avg_hr = safe_float(g.get("Srednie_HR"))
                    ld = safe_float(g.get("Obciazenie_Treningowe_Load"))
                    new_status = "Zrealizowane ✅ (Siłownia)"
                    audit_tag = f"[AUDYT WYKONANIA: Wykonano {g.get('Nazwa', 'Siłownia')} - czas {round(dur)} min, śr. HR {int(avg_hr) if avg_hr else '?'} bpm, Load {round(ld, 1) if ld else '?'}]"
                elif day_acts:
                    other_types = ", ".join(str(a.get("Nazwa", a.get("Typ", ""))) for a in day_acts)
                    new_status = "Zmodyfikowane ⚠️"
                    audit_tag = f"[AUDYT WYKONANIA: Zamiast siłowni zarejestrowano: {other_types}]"
                else:
                    new_status = "Pominięte ❌"
                    audit_tag = "[AUDYT WYKONANIA: Brak zarejestrowanej sesji siłowej w Garminie]"
            else:
                # Czysty dzień regeneracji lub lekki cross-training
                if not day_acts:
                    new_status = "Zrealizowane ✅ (Regeneracja)"
                    audit_tag = "[AUDYT WYKONANIA: Pełna regeneracja zgodnie z planem]"
                else:
                    other_types = ", ".join(str(a.get("Nazwa", a.get("Typ", ""))) for a in day_acts)
                    new_status = "Zrealizowane ✅ (Aktywna regeneracja)"
                    audit_tag = f"[AUDYT WYKONANIA: Aktywności w dniu bez biegu: {other_types}]"

        if new_status:
            updated_note = f"{coach_note}\n{audit_tag}".strip() if audit_tag not in coach_note else coach_note
            treningi_sheet.update(values=[[new_status, updated_note]], range_name=f"D{row_num}:E{row_num}")
            row[3] = new_status
            row[4] = updated_note
            print(f"Audyt TODO-06 ({d_str} - {w_name}): {new_status}")
            audit_reports.append({"data": d_str, "plan": w_name, "status": new_status, "audyt": audit_tag})

    return audit_reports


def is_rest_day_entry(workout_name, steps_code):
    """Sprawdza, czy dany dzień w planie jest całkowitym dniem odpoczynku (Rest Day)."""
    w_low = str(workout_name).lower()
    s_up = str(steps_code).strip().upper()
    if s_up != "REST" and not s_up.startswith("REST"):
        return False
    # Jeśli steps == REST, sprawdzamy, czy w nazwie nie kryje się siłownia, rower lub basen
    active_non_run_keywords = ["siłownia", "silownia", "gym", "siła", "rower", "gravel", "basen", "pływanie", "swim"]
    if any(k in w_low for k in active_non_run_keywords):
        return False
    return True


def enforce_fixed_gym_and_max_streak(seven_day_plan, fixed_gym_days, activities_by_date, today_date):
    """
    Twardy strażnik w Pythonie:
    1. Gwarantuje, że dni z ręcznie wpisanym Gym A / Gym B w Google Calendar są ustawione jako sztywna Siłownia.
    2. Pilnuje zasady: NIGDY więcej niż 3 dni treningowe z rzędu (4. dzień automatycznie staje się Rest Day),
       chroniąc także dzień przed sztywną siłownią, gdyby siłownia miała być 4. dniem z rzędu.
    """
    # Krok 1: Obliczamy, ile dni treningowych z rzędu było do dzisiaj włącznie
    initial_streak = 0
    for back_offset in range(0, 4):
        d_check = (today_date - datetime.timedelta(days=back_offset)).isoformat()
        acts = activities_by_date.get(d_check, [])
        # Liczymy dzień jako treningowy, jeśli była zarejestrowana aktywność biegowa/siłowa/kolarska/pływacka
        real_acts = [a for a in acts if str(a.get("Typ", "")).lower() not in ["walking", "breathwork", "meditation"]]
        if real_acts:
            initial_streak += 1
        else:
            if back_offset == 0:
                # Jeśli dzisiaj jeszcze nie było treningu, sprawdzamy od wczoraj
                continue
            break

    # Krok 2: Nakładamy sztywne dni siłowni z Google Calendar
    plan_by_date = {item["date"]: item for item in seven_day_plan if "date" in item}
    sorted_dates = sorted(plan_by_date.keys())

    for d_str in sorted_dates:
        if d_str in fixed_gym_days:
            cal_title = fixed_gym_days[d_str]
            plan_by_date[d_str]["workout_name"] = f"Siłownia ({cal_title})"
            plan_by_date[d_str]["steps"] = "REST"
            plan_by_date[d_str]["is_fixed_gym"] = True
        else:
            plan_by_date[d_str]["is_fixed_gym"] = False

    # Krok 3: Walidacja maksymalnie 3 dni treningowych z rzędu
    streak = initial_streak
    for i, d_str in enumerate(sorted_dates):
        item = plan_by_date[d_str]
        is_rest = is_rest_day_entry(item["workout_name"], item["steps"])

        if is_rest:
            streak = 0
            continue

        # Sprawdzamy, czy po tym dniu następują sztywne dni siłowni, które przekroczyłyby limit 3 dni
        future_fixed_streak = 0
        for j in range(i + 1, min(i + 4, len(sorted_dates))):
            if plan_by_date[sorted_dates[j]]["is_fixed_gym"]:
                future_fixed_streak += 1
            else:
                break

        if (streak + 1 > 3) or (not item["is_fixed_gym"] and (streak + 1 + future_fixed_streak > 3)):
            if not item["is_fixed_gym"]:
                print(f"[STRAŻNIK REGUŁY 3 DNI] Zamieniam {d_str} ({item['workout_name']}) na Rest Day (ciąg wyniósłby >3 dni).")
                item["workout_name"] = "Dzień Regeneracji (Rest Day)"
                item["steps"] = "REST"
                item["coach_memory_note"] = (
                    f"[Automatyczna korekta: zasada max 3 dni treningowych z rzędu] "
                    f"Pełny odpoczynek dostosowany do sztywnego grafiku siłowni w Google Calendar."
                )
                streak = 0
            else:
                streak += 1
        else:
            streak += 1

    return [plan_by_date[d] for d in sorted_dates]
