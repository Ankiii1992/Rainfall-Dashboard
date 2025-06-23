import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Rainfall Dashboard", layout="wide")

# ----------- Language Toggle -----------
def label(key):
    return {
        "title": {"en": "🌧️ 2-Hourly Rainfall Dashboard", "gu": "🌧️ ૨ કલાકનું વરસાદ માહિતી ડૅશબોર્ડ"},
        "select_date": {"en": "📅 Select Date", "gu": "📅 તારીખ પસંદ કરો"},
        "select_taluka": {"en": "📍 Select Taluka", "gu": "📍 Taluka પસંદ કરો"},
        "selected_taluka": {"en": "Selected Taluka Overview", "gu": "📍 Taluka માહિતી"},
        "latest_slot": {"en": "Latest Time Slot", "gu": "⏰ છેલ્લો સમયગાળો"},
        "last_rain": {"en": "Rain in Last 2 Hours", "gu": "🌧️ છેલ્લાં 2 કલાકમાં"},
        "total_today": {"en": "Total Rainfall Today", "gu": "💧 આજ સુધી કુલ વરસાદ"},
        "max_today": {"en": "Highest rainfall taluka up to", "gu": "🌧️ અત્યાર સુધીમાં સૌથી વધુ વરસાદ થયેલો તાલુકો"},
        "max_2hr": {"en": "Top in Last 2 Hours", "gu": "⏱️ છેલ્લાં 2 કલાકમાં સૌથી વધુ"},
        "chart_title": {"en": "Rainfall Trend (2-Hourly)", "gu": "🕒 સમયગાળાની સાથે વરસાદ ગ્રાફ"},
        "table_title": {"en": "Full Day Table", "gu": "📋 સમગ્ર દિવસ માટે વિગતો"},
        "top10_title": {"en": "Talukas with Highest Rainfall So Far", "gu": "📊 અત્યાર સુધીના ટોચના તાલુકાઓ"},
        "footer": {"en": "Live data from Google Sheet.", "gu": "આ માહિતી Google Sheet પરથી લાઈવ અપડેટ થાય છે."},
        "show_full_table": {"en": "Show Full Taluka Table", "gu": "બધા તાલુકાનું ટેબલ જુઓ"}
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

# ----------- Data Loading and Processing -----------
sheet_url = "https://docs.google.com/spreadsheets/d/1S2npEHBjBn3e9xPuAnHOWF9NEWuTzEiAJpvEp4Gbnik/export?format=csv&gid=1849046072"
df_raw = pd.read_csv(sheet_url)
df_raw.columns = df_raw.columns.str.strip()

# Debug column names
#st.sidebar.write("🧾 Columns found in sheet:", df_raw.columns.tolist())

# Define 2-hour time slot columns
  time_slots = ["06–08", "08–10", "10–12", "12–14", "14–16", "16–18", "18–20", "20–22"]

# Melt wide to long (avoid conflict with existing "Rain_mm" or "Total_mm")
df = df_raw.melt(
    id_vars=["District", "Taluka"],
    value_vars=[col for col in time_slots if col in df_raw.columns],
    var_name="Time Slot",
    value_name="Rain_2hr_mm"
)

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

# Selected Taluka Overview
st.markdown("### 📍 " + label("selected_taluka"))
with st.container():
    col1, col2 = st.columns(2)
    col1.metric("📌 Taluka", selected_taluka)
    col2.metric("🕒 " + label("latest_slot"), latest_slot)

    col3, col4 = st.columns(2)
    col3.metric("🌧️ " + label("last_rain"), f"{latest_rain} mm")
    col4.metric("💧 " + label("total_today"), f"{total_today} mm")

# Highest Taluka Summary
st.markdown("---")
latest_time_label = format_timeslot(latest_interval).split("–")[1]
st.markdown(f"### 🏆 {label('max_today')} {latest_time_label} ({selected_date.strftime('%d %B %Y')})")
with st.container():
    col5, col6 = st.columns(2)
    col5.metric("🥇 Highest Total", f"{top_taluka_today} – {top_today_amount} mm")
    col6.metric("⏱️ " + label("max_2hr"), f"{top_taluka_2h} – {top_2h_amount} mm")

# Trend Chart
st.markdown("---")
st.subheader("📈 " + label("chart_title"))
chart = px.line(filtered, x="Time Slot Label", y="Rain_2hr_mm", markers=True,
                labels={"Time Slot Label": "Time Slot", "Rain_2hr_mm": "Rainfall (mm)"})
st.plotly_chart(chart, use_container_width=True)

# Taluka Day Table
st.subheader("📋 " + label("table_title"))
st.dataframe(filtered[["Time Slot Label", "Rain_2hr_mm"]].set_index("Time Slot Label"))

# Expandable Full Table in Original Format (Wide CSV Style)
st.markdown("---")
with st.expander("🔽 " + label("show_full_table")):
    st.dataframe(
        df_raw.sort_values(by=["District", "Taluka"]).reset_index(drop=True)
    )

# Footer
st.markdown("---")
st.caption("📊 " + label("footer"))
