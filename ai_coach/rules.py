"""Strażnik reguł mikrocyklu: sztywne sesje niebiegowe (Gym A/B z Google lub treningi w Garminie) i limit max 3 dni treningowych z rzędu."""
import datetime


def is_rest_day_entry(workout_name, steps_code):
    """Sprawdza, czy dany dzień w planie jest całkowitym dniem odpoczynku (Rest Day)."""
    w_low = str(workout_name).lower()
    s_up = str(steps_code).strip().upper()
    if s_up != "REST" and not s_up.startswith("REST"):
        return False
    active_non_run_keywords = ["siłownia", "silownia", "gym", "siła", "rower", "gravel", "basen", "pływanie", "swim"]
    if any(k in w_low for k in active_non_run_keywords):
        return False
    return True


def enforce_fixed_gym_and_max_streak(seven_day_plan, fixed_gym_days, activities_by_date, today_date):
    """
    Twardy strażnik w Pythonie:
    1. Gwarantuje, że dni ze sztywną siłownią / treningiem niebiegowym (w Google Calendar lub w kalendarzu Garmin)
       nie są nadpisywane biegiem.
    2. Pilnuje zasady: NIGDY więcej niż 3 dni treningowe z rzędu (4. dzień automatycznie staje się Rest Day),
       chroniąc także dzień przed sztywną siłownią, gdyby siłownia miała być 4. dniem z rzędu.
    """
    initial_streak = 0
    for back_offset in range(0, 4):
        d_check = (today_date - datetime.timedelta(days=back_offset)).isoformat()
        acts = activities_by_date.get(d_check, [])
        real_acts = [a for a in acts if str(a.get("Typ", "")).lower() not in ["walking", "breathwork", "meditation"]]
        if real_acts:
            initial_streak += 1
        else:
            if back_offset == 0:
                continue
            break

    plan_by_date = {item["date"]: item for item in seven_day_plan if "date" in item}
    sorted_dates = sorted(plan_by_date.keys())

    for d_str in sorted_dates:
        if d_str in fixed_gym_days:
            cal_title = fixed_gym_days[d_str]
            if any(k in cal_title.lower() for k in ["gym", "siłownia", "silownia", "siła"]):
                plan_by_date[d_str]["workout_name"] = f"Siłownia ({cal_title})"
            else:
                plan_by_date[d_str]["workout_name"] = cal_title
            plan_by_date[d_str]["steps"] = "REST"
            plan_by_date[d_str]["is_fixed_gym"] = True
        else:
            plan_by_date[d_str]["is_fixed_gym"] = False

    streak = initial_streak
    for i, d_str in enumerate(sorted_dates):
        item = plan_by_date[d_str]
        is_rest = is_rest_day_entry(item["workout_name"], item["steps"])

        if is_rest:
            streak = 0
            continue

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
                    "[Automatyczna korekta: zasada max 3 dni treningowych z rzędu] "
                    "Pełny odpoczynek dostosowany do sztywnego grafiku siłowni w kalendarzu."
                )
                streak = 0
            else:
                streak += 1
        else:
            streak += 1

    return [plan_by_date[d] for d in sorted_dates]
