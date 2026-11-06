"""
Publikacja 7-dniowego planu z `ai_coach` do arkusza `Treningi` oraz bezpośrednio do kalendarza Garmin Connect.
Zasady rozwiązywania konfliktów w kalendarzu Garmin Connect:
1. Jeśli w danym dniu w kalendarzu Garmin jest już trening siłowy (lub inny trening poza bieganiem) -> pomijamy dzień (status: `Zaplanowane (Bez biegu)`).
2. Jeśli w danym dniu w kalendarzu Garmin jest już INNY bieg (niebędący wcześniej wgranym biegiem `ai_coach` wg kolumny F `Garmin_Workout_ID`):
   - NIE usuwamy go automatycznie.
   - Wysyłamy powiadomienie push przez Join do Taskera (`send_garmin_conflict_alert`) z prośbą o usunięcie starego biegu.
   - Zapisujemy w arkuszu status `Konflikt ⚠️ (Usuń stary bieg w Garminie)`.
3. Jeśli w danym dniu był wcześniejszy bieg wgrany przez `ai_coach` (zgodny `Garmin_Workout_ID`), a plan uległ zmianie -> podmieniamy go na nową wersję.
"""
import re

from common.garmin_calendar import delete_workout, upload_and_schedule
from common.notify import send_garmin_conflict_alert
from common.workout_parser import build_running_workout, is_rest_code


def normalize_steps_only(code_str):
    if not code_str:
        return ""
    lines = [l.strip() for l in code_str.strip().splitlines() if l.strip()]
    if not lines:
        return ""
    if lines[0].upper() == "REST":
        return "REST"
    if re.match(r"^\d{4}-\d{2}-\d{2}\b", lines[0]):
        return "\n".join(lines[1:]).strip()
    return "\n".join(lines).strip()


def _upsert_sheet_row(treningi_sheet, existing_by_date, target_date, row_values):
    if target_date in existing_by_date:
        row_num = existing_by_date[target_date]["row_num"]
        treningi_sheet.update(values=[row_values], range_name=f"A{row_num}:F{row_num}")
    else:
        treningi_sheet.append_row(row_values)


def publish_seven_day_plan_to_garmin(
    garmin_client,
    treningi_sheet,
    seven_day_plan,
    existing_by_date,
    garmin_planned_by_date,
):
    """Zapisuje 7-dniowy plan w zakładce Treningi i synchronizuje go z kalendarzem Garmin Connect."""
    for day_item in seven_day_plan:
        target_date = str(day_item.get("date", "")).strip()
        if not target_date:
            continue

        workout_name = str(day_item.get("workout_name", "Trening AI")).strip()
        steps_raw = str(day_item.get("steps", "REST")).strip()
        coach_note = str(day_item.get("coach_memory_note", "")).strip()

        is_rest = is_rest_code(steps_raw)
        if is_rest:
            clean_new_steps = "REST"
            full_workout_code = "REST"
        else:
            clean_new_steps = normalize_steps_only(steps_raw)
            full_workout_code = f"{target_date} {workout_name}\n{clean_new_steps}"

        ex = existing_by_date.get(target_date)
        owned_wid = ex.get("garmin_workout_id", "") if ex else ""
        day_garmin_workouts = garmin_planned_by_date.get(target_date, [])

        non_run_in_garmin = [w for w in day_garmin_workouts if not w.get("is_run", True)]
        runs_in_garmin = [w for w in day_garmin_workouts if w.get("is_run", True)]

        # REGUŁA 1: W kalendarzu Garmin jest już trening siłowy / inny poza bieganiem -> pomijamy dzień
        if non_run_in_garmin and not is_rest:
            existing_non_run_title = non_run_in_garmin[0].get("title") or "Trening niebiegowy"
            print(f"[{target_date}] W kalendarzu Garmin jest już '{existing_non_run_title}' – pomijam wgrywanie biegu.")
            row_values = [
                target_date,
                existing_non_run_title,
                "REST",
                "Zaplanowane (Bez biegu)",
                coach_note,
                non_run_in_garmin[0].get("workout_id", ""),
            ]
            _upsert_sheet_row(treningi_sheet, existing_by_date, target_date, row_values)
            continue

        # Dzień bez biegania (REST / Siłownia / Regeneracja)
        if is_rest:
            # Jeśli wcześniej na ten dzień ai_coach wgrał swój własny bieg, wycofujemy go z kalendarza Garmin
            if owned_wid:
                for w in runs_in_garmin:
                    if w.get("workout_id") == owned_wid:
                        try:
                            delete_workout(garmin_client, owned_wid)
                        except Exception as e:
                            print(f"Uwaga przy usuwaniu wycofanego biegu AI Coach ({target_date}): {e}")
            row_values = [target_date, workout_name, "REST", "Zaplanowane (Bez biegu)", coach_note, ""]
            _upsert_sheet_row(treningi_sheet, existing_by_date, target_date, row_values)
            print(f"[{target_date}] Zaplanowano dzień bez biegu -> {workout_name}")
            continue

        # Dzień biegowy: sprawdzamy, czy w Garminie są obce biegi (niewgrane przez ai_coach)
        foreign_runs = [
            w for w in runs_in_garmin
            if not (owned_wid and w.get("workout_id") == owned_wid)
        ]
        if foreign_runs:
            foreign = foreign_runs[0]
            foreign_title = foreign.get("title") or "Inny bieg"
            if foreign_title.strip().lower() != workout_name.lower():
                print(
                    f"[{target_date}] KONFLIKT w kalendarzu Garmin: istnieje bieg '{foreign_title}', "
                    f"a AI Coach chce zaplanować '{workout_name}'. Wysyłam prośbę o usunięcie starego biegu."
                )
                send_garmin_conflict_alert(target_date, foreign_title)
                conflict_note = f"{coach_note}\n[KONFLIKT GARMIN: W kalendarzu jest już bieg '{foreign_title}' – usuń go, aby wgrać '{workout_name}']".strip()
                row_values = [
                    target_date,
                    workout_name,
                    full_workout_code,
                    "Konflikt ⚠️ (Usuń stary bieg w Garminie)",
                    conflict_note,
                    owned_wid,
                ]
                _upsert_sheet_row(treningi_sheet, existing_by_date, target_date, row_values)
                continue

        # Brak obcych biegów: sprawdzamy, czy nasz własny bieg w Garminie jest już aktualny
        if ex:
            old_steps = normalize_steps_only(ex["code"])
            old_name = ex["name"]
            steps_changed = (old_steps != clean_new_steps) or (old_name != workout_name)
            already_in_garmin = any(w.get("workout_id") == owned_wid for w in runs_in_garmin) if owned_wid else bool(runs_in_garmin)

            if not steps_changed and ex["status"] == "Zaplanowane" and already_in_garmin:
                print(f"[{target_date}] Plan biegowy w Garminie bez zmian ({workout_name}) – zachowuję.")
                continue

            # Jeśli aktualizujemy własny bieg AI Coacha, usuwamy poprzednią wersję z Garmina
            if owned_wid:
                for w in runs_in_garmin:
                    if w.get("workout_id") == owned_wid:
                        try:
                            delete_workout(garmin_client, owned_wid)
                        except Exception as e:
                            print(f"Uwaga przy podmianie treningu AI Coach ({target_date}): {e}")

        # Budujemy i wgrywamy bieg bezpośrednio do kalendarza Garmin Connect
        try:
            payload = build_running_workout(workout_name, full_workout_code)
            new_wid = upload_and_schedule(garmin_client, payload, target_date)
            status_flag = "Zaplanowane"
            print(f"[{target_date}] Wgrano do kalendarza Garmin -> {workout_name} (ID: {new_wid})")
        except Exception as e:
            print(f"Błąd wgrywania treningu do Garmina ({target_date} - {workout_name}): {e}")
            new_wid = owned_wid
            status_flag = "Do wgrania"

        row_values = [target_date, workout_name, full_workout_code, status_flag, coach_note, new_wid]
        _upsert_sheet_row(treningi_sheet, existing_by_date, target_date, row_values)
