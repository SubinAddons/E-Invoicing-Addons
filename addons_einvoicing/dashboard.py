"""Summaries of permission-filtered submission rows for Frappe 15 and 16."""
from collections import Counter
from datetime import date, datetime


def summarize(rows):
    counts, trend = Counter(), Counter()
    for row in rows:
        counts[row["status"]] += 1
        created = row["creation"]
        if isinstance(created, datetime):
            day = created.date().isoformat()
        elif isinstance(created, date):
            day = created.isoformat()
        else:
            day = datetime.fromisoformat(str(created)).date().isoformat()
        trend[day] += 1
    return (
        [{"status": status, "total": total} for status, total in sorted(counts.items())],
        [{"day": day, "total": total} for day, total in sorted(trend.items())],
    )
