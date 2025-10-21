import os
import time
import textwrap
import datetime as dt
import streamlit as st
import google.generativeai as gen
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# --------------------------
# Setup & Env
# --------------------------
st.set_page_config(page_title="Content Studio", page_icon="🧠", layout="wide")
load_dotenv()

# Required
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
SHEET_ID   = os.getenv("SHEET_ID")
CRED_PATH  = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "./credentials.json")

# Optional branding/auth
BRAND_NAME = os.getenv("BRAND_NAME", "BizConvert")
ACCENT_HEX = os.getenv("ACCENT_HEX", "#E11D48")  # rose-600
LOGO_PATH  = os.getenv("LOGO_PATH", "")
PASSCODE   = os.getenv("APP_PASSCODE", "")

if not GEMINI_KEY:
    st.error("GEMINI_API_KEY missing in .env")
    st.stop()
if not SHEET_ID:
    st.error("SHEET_ID missing in .env")
    st.stop()

gen.configure(api_key=GEMINI_KEY)

# --------------------------
# Simple Auth Gate (optional)
# --------------------------
if PASSCODE:
    with st.sidebar:
        st.subheader("🔒 Access")
        code = st.text_input("Passcode", type="password")
        if st.button("Unlock"):
            st.session_state.get("unlocked") or st.session_state.update(unlocked=False)
            st.session_state.unlocked = (code == PASSCODE)
        if not st.session_state.get("unlocked", False):
            st.stop()

# --------------------------
# Styling
# --------------------------
CUSTOM_CSS = f"""
<style>
:root {{
  --accent: {ACCENT_HEX};
}}
.block-container {{
  padding-top: 1.6rem;
}}
h1, h2, h3, .stButton>button {{
  color: var(--accent);
}}
.stButton>button {{
  border: 1px solid var(--accent);
}}
.footer-note {{
  margin-top: 1rem; font-size: 12px; opacity: 0.8;
}}
.badge {{
  display:inline-block; padding:4px 8px; border-radius:8px; 
  background: rgba(225,29,72,0.08); color: var(--accent); 
  border: 1px solid rgba(225,29,72,0.3);
  font-size:12px; margin-left:8px;
}}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

logo_col, title_col = st.columns([1,5])
with logo_col:
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_container_width=True)
with title_col:
    st.markdown(f"## 🧠 {BRAND_NAME} — Content Studio <span class='badge'>Gemini</span>", unsafe_allow_html=True)
    st.caption("Generate on-brand content and auto-log to Google Sheets.")

# --------------------------
# Google Sheets
# --------------------------
def _sheet():
    scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CRED_PATH, scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1
    if not ws.get_all_values():
        ws.append_row(["Timestamp","Model","Temperature","Type","Template","Topic","Tone","Length","Variant","Output"])
    return ws

# --------------------------
# Templates
# --------------------------
TEMPLATES = {
    "None (custom)": "",
    "Real-Estate": "Audience: home buyers or sellers. Include neighborhood benefits, property features, and a clear CTA to schedule a viewing.",
    "E-commerce": "Audience: online shoppers. Highlight benefits, social proof, limited-time offers, and a CTA to buy now.",
    "Fitness": "Audience: beginners. Emphasize transformation, habit-building tips, and a CTA to start a plan today.",
    "Travel": "Audience: budget travelers. Include local highlights, hidden gems, best season, and a CTA to book.",
    "SaaS": "Audience: SMB teams. Stress pain→solution, 3 key features, 1 mini case-study line, and CTA for free trial.",
    "Coaching": "Audience: professionals. Clarify desired outcomes, program structure, and CTA to book a discovery call."
}

# --------------------------
# Helpers
# --------------------------
def clean_text(s: str) -> str:
    s = (s or "").strip()
    return s.replace("\r\n","\n").strip()

def build_prompt(topic: str, ctype: str, tone: str, length: int, extra: str, template: str) -> str:
    sys = (
        f"You are a concise, conversion-focused copywriter. Produce {ctype.lower()} with a strong hook, "
        "clear structure, and a compelling call-to-action. Keep it helpful and readable for a general audience."
    )
    guide = (
        f"\n\nTopic: {topic}\nTone/Style: {tone}\nTarget Length (approx words): {length}\n"
        "Formatting: short paragraphs or bullet points when useful."
    )
    if template and template != "None (custom)":
        guide += f"\nTemplate Hints: {TEMPLATES.get(template,'').strip()}"
    if extra.strip():
        guide += f"\nExtra Instructions: {extra.strip()}"
    return f"{sys}\n{guide}\n\nWrite it now."

def gemini_generate(model_name: str, prompt: str, temperature: float):
    mdl = gen.GenerativeModel(model_name)
    return mdl.generate_content(prompt, generation_config={"temperature": temperature})

def gemini_generate_with_backoff(model_name: str, prompt: str, temperature: float,
                                 retries: int = 3, base_wait: float = 4.0) -> str:
    for i in range(retries + 1):
        try:
            resp = gemini_generate(model_name, prompt, temperature)
            out = getattr(resp, "text", "") or ""
            if out.strip():
                return clean_text(out)
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "quota" in msg:
                # Friendly rate-limit banner
                st.warning(f"Rate limit hit. Cooling down… ({i+1}/{retries})")
                time.sleep(base_wait * (2 ** i))  # 4s, 8s, 16s…
                continue
            raise
    return "(No output — please try again shortly.)"

def save_variants_to_sheet(ws, model_name, temperature, ctype, template, topic, tone, length, variants):
    ts = dt.datetime.now().isoformat(timespec="seconds")
    for idx, text in enumerate(variants, start=1):
        ws.append_row([ts, model_name, temperature, ctype, template, topic, tone, length, idx, text])

def read_recent_history(ws, limit=25):
    values = ws.get_all_values()
    if len(values) <= 1:
        return []
    header, rows = values[0], values[1:]
    rows = rows[-limit:]
    return [dict(zip(header, r)) for r in rows]

# --------------------------
# Sidebar
# --------------------------
with st.sidebar:
    st.subheader("⚙️ Settings")
    model = st.selectbox("Model", ["gemini-2.5-flash", "gemini-2.5-pro"], index=0)
    temperature = st.slider("Creativity (temperature)", 0.0, 1.0, 0.5, 0.1)
    n_variants = st.radio("Variants", [1, 2, 3], index=0, horizontal=True)
    st.markdown("---")
    try:
        ws = _sheet()
        st.success("Connected to Google Sheet ✅")
    except Exception as e:
        st.error(f"Sheet error: {e}")
        st.stop()
    st.markdown("<div class='footer-note'>© "
                f"{dt.datetime.now().year} {BRAND_NAME}. All rights reserved.</div>", unsafe_allow_html=True)

# --------------------------
# Form
# --------------------------
col1, col2 = st.columns(2)
with col1:
    ctype = st.selectbox(
        "Content Type",
        ["Ad Copy", "Instagram Caption", "LinkedIn Post", "Blog Intro", "Email Promo", "Product Description", "YouTube Description"],
        index=0
    )
    tone  = st.selectbox("Tone / Style", ["Professional", "Friendly", "Bold", "Funny", "Motivational", "Persuasive"], index=0)
with col2:
    length = st.slider("Approx Length (words)", 50, 600, 140, step=10)
template = st.selectbox("Template Preset (optional)", list(TEMPLATES.keys()), index=0)
topic = st.text_input("Topic / Offer / Idea", placeholder="e.g., AI tools for small businesses")
extra = st.text_area("Extra Instructions (optional)", placeholder="Audience, CTA, keywords, structure…", height=120)

go = st.button("🚀 Generate Content", type="primary")

# --------------------------
# Generate & Save
# --------------------------
if go:
    if not topic.strip():
        st.error("Please enter a topic.")
    else:
        prompt = build_prompt(topic.strip(), ctype, tone, int(length), extra, template)
        st.info("Generating with Gemini…")
        variants = []
        try:
            for i in range(int(n_variants)):
                txt = gemini_generate_with_backoff(model, prompt, float(temperature))
                variants.append(txt if txt else "(No output)")
                if i < n_variants - 1:
                    time.sleep(2.5)  # gentle pacing
            save_variants_to_sheet(ws, model, temperature, ctype, template, topic.strip(), tone, int(length), variants)
            st.success("Saved to Google Sheet ✅")
        except Exception as e:
            st.error(f"Generation failed: {e}")

        if variants:
            st.markdown("### ✍️ Generated Content")
            for i, v in enumerate(variants, start=1):
                st.markdown(f"**Variant {i}**")
                st.write(v)
                st.download_button(
                    label=f"Download Variant {i} (.txt)",
                    data=v.encode("utf-8"),
                    file_name=f"{ctype.replace(' ','_').lower()}_{i}.txt",
                    mime="text/plain",
                    use_container_width=True
                )
                st.markdown("---")

# --------------------------
# History
# --------------------------
with st.expander("📜 History (last 25 rows)"):
    try:
        import pandas as pd
        history = read_recent_history(ws, limit=25)
        if not history:
            st.write("No rows yet.")
        else:
            df = pd.DataFrame(history)
            df["Output"] = df["Output"].apply(lambda t: (t[:120] + "…") if len(t) > 140 else t)
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not load history: {e}")
