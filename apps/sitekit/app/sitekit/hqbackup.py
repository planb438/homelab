"""Nightly copy of the HQ Google Sheets into the lab (one .xlsx per sheet, all tabs).

Env:  HQ_SHEETS  lines of "Name|spreadsheetId"   (from the sealed secret)
      SA_FILE    path to the Google service-account JSON key (default /secrets/sa.json)
      OUT_DIR    where to write (default /backups);  KEEP_DAYS (default 30)
Each sheet must be shared (Viewer) with the service account's email.
"""
import os, re, shutil, sys
from datetime import date, datetime, timedelta

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def parse_sheets(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        name, sid = [x.strip() for x in line.rsplit("|", 1)]
        if re.fullmatch(r"[A-Za-z0-9_-]{20,}", sid):
            out.append((name, sid))
    return out


def safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:80] or "sheet"


def session(sa_file):
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_file(sa_file, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return AuthorizedSession(creds)


def prune(out_dir, keep_days, today):
    for d in os.listdir(out_dir):
        try:
            if datetime.strptime(d, "%Y-%m-%d").date() < today - timedelta(days=keep_days):
                shutil.rmtree(os.path.join(out_dir, d))
        except ValueError:
            pass


def run(sess, sheets, out_dir, keep_days=30, today=None):
    today = today or date.today()
    day = os.path.join(out_dir, today.isoformat())
    os.makedirs(day, exist_ok=True)
    ok, failed = 0, []
    for name, sid in sheets:
        r = sess.get(f"https://www.googleapis.com/drive/v3/files/{sid}/export", params={"mimeType": XLSX}, timeout=120)
        if r.status_code == 200:
            with open(os.path.join(day, safe(name) + ".xlsx"), "wb") as f:
                f.write(r.content)
            ok += 1
            print(f"saved  {name}")
        else:
            failed.append(name)
            print(f"FAILED {name}: HTTP {r.status_code} (is it shared with the service account?)")
    prune(out_dir, keep_days, today)
    print(f"{ok} saved, {len(failed)} failed -> {day}")
    return ok, failed


def main():
    sheets = parse_sheets(os.environ.get("HQ_SHEETS", ""))
    if not sheets:
        print("HQ_SHEETS is empty"); return 1
    ok, failed = run(session(os.environ.get("SA_FILE", "/secrets/sa.json")), sheets,
                     os.environ.get("OUT_DIR", "/backups"), int(os.environ.get("KEEP_DAYS", "30")))
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
