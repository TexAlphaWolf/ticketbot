"""Ticket statistics exported as CSV or Excel (.xlsx) for the staff."""

import csv
import io
from datetime import UTC, datetime

from . import config
from .logic import compute_stats

# Text starting with one of these is run as a formula by Excel / LibreOffice / Sheets
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

COLUMNS = (
    "ticket", "type", "priority", "status", "owner", "owner_id", "assigned_to", "claimed_by",
    "closed_by", "opened_at", "first_response_at", "closed_at", "first_response_min",
    "resolution_min", "close_reason", "rating", "rating_comment",
)
TIME_COLUMNS = {"opened_at", "first_response_at", "closed_at"}


def safe_text(value):
    """Neutralize spreadsheet formulas in user-written text (CSV/formula injection)."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _utc(ts: float | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).replace(tzinfo=None)


def _minutes(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return round(max(0.0, end - start) / 60, 1)


def ticket_rows(tickets: list[dict], names: dict[int, str], _) -> list[dict]:
    """One row per ticket with the metadata used by /stats (no subject or messages)."""

    def name(user_id):
        if not user_id:
            return None
        return names.get(user_id) or str(user_id)

    rows = []
    for t in sorted(tickets, key=lambda t: (t["opened_at"], t["id"])):
        priority = t.get("priority")
        rows.append({
            "ticket": t.get("name") or (f"#{t['number']}" if t.get("number") else None),
            "type": t["type_label"],
            "priority": _("priority." + priority) if priority in config.PRIORITY_EMOJI
            else _("priority.none"),
            "status": _("export.status." + t["status"]),
            "owner": name(t["owner_id"]),
            "owner_id": str(t["owner_id"]),
            "assigned_to": name(t.get("assigned_to")),
            "claimed_by": name(t.get("claimed_by")),
            "closed_by": name(t.get("closed_by")),
            "opened_at": _utc(t["opened_at"]),
            "first_response_at": _utc(t.get("first_response_at")),
            "closed_at": _utc(t.get("closed_at")),
            "first_response_min": _minutes(t["opened_at"], t.get("first_response_at")),
            "resolution_min": _minutes(t["opened_at"], t.get("closed_at"))
            if t["status"] == config.STATUS_CLOSED else None,
            "close_reason": t.get("close_reason"),
            "rating": t.get("rating"),
            "rating_comment": t.get("rating_comment"),
        })
    return rows


def headers(_) -> list[str]:
    return [_("export.col." + c) for c in COLUMNS]


def to_csv(rows: list[dict], _) -> bytes:
    """UTF-8 with BOM, so Excel opens accents and emoji correctly."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(headers(_))
    for row in rows:
        writer.writerow([
            row[c].strftime("%Y-%m-%d %H:%M:%S") if c in TIME_COLUMNS and row[c]
            else "" if row[c] is None else safe_text(row[c])
            for c in COLUMNS
        ])
    return out.getvalue().encode("utf-8-sig")


def to_xlsx(rows: list[dict], tickets: list[dict], names: dict[int, str], period: str,
            _) -> bytes:
    """Workbook with a Tickets sheet and a Summary sheet (totals and staff leaderboard)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    bold = Font(bold=True)
    wb = Workbook()
    ws = wb.active
    ws.title = _("export.sheet.tickets")[:31]
    ws.append(headers(_))
    for row in rows:
        ws.append([safe_text(row[c]) for c in COLUMNS])
    for cell in ws[1]:
        cell.font = bold
    for i, column in enumerate(COLUMNS, 1):
        letter = get_column_letter(i)
        if column in TIME_COLUMNS:
            for cell in ws[letter][1:]:
                cell.number_format = "yyyy-mm-dd hh:mm"
        longest = max(len(str(cell.value)) for cell in ws[letter] if cell.value is not None)
        width = 18 if column in TIME_COLUMNS else max(longest, 8)
        ws.column_dimensions[letter].width = min(max(width, len(ws.cell(1, i).value)) + 2, 40)
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions

    s = compute_stats(tickets)
    summary = wb.create_sheet(_("export.sheet.summary")[:31])

    def minutes(seconds):
        return round(seconds / 60, 1) if seconds is not None else None

    for label, value in (
        (_("export.sum.period"), period),
        (_("export.sum.generated"), _utc(datetime.now(UTC).timestamp())),
        (_("export.sum.opened"), s["opened"]),
        (_("export.sum.closed"), s["closed"]),
        (_("export.sum.open"), s["open"]),
        (_("export.sum.first_response"), minutes(s["avg_first_response"])),
        (_("export.sum.resolution"), minutes(s["avg_resolution"])),
        (_("export.sum.rating"), round(s["avg_rating"], 2) if s["avg_rating"] else None),
        (_("export.sum.ratings"), s["ratings"]),
    ):
        summary.append([label, value])
        summary.cell(summary.max_row, 1).font = bold
    summary.cell(2, 2).number_format = "yyyy-mm-dd hh:mm"

    summary.append([])
    summary.append([_("export.col.type"), _("export.sum.count")])
    for cell in summary[summary.max_row]:
        cell.font = bold
    for label, count in s["by_type"].most_common():
        summary.append([safe_text(label), count])

    summary.append([])
    summary.append([_("export.sum.staff"), _("export.sum.handled"), _("export.sum.rating"),
                    _("export.sum.ratings"), _("export.sum.first_response")])
    for cell in summary[summary.max_row]:
        cell.font = bold
    for row in s["leaderboard"]:
        summary.append([
            safe_text(names.get(row["staff_id"]) or str(row["staff_id"])),
            row["handled"],
            round(row["avg_rating"], 2) if row["avg_rating"] else None,
            row["ratings"],
            minutes(row["avg_first_response"]),
        ])
    summary.column_dimensions["A"].width = 34
    for letter in "BCDE":
        summary.column_dimensions[letter].width = 18

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
