from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.project_timeline import axis_ticks, resource_rows, schedule_rows, timeline_window


def test_timeline_window_and_short_scale_labels():
    project = SimpleNamespace(start_date=date(2026, 10, 1), due_date=date(2026, 11, 30))
    start, end, year = timeline_window(project, "all")
    assert (start, end, year) == (project.start_date, project.due_date, None)
    ticks = axis_ticks(start, end)
    assert ticks[0][1] == "01.10"
    assert all(len(label) <= 5 for _, label in ticks)


def test_long_timeline_uses_sparse_month_ticks_and_validates_year():
    project = SimpleNamespace(start_date=date(2025, 1, 1), due_date=date(2027, 12, 31))
    start, end, selected = timeline_window(project, "2026")
    assert (start, end, selected) == (date(2026, 1, 1), date(2026, 12, 31), 2026)
    assert len(axis_ticks(start, end)) <= 6
    try:
        timeline_window(project, "2030")
    except ValueError:
        pass
    else:
        raise AssertionError("Out-of-range year should be rejected")


def test_schedule_clips_bars_and_resource_overlaps_ignore_closed_tasks():
    owner = SimpleNamespace(full_name="Project Owner")
    first = SimpleNamespace(id=1, title="First", owner=owner, owner_user_id=7,
        start_date=date(2026, 9, 20), due_date=date(2026, 10, 10), status="pending",
        estimated_hours=Decimal("4.0"))
    second = SimpleNamespace(id=2, title="Second", owner=owner, owner_user_id=7,
        start_date=date(2026, 10, 5), due_date=date(2026, 10, 20), status="in_progress",
        estimated_hours=None)
    completed = SimpleNamespace(id=3, title="Closed", owner=owner, owner_user_id=7,
        start_date=date(2026, 10, 7), due_date=date(2026, 10, 9), status="completed",
        estimated_hours=Decimal("2.0"))
    project = SimpleNamespace(tasks=[first, second, completed], milestones=[])
    rows = schedule_rows(project, date(2026, 10, 1), date(2026, 10, 31))
    assert len(rows) == 3 and rows[0]["clipped"] is True
    summary = resource_rows(project)[0]
    assert summary["hours"] == Decimal("6.0")
    assert summary["overlaps"] == 1
    assert summary["unestimated"] == 1
