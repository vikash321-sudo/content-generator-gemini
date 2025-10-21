import os, gspread, json
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

cred_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH")
creds = ServiceAccountCredentials.from_json_keyfile_name(cred_path, scope)
client = gspread.authorize(creds)

# Debug: show which service account is being used
with open(cred_path, "r") as f:
    svc = json.load(f)
print("Using service account:", svc.get("client_email"))

SPREADSHEET_ID = "1XtlJIpOMxPVqml8T--TYnb569Z445OiwmoyyhxMbn-Y"
sh = client.open_by_key(SPREADSHEET_ID)
ws = sh.sheet1
# Add headers once if empty
if not ws.get_all_values():
    ws.append_row(["Topic", "Tone", "Output"])
ws.append_row(["Test topic", "Professional", "Row added via service account ✅"])
print("✅ Appended a row to your existing Sheet successfully!")