"""Analityka fizjologiczna (CTL, ATL, TSB, ACWR, baza 60d HRV/RHR/Snu) oraz odczyt zakładki Cele_i_Strategia."""
import datetime


def safe_float(val, default=None):
    if val is None or val == "":
        return default
    try:
        return float(str(val).replace(",", ".").strip())
    except ValueError:
        return default


def read_goals_and_strategy(sh):
    """
    Odczytuje zreorganizowaną zakładkę 'Cele_i_Strategia':
    zarówno tabelę Mezocykli, jak i tabelę Konfiguracji, Reguł, Urlopów i Startów.
    """
    ws = sh.worksheet("Cele_i_Strategia")
    rows = ws.get_all_values()

    config = {}
    races = []
    vacations_and_blocks = []
    training_rules = []
    mesocycles = []
    today = datetime.date.today()

    for r in rows:
        if len(r) < 2 or not r[0].strip():
            continue
        col0 = r[0].strip()
        col0_up = col0.upper()

        if col0_up in ["MEZOCYKL / FAZA", "TYP_WPISU"]:
            continue

        if col0_up.startswith("MEZOCYKL") or col0_up.startswith("BLOK SPECJALNY"):
            mesocycles.append({
                "faza": col0,
                "okres": r[1].strip() if len(r) > 1 else "",
                "tygodnie": r[2].strip() if len(r) > 2 else "",
                "cel": r[3].strip() if len(r) > 3 else "",
                "objetosc_km": r[4].strip() if len(r) > 4 else "",
                "uklad_tygodnia": r[5].strip() if len(r) > 5 else "",
                "kluczowe_jednostki": r[6].strip() if len(r) > 6 else "",
            })
            continue

        name = r[1].strip() if len(r) > 1 else ""
        val_or_date = r[2].strip() if len(r) > 2 else ""
        dist = r[3].strip() if len(r) > 3 else ""
        goal = r[4].strip() if len(r) > 4 else ""
        notes = r[5].strip() if len(r) > 5 else ""

        if col0_up == "KONFIGURACJA":
            config[name] = {
                "wartosc": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |"),
            }
        elif "START" in col0_up:
            days_left = None
            try:
                race_date = datetime.datetime.strptime(val_or_date[:10], "%Y-%m-%d").date()
                days_left = (race_date - today).days
            except ValueError:
                pass

            if days_left is None or days_left >= -7:
                races.append({
                    "typ": col0_up,
                    "nazwa": name,
                    "data": val_or_date,
                    "dni_do_startu": days_left,
                    "dystans": dist,
                    "cel": goal,
                    "uwagi": notes,
                })
        elif any(k in col0_up for k in ["URLOP", "WYJAZD", "NIEDOSTEPNOSC", "PRZERWA"]):
            vacations_and_blocks.append({
                "typ": col0_up,
                "nazwa": name,
                "okres": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |"),
            })
        else:
            training_rules.append({
                "kategoria": col0_up,
                "klucz": name,
                "wartosc": val_or_date,
                "szczegoly": f"{dist} | {goal} | {notes}".strip(" |"),
            })

    return config, races, vacations_and_blocks, training_rules, mesocycles


def analyze_full_history(wellness_sheet, activities_sheet):
    w_all = wellness_sheet.get_all_values()
    a_all = activities_sheet.get_all_values()
    today = datetime.date.today()

    w_headers = w_all[0][:24] if w_all else []
    w_rows = w_all[1:] if len(w_all) > 1 else []

    rhr_60, rhr_7, hrv_60, hrv_7, sleep_60, sleep_7 = [], [], [], [], [], []
    recent_wellness = []

    for row in w_rows[-90:]:
        padded = row[:24] + [""] * max(0, 24 - len(row))
        d_dict = dict(zip(w_headers, padded))
        try:
            d_date = datetime.datetime.strptime(d_dict.get("Data", ""), "%Y-%m-%d").date()
        except ValueError:
            continue

        days_ago = (today - d_date).days
        rhr = safe_float(d_dict.get("Tetno_Spoczynkowe"))
        hrv = safe_float(d_dict.get("HRV_rMSSD"))
        slp = safe_float(d_dict.get("Sen_Wynik"))

        if 0 <= days_ago <= 60:
            if rhr:
                rhr_60.append(rhr)
            if hrv:
                hrv_60.append(hrv)
            if slp:
                sleep_60.append(slp)
        if 0 <= days_ago <= 7:
            if rhr:
                rhr_7.append(rhr)
            if hrv:
                hrv_7.append(hrv)
            if slp:
                sleep_7.append(slp)

    for row in w_rows[-7:]:
        padded = row[:24] + [""] * max(0, 24 - len(row))
        recent_wellness.append(dict(zip(w_headers, padded)))

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    wellness_summary = {
        "RHR_srednia_7d": avg(rhr_7),
        "RHR_baza_60d": avg(rhr_60),
        "HRV_srednia_7d": avg(hrv_7),
        "HRV_baza_60d": avg(hrv_60),
        "Sen_Wynik_srednia_7d": avg(sleep_7),
        "Sen_Wynik_baza_60d": avg(sleep_60),
    }

    a_headers = a_all[0][:25] if a_all else []
    a_rows = a_all[1:] if len(a_all) > 1 else []

    daily_load = {}
    weekly_stats = {}
    recent_activities = []
    activities_by_date = {}

    for row in a_rows:
        padded = row[:25] + [""] * max(0, 25 - len(row))
        act = dict(zip(a_headers, padded))
        d_str = act.get("Data", "").strip()
        try:
            a_date = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if (today - a_date).days <= 30:
            activities_by_date.setdefault(d_str, []).append(act)

        load = safe_float(act.get("Obciazenie_Treningowe_Load"), 0.0)
        dist = safe_float(act.get("Dystans_Km"), 0.0)
        dur = safe_float(act.get("Czas_Calkowity_Min"), 0.0)
        atype = str(act.get("Typ", "")).lower()

        daily_load[a_date] = daily_load.get(a_date, 0.0) + load

        days_ago = (today - a_date).days
        if 0 <= days_ago <= 84:
            iso_yr, iso_wk, _ = a_date.isocalendar()
            wk_key = f"{iso_yr}-W{iso_wk:02d}"
            if wk_key not in weekly_stats:
                weekly_stats[wk_key] = {"run_km": 0.0, "run_sessions": 0, "gym_sessions": 0, "other_min": 0.0, "total_load": 0.0}
            weekly_stats[wk_key]["total_load"] += load
            if "running" in atype:
                weekly_stats[wk_key]["run_km"] += dist
                weekly_stats[wk_key]["run_sessions"] += 1
            elif "strength" in atype:
                weekly_stats[wk_key]["gym_sessions"] += 1
            else:
                weekly_stats[wk_key]["other_min"] += dur

    ctl, atl = 0.0, 0.0
    for i in range(180, -1, -1):
        d = today - datetime.timedelta(days=i)
        ld = daily_load.get(d, 0.0)
        ctl += (ld - ctl) * (1.0 / 42.0)
        atl += (ld - atl) * (1.0 / 7.0)

    tsb = ctl - atl
    acwr = round(atl / ctl, 2) if ctl > 5 else 1.0

    for row in a_rows[-12:]:
        padded = row[:25] + [""] * max(0, 25 - len(row))
        recent_activities.append(dict(zip(a_headers, padded)))

    sorted_weeks = dict(sorted(weekly_stats.items())[-8:])
    for k in sorted_weeks:
        sorted_weeks[k]["run_km"] = round(sorted_weeks[k]["run_km"], 1)
        sorted_weeks[k]["other_min"] = round(sorted_weeks[k]["other_min"], 0)
        sorted_weeks[k]["total_load"] = round(sorted_weeks[k]["total_load"], 0)

    load_metrics = {
        "CTL_Forma_Przewlekla_42d": round(ctl, 1),
        "ATL_Zmeczenie_Ostre_7d": round(atl, 1),
        "TSB_Bilans_Swiezosci": round(tsb, 1),
        "ACWR_Wskaznik_Ryzyka_Kontuzji": acwr,
        "Objetosc_Ostatnie_8_Tygodni": sorted_weeks,
    }

    return wellness_summary, recent_wellness, load_metrics, recent_activities, activities_by_date
