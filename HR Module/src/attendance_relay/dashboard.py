from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any


def render_dashboard_html(
    *,
    rows: list[dict[str, Any]],
    total: int,
    employee_code_filter: str | None,
    device_sn_filter: str | None,
    limit: int,
    refreshed_at: str,
) -> str:
    table_rows = _build_rows(rows)
    employee_val = escape(employee_code_filter or "")
    device_val = escape(device_sn_filter or "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Attendance Dashboard</title>
  <meta http-equiv="refresh" content="20">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    :root {{
      --bg: #f2f4ef;
      --ink: #10231b;
      --ink-soft: #476457;
      --accent: #0b7a56;
      --accent-2: #d65a00;
      --card: #ffffff;
      --line: #d5ddd7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Sora", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 18%, #d9f5e9 0%, transparent 28%),
        radial-gradient(circle at 88% 5%, #ffe8cf 0%, transparent 22%),
        var(--bg);
      min-height: 100vh;
    }}
    .wrap {{
      width: min(1200px, 96vw);
      margin: 24px auto 40px;
    }}
    .header {{
      display: flex;
      gap: 14px;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: end;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.4rem, 2.2vw, 2rem);
      letter-spacing: 0.4px;
    }}
    .meta {{
      color: var(--ink-soft);
      font-size: 0.92rem;
    }}
    .stats {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .chip {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 0.9rem;
    }}
    .chip strong {{
      color: var(--accent);
      margin-left: 4px;
    }}
    .panel {{
      margin-top: 14px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 14px 35px rgba(16, 35, 27, 0.06);
    }}
    form {{
      padding: 14px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #f8fbf9 0%, #ffffff 100%);
    }}
    label {{
      display: block;
      font-size: 0.78rem;
      color: var(--ink-soft);
      margin-bottom: 6px;
    }}
    input {{
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      outline: none;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.85rem;
    }}
    .btns {{
      display: flex;
      gap: 8px;
      align-items: end;
    }}
    button, .link-btn {{
      border: none;
      border-radius: 10px;
      padding: 9px 12px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
      font-size: 0.85rem;
    }}
    button {{
      background: var(--accent);
      color: #fff;
    }}
    .link-btn {{
      background: #ffece0;
      color: var(--accent-2);
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 66vh;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
    }}
    th, td {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #f2f8f4;
      z-index: 1;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.4px;
      color: var(--ink-soft);
    }}
    tr:nth-child(even) td {{
      background: #fbfdfb;
    }}
    .mono {{
      font-family: "IBM Plex Mono", monospace;
    }}
    @media (max-width: 900px) {{
      form {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 620px) {{
      form {{ grid-template-columns: 1fr; }}
      .btns {{ align-items: stretch; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="header">
      <div>
        <h1>Attendance Dashboard</h1>
        <div class="meta">Auto-refresh every 20 seconds • Last refresh {escape(refreshed_at)}</div>
      </div>
    </section>
    <section class="stats">
      <div class="chip">Total Punches<strong>{total}</strong></div>
      <div class="chip">Rows Loaded<strong>{len(rows)}</strong></div>
      <div class="chip">Limit<strong>{limit}</strong></div>
    </section>
    <section class="panel">
      <form method="get" action="/dashboard">
        <div>
          <label for="employee_code">Employee Code</label>
          <input id="employee_code" name="employee_code" value="{employee_val}" placeholder="E1023">
        </div>
        <div>
          <label for="device_sn">Device Serial</label>
          <input id="device_sn" name="device_sn" value="{device_val}" placeholder="SN-01">
        </div>
        <div>
          <label for="limit">Limit</label>
          <input id="limit" name="limit" value="{limit}" placeholder="200">
        </div>
        <div class="btns">
          <button type="submit">Apply Filter</button>
          <a class="link-btn" href="/dashboard">Reset</a>
        </div>
      </form>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Employee</th>
              <th>Name</th>
              <th>Log DateTime</th>
              <th>Log Time</th>
              <th>Downloaded At</th>
              <th>Device SN</th>
              <th>Source IP</th>
              <th>Created At</th>
            </tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _build_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<tr><td colspan="9" style="text-align:center; color:#476457;">'
            "No attendance records found for the selected filters."
            "</td></tr>"
        )

    html_rows: list[str] = []
    for row in rows:
        html_rows.append(
            "<tr>"
            f"<td class='mono'>{escape(_as_text(row.get('id')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('employee_code')))}</td>"
            f"<td>{escape(_as_text(row.get('employee_name')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('log_datetime')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('log_time')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('downloaded_at')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('device_sn')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('source_ip')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('created_at')))}</td>"
            "</tr>"
        )
    return "".join(html_rows)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def render_employee_dashboard_html(
    *,
    rows: list[dict[str, Any]],
    total: int,
    employee_code_filter: str | None,
    department_filter: str | None,
    limit: int,
    refreshed_at: str,
) -> str:
    table_rows = _build_employee_rows(rows)
    employee_val = escape(employee_code_filter or "")
    department_val = escape(department_filter or "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Employee Dashboard</title>
  <meta http-equiv="refresh" content="20">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    :root {{
      --bg: #eef2f8;
      --ink: #13263d;
      --ink-soft: #4d6179;
      --accent: #1f5cc2;
      --accent-2: #176f5f;
      --card: #ffffff;
      --line: #d6deea;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Sora", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% 15%, #d9e8ff 0%, transparent 25%),
        radial-gradient(circle at 90% 8%, #dff7ef 0%, transparent 22%),
        var(--bg);
      min-height: 100vh;
    }}
    .wrap {{
      width: min(1400px, 96vw);
      margin: 24px auto 40px;
    }}
    .header {{
      display: flex;
      gap: 14px;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: end;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.4rem, 2.2vw, 2rem);
      letter-spacing: 0.4px;
    }}
    .meta {{
      color: var(--ink-soft);
      font-size: 0.92rem;
    }}
    .stats {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .chip {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 0.9rem;
    }}
    .chip strong {{
      color: var(--accent);
      margin-left: 4px;
    }}
    .panel {{
      margin-top: 14px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 14px 35px rgba(19, 38, 61, 0.08);
    }}
    form {{
      padding: 14px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #f7faff 0%, #ffffff 100%);
    }}
    label {{
      display: block;
      font-size: 0.78rem;
      color: var(--ink-soft);
      margin-bottom: 6px;
    }}
    input {{
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      outline: none;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.85rem;
    }}
    .btns {{
      display: flex;
      gap: 8px;
      align-items: end;
    }}
    button, .link-btn {{
      border: none;
      border-radius: 10px;
      padding: 9px 12px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
      font-size: 0.85rem;
    }}
    button {{
      background: var(--accent);
      color: #fff;
    }}
    .link-btn {{
      background: #e8fff8;
      color: var(--accent-2);
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 72vh;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
    }}
    th, td {{
      text-align: left;
      padding: 9px 11px;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #eef4ff;
      z-index: 1;
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.35px;
      color: var(--ink-soft);
    }}
    tr:nth-child(even) td {{
      background: #fbfdff;
    }}
    .mono {{
      font-family: "IBM Plex Mono", monospace;
    }}
    @media (max-width: 980px) {{
      form {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 620px) {{
      form {{ grid-template-columns: 1fr; }}
      .btns {{ align-items: stretch; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="header">
      <div>
        <h1>Employee Master Dashboard</h1>
        <div class="meta">Auto-refresh every 20 seconds • Last refresh {escape(refreshed_at)}</div>
      </div>
    </section>
    <section class="stats">
      <div class="chip">Total Employees<strong>{total}</strong></div>
      <div class="chip">Rows Loaded<strong>{len(rows)}</strong></div>
      <div class="chip">Limit<strong>{limit}</strong></div>
    </section>
    <section class="panel">
      <form method="get" action="/dashboard/employees">
        <div>
          <label for="employee_code">Employee Code</label>
          <input id="employee_code" name="employee_code" value="{employee_val}" placeholder="230">
        </div>
        <div>
          <label for="department">Department</label>
          <input id="department" name="department" value="{department_val}" placeholder="OPERATIONS">
        </div>
        <div>
          <label for="limit">Limit</label>
          <input id="limit" name="limit" value="{limit}" placeholder="500">
        </div>
        <div class="btns">
          <button type="submit">Apply Filter</button>
          <a class="link-btn" href="/dashboard/employees">Reset</a>
        </div>
      </form>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Employee Code</th>
              <th>Normalized</th>
              <th>Name</th>
              <th>Father Name</th>
              <th>Card No</th>
              <th>Proximity Card</th>
              <th>Email</th>
              <th>Phone</th>
              <th>Department</th>
              <th>Designation</th>
              <th>Branch</th>
              <th>Office Policy</th>
              <th>DOB</th>
              <th>DOJ</th>
              <th>Shift Start</th>
              <th>Shift Code</th>
              <th>Weekly Off</th>
              <th>Company</th>
            </tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _build_employee_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<tr><td colspan="18" style="text-align:center; color:#4d6179;">'
            "No employee records found for the selected filters."
            "</td></tr>"
        )

    html_rows: list[str] = []
    for row in rows:
        html_rows.append(
            "<tr>"
            f"<td class='mono'>{escape(_as_text(row.get('employee_code')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('employee_code_normalized')))}</td>"
            f"<td>{escape(_as_text(row.get('employee_name')))}</td>"
            f"<td>{escape(_as_text(row.get('father_name')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('card_no')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('proximity_card_no')))}</td>"
            f"<td>{escape(_as_text(row.get('email_id')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('phone_no')))}</td>"
            f"<td>{escape(_as_text(row.get('department')))}</td>"
            f"<td>{escape(_as_text(row.get('designation')))}</td>"
            f"<td>{escape(_as_text(row.get('branch_name')))}</td>"
            f"<td>{escape(_as_text(row.get('office_time_policy')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('date_of_birth')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('date_of_join')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('shift_start_date')))}</td>"
            f"<td>{escape(_as_text(row.get('shift_code')))}</td>"
            f"<td>{escape(_as_text(row.get('weekly_off')))}</td>"
            f"<td>{escape(_as_text(row.get('company_name')))}</td>"
            "</tr>"
        )
    return "".join(html_rows)


def render_device_admin_dashboard_html(
    *,
    rows: list[dict[str, Any]],
    refreshed_at: str,
    message: str | None = None,
    error: str | None = None,
) -> str:
    table_rows = _build_device_rows(rows)
    notice = f"<div class='notice ok'>{escape(message)}</div>" if message else ""
    failure = f"<div class='notice err'>{escape(error)}</div>" if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Device Admin</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    :root {{
      --bg: #eef4f8;
      --ink: #10273c;
      --ink-soft: #4d6179;
      --accent: #1c6bc8;
      --ok-bg: #e9f7ee;
      --ok-ink: #1f6b3a;
      --err-bg: #ffecec;
      --err-ink: #8f1c1c;
      --card: #ffffff;
      --line: #d8e2ef;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Sora", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 14%, #d9e8ff 0%, transparent 23%),
        radial-gradient(circle at 86% 8%, #dff7ef 0%, transparent 20%),
        var(--bg);
      min-height: 100vh;
    }}
    .wrap {{
      width: min(1280px, 96vw);
      margin: 24px auto 40px;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      flex-wrap: wrap;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.4rem, 2.2vw, 1.95rem);
      letter-spacing: 0.4px;
    }}
    .meta {{
      color: var(--ink-soft);
      font-size: 0.92rem;
    }}
    .panel {{
      margin-top: 14px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 14px 32px rgba(16, 39, 60, 0.07);
    }}
    form {{
      padding: 14px;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #f7faff 0%, #ffffff 100%);
    }}
    label {{
      display: block;
      font-size: 0.78rem;
      color: var(--ink-soft);
      margin-bottom: 6px;
    }}
    input {{
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      outline: none;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.84rem;
    }}
    .check-wrap {{
      display: flex;
      align-items: end;
      gap: 8px;
    }}
    .check-wrap input {{
      width: auto;
      height: 18px;
      margin: 0;
      transform: translateY(-2px);
    }}
    .check-wrap label {{
      margin: 0;
      font-size: 0.82rem;
    }}
    .btn {{
      border: none;
      border-radius: 10px;
      padding: 9px 12px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      margin-top: 22px;
    }}
    .notice {{
      margin: 12px 14px 0;
      padding: 9px 11px;
      border-radius: 10px;
      font-size: 0.85rem;
      border: 1px solid transparent;
    }}
    .notice.ok {{
      color: var(--ok-ink);
      background: var(--ok-bg);
      border-color: #b8e7c8;
    }}
    .notice.err {{
      color: var(--err-ink);
      background: var(--err-bg);
      border-color: #f6c5c5;
    }}
    .table-wrap {{
      overflow: auto;
      max-height: 68vh;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
    }}
    th, td {{
      text-align: left;
      padding: 9px 11px;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #eef4ff;
      z-index: 1;
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.35px;
      color: var(--ink-soft);
    }}
    tr:nth-child(even) td {{
      background: #fbfdff;
    }}
    .mono {{
      font-family: "IBM Plex Mono", monospace;
    }}
    @media (max-width: 920px) {{
      form {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 620px) {{
      form {{ grid-template-columns: 1fr; }}
      .btn {{ margin-top: 0; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="header">
      <div>
        <h1>Device Connection Admin</h1>
        <div class="meta">Last refresh {escape(refreshed_at)}</div>
      </div>
    </section>
    <section class="panel">
      <form method="post" action="/dashboard/admin/devices/save">
        <div>
          <label for="device_id">Device ID</label>
          <input id="device_id" name="device_id" required placeholder="machine-1">
        </div>
        <div>
          <label for="device_name">Device Name</label>
          <input id="device_name" name="device_name" placeholder="Main Gate">
        </div>
        <div>
          <label for="site_id">Site ID</label>
          <input id="site_id" name="site_id" placeholder="HQ">
        </div>
        <div>
          <label for="ip">Machine IP</label>
          <input id="ip" name="ip" required placeholder="192.168.1.19">
        </div>
        <div>
          <label for="port">Machine Port</label>
          <input id="port" name="port" type="number" min="1" max="65535" value="5005" required>
        </div>
        <div>
          <label for="machine_number">Machine Number</label>
          <input id="machine_number" name="machine_number" type="number" min="1" value="1" required>
        </div>
        <div>
          <label for="timezone">Timezone</label>
          <input id="timezone" name="timezone" value="Asia/Kolkata" required>
        </div>
        <div>
          <label for="machine_password">Machine Password</label>
          <input id="machine_password" name="machine_password" placeholder="0">
        </div>
        <div class="check-wrap">
          <input id="is_active" name="is_active" type="checkbox" checked>
          <label for="is_active">Device Active</label>
        </div>
        <div>
          <button class="btn" type="submit">Save Device Config</button>
        </div>
      </form>
      {notice}
      {failure}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Device ID</th>
              <th>Name</th>
              <th>Site</th>
              <th>IP</th>
              <th>Port</th>
              <th>Machine No.</th>
              <th>Timezone</th>
              <th>Active</th>
              <th>Password</th>
              <th>Seen</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {table_rows}
          </tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>
"""


def _build_device_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<tr><td colspan="11" style="text-align:center; color:#4d6179;">'
            "No device configuration saved yet."
            "</td></tr>"
        )

    html_rows: list[str] = []
    for row in rows:
        html_rows.append(
            "<tr>"
            f"<td class='mono'>{escape(_as_text(row.get('device_id')))}</td>"
            f"<td>{escape(_as_text(row.get('device_name')))}</td>"
            f"<td>{escape(_as_text(row.get('site_id')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('ip')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('port')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('machine_number')))}</td>"
            f"<td>{escape(_as_text(row.get('timezone')))}</td>"
            f"<td>{'Yes' if bool(row.get('is_active')) else 'No'}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('machine_password')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('last_seen_at')))}</td>"
            f"<td class='mono'>{escape(_as_text(row.get('updated_at')))}</td>"
            "</tr>"
        )
    return "".join(html_rows)
