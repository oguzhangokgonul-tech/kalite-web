"""Read-only project schedule and resource summaries."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from heapq import heappop, heappush


def timeline_window(project, selected_year=None):
    if selected_year in (None, "", "all"):
        if selected_year == "all" or (project.due_date - project.start_date).days <= 730:
            return project.start_date, project.due_date, None
        today = date.today()
        year = min(max(today.year, project.start_date.year), project.due_date.year)
    else:
        try:
            year = int(selected_year)
        except (TypeError, ValueError):
            raise ValueError("Geçerli bir yıl seçin.") from None
        if year < project.start_date.year or year > project.due_date.year:
            raise ValueError("Seçilen yıl proje tarihleri dışında.")
    return max(project.start_date, date(year, 1, 1)), min(project.due_date, date(year, 12, 31)), year


def schedule_rows(project, window_start, window_end):
    span = (window_end - window_start).days + 1
    rows = []
    for task in project.tasks:
        if task.due_date < window_start or task.start_date > window_end:
            continue
        start = max(task.start_date, window_start)
        end = min(task.due_date, window_end)
        left = 100 * (start - window_start).days / span
        width = max(0.8, 100 * ((end - start).days + 1) / span)
        rows.append({"kind": "task", "title": task.title, "start": task.start_date,
            "due": task.due_date, "status": task.status, "owner": task.owner,
            "estimated_hours": task.estimated_hours, "left": min(left, 99.2),
            "width": min(width, 100 - min(left, 99.2)), "id": task.id,
            "clipped": start != task.start_date or end != task.due_date})
    for milestone in project.milestones:
        if not window_start <= milestone.target_date <= window_end:
            continue
        left = 100 * ((milestone.target_date - window_start).days + 0.5) / span
        rows.append({"kind": "milestone", "title": milestone.title,
            "start": milestone.target_date, "due": milestone.target_date,
            "status": milestone.status, "owner": None, "estimated_hours": None,
            "left": min(max(left, 0), 100), "width": 0, "id": milestone.id, "clipped": False})
    rows.sort(key=lambda row: (row["start"], row["kind"] != "milestone", row["id"]))
    return rows


def axis_ticks(window_start, window_end):
    span = (window_end - window_start).days + 1
    start_format = "%d.%m" if span <= 62 else "%m.%Y" if span <= 730 else "%Y"
    ticks = [(0.0, window_start.strftime(start_format))]
    if span <= 62:
        current = window_start + timedelta(days=(7 - window_start.weekday()) % 7)
        step = "week"
    elif span <= 730:
        current = date(window_start.year + (window_start.month == 12), window_start.month % 12 + 1, 1)
        step = "month"
        month_step = 3 if span > 500 else 2 if span > 310 else 1
    else:
        current = date(window_start.year + 1, 1, 1)
        step = "year"
    while current <= window_end:
        position = 100 * (current - window_start).days / span
        label = current.strftime("%d.%m") if step == "week" else current.strftime("%m.%Y" if step == "month" else "%Y")
        if position > 9:
            ticks.append((position, label))
        if step == "week":
            current += timedelta(days=7)
        elif step == "month":
            month_index = current.year * 12 + current.month - 1 + month_step
            current = date(month_index // 12, month_index % 12 + 1, 1)
        else:
            current = date(current.year + 1, 1, 1)
    return ticks


def resource_rows(project):
    grouped = defaultdict(list)
    for task in project.tasks:
        if task.status != "cancelled":
            grouped[task.owner_user_id].append(task)
    rows = []
    for tasks in grouped.values():
        ordered = sorted(tasks, key=lambda task: (task.start_date, task.due_date, task.id))
        open_tasks = [task for task in ordered if task.status in {"pending", "in_progress"}]
        active_due = []
        overlaps = 0
        for task in open_tasks:
            while active_due and active_due[0] < task.start_date:
                heappop(active_due)
            overlaps += len(active_due)
            heappush(active_due, task.due_date)
        estimated = [task.estimated_hours for task in ordered if task.estimated_hours is not None]
        rows.append({"owner": ordered[0].owner, "tasks": ordered,
            "hours": sum(estimated, Decimal("0.0")),
            "unestimated": len(ordered) - len(estimated), "overlaps": overlaps})
    return sorted(rows, key=lambda row: ((row["owner"].full_name if row["owner"] else "").casefold(), row["tasks"][0].owner_user_id))
