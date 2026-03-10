#!/usr/bin/env python3
"""
EnviroSat — ground_station/dashboard.py
Browser-based live dashboard served over HTTP.

Reads the most recent CSV log file written by ground_station.py
and serves a self-refreshing HTML dashboard on http://localhost:8080

Open in any browser on the same machine. The page auto-refreshes
every 5 seconds using a simple meta-refresh tag — no JavaScript
frameworks, no dependencies beyond the Python standard library.

Start alongside ground_station.py in a second terminal:
  python dashboard.py

Or run both together:
  python ground_station.py &
  python dashboard.py

Author:  EnviroSat Team
Licence: MIT
"""

import csv
import glob
import http.server
import json
import logging
import os
import socketserver
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

OUTPUT_DIR   = os.path.expanduser("~/envirosat_ground_station")
DASHBOARD_PORT = 8080
MAX_HISTORY  = 60   # Number of records to show in history table


def latest_csv_file() -> str | None:
    """Return the most recently modified CSV log file."""
    pattern = os.path.join(OUTPUT_DIR, "ground_station_*.csv")
    files   = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return files[0] if files else None


def read_csv_records(filepath: str, max_rows: int = MAX_HISTORY) -> list:
    """Return the last max_rows records from a CSV log file as a list of dicts."""
    records = []
    try:
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(row)
    except (OSError, csv.Error):
        pass
    return records[-max_rows:]


def battery_bar(volts_str: str) -> str:
    """Return an ASCII battery bar based on voltage string."""
    try:
        v   = float(volts_str)
        pct = max(0, min(100, int((v - 3.2) / (4.15 - 3.2) * 100)))
    except (ValueError, TypeError):
        return "—"
    filled = pct // 10
    bar    = "█" * filled + "░" * (10 - filled)
    color  = "#2ecc71" if pct > 40 else "#e67e22" if pct > 20 else "#e74c3c"
    return f'<span style="color:{color};font-family:monospace">[{bar}] {pct}%</span>'


def render_html(records: list) -> str:
    """Build the full HTML page from the record list."""
    latest = records[-1] if records else {}
    total  = len(records)

    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Status colour
    gps_ok   = latest.get("gps_fix", "").lower() in ("true", "1", "yes")
    batt_v   = latest.get("battery_v", "")

    rows_html = ""
    for r in reversed(records):
        rows_html += (
            f"<tr>"
            f"<td>{r.get('received_at','')}</td>"
            f"<td>{r.get('temperature_c','')}</td>"
            f"<td>{r.get('pressure_hpa','')}</td>"
            f"<td>{r.get('humidity_pct','')}</td>"
            f"<td>{r.get('pm2_5','')}</td>"
            f"<td>{r.get('lat','')}</td>"
            f"<td>{r.get('lon','')}</td>"
            f"<td>{r.get('battery_v','')}</td>"
            f"</tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="5">
<title>EnviroSat Ground Station</title>
<style>
  :root {{
    --navy: #0D2B4E; --teal: #1B7A8A; --orange: #E07B39;
    --green: #1E7A4A; --bg: #0f1923; --card: #172434;
    --text: #d0e8f0; --dim: #7a9ab0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: Arial, sans-serif; padding: 20px; }}
  h1 {{ color: var(--teal); font-size: 1.6rem; margin-bottom: 4px; }}
  .subtitle {{ color: var(--dim); font-size: 0.85rem; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: var(--card); border-left: 4px solid var(--teal); padding: 14px 16px; border-radius: 4px; }}
  .card-label {{ font-size: 0.75rem; color: var(--dim); text-transform: uppercase; letter-spacing: 0.05em; }}
  .card-value {{ font-size: 1.5rem; font-weight: bold; color: var(--text); margin-top: 4px; }}
  .card-unit  {{ font-size: 0.8rem; color: var(--dim); }}
  .ok   {{ color: #2ecc71; }} .warn {{ color: #e67e22; }} .err {{ color: #e74c3c; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  th {{ background: var(--navy); color: var(--teal); padding: 8px 10px; text-align: left; }}
  td {{ border-bottom: 1px solid #1e3248; padding: 6px 10px; color: var(--text); }}
  tr:hover td {{ background: #1e3248; }}
  .section-title {{ color: var(--teal); font-size: 1rem; font-weight: bold; margin: 20px 0 10px; border-bottom: 1px solid var(--teal); padding-bottom: 4px; }}
</style>
</head>
<body>
<h1>🛰 EnviroSat Ground Station</h1>
<div class="subtitle">Auto-refresh every 5 s &nbsp;·&nbsp; {ts_now} &nbsp;·&nbsp; {total} packets received</div>

<div class="grid">
  <div class="card">
    <div class="card-label">Temperature</div>
    <div class="card-value">{latest.get('temperature_c','—')}<span class="card-unit"> °C</span></div>
  </div>
  <div class="card">
    <div class="card-label">Pressure</div>
    <div class="card-value">{latest.get('pressure_hpa','—')}<span class="card-unit"> hPa</span></div>
  </div>
  <div class="card">
    <div class="card-label">Humidity</div>
    <div class="card-value">{latest.get('humidity_pct','—')}<span class="card-unit"> %</span></div>
  </div>
  <div class="card">
    <div class="card-label">PM2.5</div>
    <div class="card-value">{latest.get('pm2_5','—')}<span class="card-unit"> µg/m³</span></div>
  </div>
  <div class="card">
    <div class="card-label">PM10</div>
    <div class="card-value">{latest.get('pm10','—')}<span class="card-unit"> µg/m³</span></div>
  </div>
  <div class="card">
    <div class="card-label">Battery</div>
    <div class="card-value" style="font-size:1rem">{battery_bar(batt_v)}</div>
  </div>
  <div class="card">
    <div class="card-label">GPS</div>
    <div class="card-value {'ok' if gps_ok else 'err'}" style="font-size:1rem">{'✓ FIX' if gps_ok else '✗ NO FIX'}</div>
    <div class="card-unit">{latest.get('lat','—')} / {latest.get('lon','—')}</div>
  </div>
  <div class="card">
    <div class="card-label">Heading</div>
    <div class="card-value">{latest.get('heading_deg','—')}<span class="card-unit"> °</span></div>
  </div>
</div>

<div class="section-title">Recent Packets (last {MAX_HISTORY})</div>
<table>
<thead>
  <tr>
    <th>Received</th><th>Temp (°C)</th><th>Press (hPa)</th>
    <th>Hum (%)</th><th>PM2.5</th><th>Lat</th><th>Lon</th><th>Batt (V)</th>
  </tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        csv_file = latest_csv_file()
        if csv_file:
            records = read_csv_records(csv_file)
        else:
            records = []

        html    = render_html(records).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *args):
        pass    # Suppress default per-request logging noise


def main():
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    log.info(f"Dashboard starting on http://localhost:{DASHBOARD_PORT}")
    log.info("Open this URL in a browser — page auto-refreshes every 5 seconds.")
    with socketserver.TCPServer(("", DASHBOARD_PORT), DashboardHandler) as httpd:
        httpd.allow_reuse_address = True
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log.info("Dashboard stopped.")


if __name__ == "__main__":
    main()
