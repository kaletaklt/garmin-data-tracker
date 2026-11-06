"""TODO-06: Automatyczny audyt wykonania treningu (Plan vs Wykonanie)."""
import datetime
import re

from ai_coach.analytics import safe_float


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
        "pace_target": pace_targets[0] if pace_targets else None,
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

        if any(status.startswith(prefix) for prefix in ["Zrealizowane", "Zmodyfikowane", "Pominięte"]):
            if (today - w_date).days <= 7:
                audit_reports.append({"data": d_str, "plan": w_name, "status": status, "notatka": coach_note})
            continue

        day_acts = activities_by_date.get(d_str, [])
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
            if any(k in w_low for k in ["siłownia", "silownia", "gym", "siła"]):
                gyms = [a for a in day_acts if "strength" in str(a.get("Typ", "")).lower()]
                if gyms:
                    g = gyms[0]
                    dur = safe_float(g.get("Czas_Calkowity_Min"), 0.0)
                    avg_hr = safe_float(g.get("Srednie_HR"))
                    ld = safe_float(g.get("Obciazenie_Treningowe_Load"))
                    new_status = "Zrealizowane ✅ (Siłownia)"
                    audit_tag = (
                        f"[AUDYT WYKONANIA: Wykonano {g.get('Nazwa', 'Siłownia')} - "
                        f"czas {round(dur)} min, śr. HR {int(avg_hr) if avg_hr else '?'} bpm, "
                        f"Load {round(ld, 1) if ld else '?'}]"
                    )
                elif day_acts:
                    other_types = ", ".join(str(a.get("Nazwa", a.get("Typ", ""))) for a in day_acts)
                    new_status = "Zmodyfikowane ⚠️"
                    audit_tag = f"[AUDYT WYKONANIA: Zamiast siłowni zarejestrowano: {other_types}]"
                else:
                    new_status = "Pominięte ❌"
                    audit_tag = "[AUDYT WYKONANIA: Brak zarejestrowanej sesji siłowej w Garminie]"
            else:
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
