import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import glob

# --- Google Sheet Push Function (Silent Execution) ---
def push_latest_csv_to_google_sheet():
    try:
        csv_files = sorted(glob.glob("Rainfall_20*.csv"))
        if not csv_files:
            print("⚠️ No CSV files found.")
            return

        csv_file = csv_files[-1]
        date_str = os.path.splitext(csv_file)[0].split("_")[1]
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        tab_name = date_obj.strftime("%d %B")

        df = pd.read_csv(csv_file)

        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["google_sheets"], scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key("1S2npEHBjBn3e9xPuAnHOWF9NEWuTzEiAJpvEp4Gbnik")

        try:
            worksheet = spreadsheet.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=tab_name, rows="100", cols="30")

        worksheet.clear()
        worksheet.update([df.columns.tolist()] + df.values.tolist())
        print(f"✅ Pushed '{csv_file}' to Google Sheet tab '{tab_name}'")

    except Exception as e:
        print(f"❌ Error while pushing to Google Sheet: {e}")



# --- Run Silent Push ---
push_latest_csv_to_google_sheet()

# --- Streamlit Dashboard ---
st.set_page_config(page_title="Rainfall Dashboard", layout="wide")

# ----------- Language Toggle -----------
def label(key):
    return {
        "title": {"en": "🌧️ 2-Hourly Rainfall Dashboard", "gu": "🌧️ સાણ કાલાક વર્સાદ માહિતી ડૈશબોર્ડ"},
        "select_date": {"en": "🗓️ Select Date", "gu": "🗓️ તારીખ પસંદ કરો"},
        "select_taluka": {"en": "📍 Select Taluka", "gu": "📍 તાલુકા પસંદ કરો"},
        "selected_taluka": {"en": "Selected Taluka Overview", "gu": "📍 તાલુકા માહિતી"},
        "latest_slot": {"en": "Latest Time Slot", "gu": "⌚ છેલ્લો સમય ગાળો"},
        "last_rain": {"en": "Rain in Last 2 Hours", "gu": "🌧️ છેલાં 2 કાલાકમાં"},
        "total_today": {"en": "Total Rainfall Today", "gu": "💧 આજ સુધી કુલ વર્સાદ"},
        "max_today": {"en": "Highest rainfall taluka up to", "gu": "🌧️ અત્યાર સુધીમાં સાઉથી વધુ વર્સાદ થયેલો તાલુકો"},
        "max_2hr": {"en": "Top in Last 2 Hours", "gu": "⏱️ છેલાં 2 કાલાકમાં સાઉથી વધુ"},
        "chart_title": {"en": "Rainfall Trend (2-Hourly)", "gu": "🕒 સમયગાળાની સાથે વર્સાદ ગ્રાફ"},
        "table_title": {"en": "Full Day Table", "gu": "📋 સમગ્ર દિવસ માટે વિવરણ"},
        "top10_title": {"en": "Talukas with Highest Rainfall So Far", "gu": "📊 અત્યાર સુધીના વધુ વર્સાદ થયેલા તાલુકાવોં"},
        "footer": {"en": "Live data from Google Sheet.", "gu": "આ માહિતી Google Sheet થી લાઇવ અપડેટ થે શે."},
        "show_full_table": {"en": "Show Full Taluka Table", "gu": "બધા તાલુકાનું ટેબલ દે«6ાવો"}
    }.get(key, {}).get(lang, key)

def format_timeslot(slot):
    try:
        start, end = slot.split("–")
        s = datetime.strptime(start.replace("24", "00").zfill(2), "%H").strftime("%I:%M %p")
        e = datetime.strptime(end.replace("24", "00").zfill(2), "%H").strftime("%I:%M %p")
        return f"{s} – {e}"
    except:
        return slot

# ----------- Language Switcher -----------
lang = st.sidebar.radio("🌐 Language", options=["en", "gu"], format_func=lambda x: "English" if x == "en" else "ગુજરાતી")

# ----------- Data Loading -----------
sheet_url = "https://docs.google.com/spreadsheets/d/1S2npEHBjBn3e9xPuAnHOWF9NEWuTzEiAJpvEp4Gbnik/export?format=csv&gid=1849046072"
df_raw = pd.read_csv(sheet_url)
df_raw.columns = df_raw.columns.str.strip()

# ----------- Data Processing -----------
time_slots = ["06–08", "08–10", "10–12", "12–14", "14–16", "16–18", "18–20", "20–22"]
df = df_raw.melt(id_vars=["District", "Taluka"], value_vars=[col for col in time_slots if col in df_raw.columns],
                 var_name="Time Slot", value_name="Rain_2hr_mm")
df["Date"] = pd.to_datetime(datetime.now().date())
df["Rain_2hr_mm"] = pd.to_numeric(df["Rain_2hr_mm"], errors="coerce")
df.dropna(subset=["Rain_2hr_mm"], inplace=True)
df["Time Slot Label"] = df["Time Slot"].apply(format_timeslot)

# ----------- UI Controls -----------
st.title(label("title"))
selected_date = st.sidebar.selectbox(label("select_date"), sorted(df["Date"].dt.date.unique(), reverse=True))
selected_taluka = st.sidebar.selectbox(label("select_taluka"), sorted(df["Taluka"].unique()))
today_df = df[df["Date"].dt.date == selected_date]
filtered = today_df[today_df["Taluka"] == selected_taluka]

if filtered.empty:
    st.warning("No data available for this selection.")
    st.stop()

# ----------- Metrics -----------
latest = filtered.iloc[-1]
latest_slot = format_timeslot(latest["Time Slot"])
latest_rain = latest["Rain_2hr_mm"]
total_today = filtered["Rain_2hr_mm"].sum()

top_today = today_df.groupby("Taluka")["Rain_2hr_mm"].sum().sort_values(ascending=False)
top_taluka_today = top_today.index[0]
top_today_amount = top_today.iloc[0]

latest_interval = today_df["Time Slot"].max()
top_last2h = today_df[today_df["Time Slot"] == latest_interval].groupby("Taluka")["Rain_2hr_mm"].sum().sort_values(ascending=False)
top_taluka_2h = top_last2h.index[0]
top_2h_amount = top_last2h.iloc[0]

# ----------- Display Sections -----------
st.markdown("### 📍 " + label("selected_taluka"))
with st.container():
    col1, col2 = st.columns(2)
    col1.metric("📌 Taluka", selected_taluka)
    col2.metric("🧓 " + label("latest_slot"), latest_slot)

    col3, col4 = st.columns(2)
    col3.metric("🌧️ " + label("last_rain"), f"{latest_rain} mm")
    col4.metric("💧 " + label("total_today"), f"{total_today} mm")

st.markdown("---")
latest_time_label = format_timeslot(latest_interval).split("–")[1]
st.markdown(f"### 🏆 {label('max_today')} {latest_time_label} ({selected_date.strftime('%d %B %Y')})")
with st.container():
    col5, col6 = st.columns(2)
    col5.metric("🥇 Highest Total", f"{top_taluka_today} – {top_today_amount} mm")
    col6.metric("⏱️ " + label("max_2hr"), f"{top_taluka_2h} – {top_2h_amount} mm")

st.markdown("---")
st.subheader("📈 " + label("chart_title"))
chart = px.line(filtered, x="Time Slot Label", y="Rain_2hr_mm", markers=True,
                labels={"Time Slot Label": "Time Slot", "Rain_2hr_mm": "Rainfall (mm)"})
st.plotly_chart(chart, use_container_width=True)

st.subheader("📋 " + label("table_title"))
st.dataframe(filtered[["Time Slot Label", "Rain_2hr_mm"]].set_index("Time Slot Label"))

st.markdown("---")
with st.expander("🕺 " + label("show_full_table")):
    st.dataframe(df_raw.sort_values(by=["District", "Taluka"]).reset_index(drop=True))

st.markdown("---")
st.caption("📊 " + label("footer"))
