"""Render a ``ReportCard`` to HTML via Jinja2.

Two modes:

- ``embedded`` returns just the body fragment for Streamlit's
  ``st.html(...)`` embed (Shell 08).
- ``standalone`` wraps the fragment in a self-contained
  ``<html><head>...</head><body>...</body></html>`` document with inline
  CSS, suitable for export and shareable links.

Jinja2 ``autoescape=True`` covers HTML escaping by default, so explicit
``| e`` filters in the template are unnecessary. The renderer is
import-time-safe: ``Environment`` is built once at module load, pointing
at the package's ``templates/`` subdirectory (mirrors how
``division_render.py:11`` keeps its precedent simple).
"""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.tournaments.reports.schema import EventReportCard, ReportCard

__all__ = [
    "render_event_html",
    "render_html",
    "write_event_html",
    "write_html",
]


_TEMPLATES_DIR: Path = Path(__file__).parent / "templates"

_env: Environment = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=False,
    lstrip_blocks=False,
)


_STANDALONE_CSS: str = """\
:root { color-scheme: light; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  color: #111; max-width: 960px; margin: 24px auto; padding: 0 16px;
  line-height: 1.55; font-size: 14px;
}
.report-card { background: #fff; }
.rc-header { padding-bottom: 14px; border-bottom: 1px solid #e5e7eb; margin-bottom: 16px; }
.rc-title { margin: 4px 0; font-size: 22px; }
.rc-eyebrow { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: #6b7280; }
.rc-eyebrow-muted { color: #9ca3af; }
.rc-eyebrow-good { color: #166534; }
.rc-eyebrow-amber { color: #92400e; }
.rc-meta { font-size: 11px; color: #6b7280; }
.rc-meta-good { color: #166534; }
.rc-hero { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.rc-card {
  padding: 18px 20px; border: 1px solid #e5e7eb; border-radius: 10px;
  background: #fafafa; position: relative;
}
.rc-optimized { border-color: #16a34a; background: #f0fdf4; }
.rc-score { font-size: 42px; font-weight: 700; line-height: 1; color: #111; }
.rc-score-good { color: #166534; }
.rc-na { color: #6b7280; font-style: italic; padding: 6px 0; }
.rc-badge {
  position: absolute; top: 18px; right: 20px; font-weight: 600;
  padding: 4px 10px; border-radius: 999px; font-size: 14px;
}
.rc-badge-good { color: #166534; background: #dcfce7; }
.rc-badge-bad { color: #991b1b; background: #fee2e2; }
.rc-section {
  padding: 14px 18px; border: 1px solid #e5e7eb; border-radius: 10px;
  background: #fff; margin-bottom: 16px;
}
.rc-risks { border-color: #fde68a; background: #fffbeb; }
.rc-list { margin: 8px 0 0; padding-left: 20px; }
.rc-mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
.rc-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.rc-table th, .rc-table td { padding: 6px 12px; border-bottom: 1px solid #f3f4f6; text-align: left; }
.rc-table th { font-size: 11px; color: #6b7280; font-weight: 600; }
.rc-num { text-align: right; font-variant-numeric: tabular-nums; }
.rc-bold { font-weight: 600; }
.delta-up { color: #166534; }
.delta-down { color: #991b1b; }
.delta-flat { color: #6b7280; }
.delta-na { color: #9ca3af; font-style: italic; }
.rc-severity {
  display: inline-block; padding: 1px 6px; border-radius: 4px;
  font-size: 10px; font-weight: 600; text-transform: uppercase; margin-right: 4px;
}
.rc-severity-info { background: #e0e7ff; color: #3730a3; }
.rc-severity-warning { background: #fef3c7; color: #92400e; }
.rc-severity-blocker { background: #fee2e2; color: #991b1b; }
.rc-category { color: #6b7280; font-size: 12px; }
.rc-affected { color: #6b7280; font-size: 12px; }
.rc-from { color: #9ca3af; }
.rc-to { color: #166534; font-weight: 600; }
.rc-move-move_up { color: #166534; }
.rc-move-move_down { color: #991b1b; }
.rc-audit summary { cursor: pointer; }
.rc-division-heading { font-size: 13px; font-weight: 600; color: #374151; margin: 16px 0 4px; }
.rc-division-heading:first-of-type { margin-top: 8px; }
.rc-pool-heading { font-size: 12px; font-weight: 600; color: #6b7280; margin: 8px 0 2px; padding-left: 4px; }
.rc-subtle { font-size: 12px; color: #6b7280; margin: 4px 0 8px; }
.rc-headline { background: #f0f9ff; border-color: #bae6fd; }
.rc-headline-lead { font-size: 15px; line-height: 1.55; margin: 8px 0 12px; color: #0c4a6e; }
.rc-headline-stats { list-style: none; padding: 0; margin: 0; display: flex; gap: 24px; flex-wrap: wrap; }
.rc-headline-stats li { font-size: 13px; color: #0c4a6e; }
.rc-stat-label { color: #075985; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; display: block; margin-bottom: 2px; }
"""


def render_html(
    report_card: ReportCard,
    *,
    mode: Literal["embedded", "standalone"] = "standalone",
    show_override_audit: bool = True,
) -> str:
    """Render the ReportCard. ``mode`` controls whether the output is a
    self-contained HTML document (``standalone``) or a body fragment
    (``embedded``) for Streamlit's ``st.html`` embed.

    ``show_override_audit`` defaults to True so legacy callers (the
    persisted ``comparison.html`` written by ``compute_and_persist_report_card``,
    Export-HTML downloads) keep the in-template audit details block.
    Shell 08's inline embed passes ``False`` because an outside expander
    surfaces the same data with richer formatting and additionally shows
    scenario-level overrides the embedded template does not.
    """
    template = _env.get_template("report_card.html")
    fragment = template.render(report_card=report_card, show_override_audit=show_override_audit)
    if mode == "embedded":
        return fragment
    # ``event_name`` / ``gender`` / ``age_group`` come from provider scrape
    # output and the registry CSV, so they're untrusted from this module's
    # perspective. The title is built outside Jinja's autoescape, so we
    # escape explicitly to defend against ``</title><script>...`` style
    # injection. The CSS is a static module constant — no escape needed.
    safe_event_name = html.escape(report_card.event_name)
    safe_gender = html.escape(report_card.gender)
    safe_age_group = html.escape(report_card.age_group)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>Report Card &middot; {safe_event_name} &middot; "
        f"{safe_gender} {safe_age_group}</title>\n"
        f"<style>\n{_STANDALONE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{fragment}\n"
        "</body>\n"
        "</html>\n"
    )


def write_html(
    report_card: ReportCard,
    path: Path,
    *,
    mode: Literal["embedded", "standalone"] = "standalone",
    show_override_audit: bool = True,
) -> Path:
    """Atomically write the rendered HTML to ``path``.

    Mirrors ``_io.write_json``'s ``.tmp`` + ``os.replace`` + fsync
    pattern at ``storage/_io.py:40``. HTML isn't JSON, so we use
    ``Path.write_bytes`` against the ``.tmp`` path then ``os.replace``.

    ``show_override_audit`` is forwarded to ``render_html`` so the persisted
    ``comparison.html`` (written by ``compute_and_persist_report_card``)
    retains its audit ``<details>`` block by default.
    """
    rendered = render_html(report_card, mode=mode, show_override_audit=show_override_audit)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    encoded = rendered.encode("utf-8")
    with open(tmp_path, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    return path


def render_event_html(
    event_card: EventReportCard,
    *,
    mode: Literal["embedded", "standalone"] = "standalone",
) -> str:
    """Render the event-wide rollup. Mirrors ``render_html`` shape conventions
    (embedded vs standalone, inline CSS in standalone, autoescape via Jinja).
    """
    template = _env.get_template("event_report_card.html")
    fragment = template.render(event_card=event_card)
    if mode == "embedded":
        return fragment
    safe_event_name = html.escape(event_card.event_name)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>Event Report &middot; {safe_event_name}</title>\n"
        f"<style>\n{_STANDALONE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{fragment}\n"
        "</body>\n"
        "</html>\n"
    )


def write_event_html(
    event_card: EventReportCard,
    path: Path,
    *,
    mode: Literal["embedded", "standalone"] = "standalone",
) -> Path:
    """Atomically write the rendered event HTML to ``path``."""
    rendered = render_event_html(event_card, mode=mode)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    encoded = rendered.encode("utf-8")
    with open(tmp_path, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    return path
