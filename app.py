import streamlit as st
import pandas as pd
import plotly.express as px
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import os

# --- Streamlit page settings ---
st.set_page_config(page_title="Rainfall Dashboard", layout="wide")

# --- Custom CSS for UI and to disable right-click and dataframe download button ---
st.markdown("""
<style>
    html, body, .main {
        background-color: #f3f6fa;
        font-family: 'Segoe UI', sans-serif;
    }
    .title-text {
        font-size: 2.8rem;
        font-weight: 800;
        color: #1a237e;
        padding: 1rem 0 0.2rem 0;
    }
    .metric-container {
        padding: 0.8rem;
    }
    .metric-tile {
        background: linear-gradient(135deg, #f0faff, #e0f2f1);
        padding: 1.2rem 1.4rem 1rem 1.4rem;
        border-radius: 1.25rem;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.06);
        text-align: center;
        transition: 0.3s ease;
        border: 1px solid #c5e1e9;
        height: 165px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .metric-tile:hover {
        transform: translateY(-4px);
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.1);
    }
    .metric-tile h4 {
        color: #01579b;
        font-size: 1.05rem;
        margin-bottom: 0.2rem;
    }
    .metric-tile h2 {
        font-size: 2.2rem;
        color: #0077b6;
        margin: 0.1rem 0 0.1rem 0;
        font-weight: 700;
    }
    .metric-tile p {
        margin: 0 0 0;
        font-size: 0.95rem;
        color: #37474f;
    }
    /* Hide the download button from st.dataframe */
    [data-testid="stElementToolbar"] {
        display: none;
    }
    /* Custom legend styling */
    .legend-container {
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
        margin-top: 1.5rem;
        padding: 1rem;
        background-color: #ffffff;
        border-radius: 0.75rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    }
    .legend-item {
        display: flex;
        align-items: center;
        margin: 0.5rem 1rem;
        font-size: 0.9rem;
        color: #37474f;
    }
    .legend-color-box {
        width: 20px;
        height: 20px;
        border-radius: 4px;
        margin-right: 0.7rem;
        border: 1px solid rgba(0,0,0,0.1);
    }
</style>

<script>
    document.addEventListener('contextmenu', event => event.preventDefault());
</script>
""", unsafe_allow_html=True)


# --- Rainfall Category & Color Mapping ---
category_colors = {
    "Very Light": "#c8e6c9",    # Light Green
    "Light": "#00ff01",         # Bright Green
    "Moderate": "#ffff00",      # Yellow
    "Rather Heavy": "#ffa500",  # Orange
    "Heavy": "#d61a1c",         # Red
    "Very Heavy": "#3b0030",    # Dark Purple
    "Extremely Heavy": "#4c0073", # Deeper Purple
    "Exceptional": "#ffdbff"    # Light Pink/Magenta
}

category_ranges = {
    "Very Light": "0.1 – 2.4 mm",
    "Light": "2.5 – 7.5 mm",
    "Moderate": "7.6 – 35.5 mm",
    "Rather Heavy": "35.6 – 64.4 mm",
    "Heavy": "64.5 – 124.4 mm",
    "Very Heavy": "124.5 – 244.4 mm",
    "Extremely Heavy": "244.5 – 350 mm",
    "Exceptional": "> 350 mm"
}

def categorize_rainfall(rainfall):
    if pd.isna(rainfall) or rainfall == 0: # Explicitly handle 0 and NA for "No Rain"
        return "No Rain" # Assign a "No Rain" category
    elif rainfall <= 2.4:
        return "Very Light"
    elif rainfall <= 7.5:
        return "Light"
    elif rainfall <= 35.5:
        return "Moderate"
    elif rainfall <= 64.4:
        return "Rather Heavy"
    elif rainfall <= 124.4:
        return "Heavy"
    elif rainfall <= 244.4:
        return "Very Heavy"
    elif rainfall <= 350:
        return "Extremely Heavy"
    else:
        return "Exceptional"

# Add "No Rain" to the category_colors if you want it explicitly mapped on the map (e.g., to grey)
# If not, talukas with 0 rainfall will simply not be colored by the choropleth color scale.
# For the purpose of the map legend, it's good to include it if you expect to show it.
# Let's define it as a light grey.
category_colors["No Rain"] = "#f0f0f0" # A very light grey for no rain
category_ranges["No Rain"] = "0 mm"

# Ensure the order of categories for the Plotly color scale and custom legend
# This is important for consistent visual representation
ordered_categories = [
    "No Rain", "Very Light", "Light", "Moderate", "Rather Heavy",
    "Heavy", "Very Heavy", "Extremely Heavy", "Exceptional"
]

# --- Load all sheet tabs (cached) ---
@st.cache_data
def load_all_sheet_tabs():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open("Rainfall Dashboard")
    sheet_tabs = spreadsheet.worksheets()

    data_by_date = {}
    for tab in sheet_tabs:
        tab_name = tab.title
        data = tab.get_all_values()
        if not data or len(data) < 2:
            continue

        df = pd.DataFrame(data[1:], columns=data[0])
        df.replace("", pd.NA, inplace=True)
        df = df.dropna(how="all")
        df.columns = df.columns.str.strip()

        df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka", "TOTAL": "Total_mm"}, inplace=True)

        if "Total_mm" in df.columns:
            df["Total_mm"] = pd.to_numeric(df["Total_mm"], errors="coerce")

        for col in df.columns:
            if "TO" in col:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        data_by_date[tab_name] = df

    return data_by_date

# --- Load GeoJSON (cached resource) ---
@st.cache_resource
def load_geojson(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        return geojson_data
    return None

# --- Load data ---
data_by_date = load_all_sheet_tabs()
available_dates = sorted(
    data_by_date.keys(),
    key=lambda d: datetime.strptime(d, "%d-%m-%Y"),
    reverse=True
)

st.markdown("<div class='title-text'>🌧️ Gujarat Rainfall Dashboard</div>", unsafe_allow_html=True)

selected_tab = st.selectbox("🗕️ Select Date", available_dates, index=0)
df = data_by_date[selected_tab].copy() # Make a copy to avoid SettingWithCopyWarning
df.columns = df.columns.str.strip()

time_slot_columns = [col for col in df.columns if "TO" in col]
time_slot_order = ['06TO08', '08TO10', '10TO12', '12TO14', '14TO16', '16TO18',
                    '18TO20', '20TO22', '22TO24', '24TO02', '02TO04', '04TO06']
existing_order = [slot for slot in time_slot_order if slot in time_slot_columns]

slot_labels = {
    "06TO08": "6–8 AM",
    "08TO10": "8–10 AM",
    "10TO12": "10–12 AM",
    "12TO14": "12–2 PM",
    "14TO16": "2–4 PM",
    "16TO18": "4–6 PM",
    "18TO20": "6–8 PM",
    "20TO22": "8–10 PM",
    "22TO24": "10–12 PM",
    "24TO02": "12–2 AM",
    "02TO04": "2–4 AM",
    "04TO06": "4–6 AM",
}

# Melt and clean data
df_long = df.melt(
    id_vars=["District", "Taluka", "Total_mm"],
    value_vars=existing_order,
    var_name="Time Slot",
    value_name="Rainfall (mm)"
)
df_long = df_long.dropna(subset=["Rainfall (mm)"])
df_long['Taluka'] = df_long['Taluka'].str.strip()
df_long = df_long.groupby(["District", "Taluka", "Time Slot"], as_index=False).agg({
    "Rainfall (mm)": "sum",
    "Total_mm": "first"
})

df_long['Time Slot Label'] = pd.Categorical(
    df_long['Time Slot'].map(slot_labels),
    categories=[slot_labels[slot] for slot in existing_order],
    ordered=True
)
df_long = df_long.sort_values(by=["Taluka", "Time Slot Label"])

# --- Metrics ---
# Ensure Total_mm is numeric for sorting, even if there are NAs for some rows
df['Total_mm'] = pd.to_numeric(df['Total_mm'], errors='coerce')
top_taluka_row = df.sort_values(by='Total_mm', ascending=False).iloc[0] if not df['Total_mm'].dropna().empty else pd.Series({'Taluka': 'N/A', 'Total_mm': 0})

df_latest_slot = df_long[df_long['Time Slot'] == existing_order[-1]]
top_latest = df_latest_slot.sort_values(by='Rainfall (mm)', ascending=False).iloc[0] if not df_latest_slot['Rainfall (mm)'].dropna().empty else pd.Series({'Taluka': 'N/A', 'Rainfall (mm)': 0})

num_talukas_with_rain = df[df['Total_mm'] > 0].shape[0]
more_than_150 = df[df['Total_mm'] > 150].shape[0]
more_than_100 = df[df['Total_mm'] > 100].shape[0]
more_than_50 = df[df['Total_mm'] > 50].shape[0]

st.markdown(f"#### 📊 Latest data available for time slot: **{slot_labels[existing_order[-1]]}**")

# --- Metric Tiles ---
st.markdown("### Overview")
row1 = st.columns(3)
row2 = st.columns(3)

# Get label for the latest slot
last_slot_label = slot_labels[existing_order[-1]]

# Metric tiles
row1_titles = [
    ("Total Talukas with Rainfall", num_talukas_with_rain),
    ("Highest Rainfall Total", f"{top_taluka_row['Taluka']}<br><p>{top_taluka_row['Total_mm']} mm</p>"),
    (f"Highest Rainfall in Last 2 Hours ({last_slot_label})", f"{top_latest['Taluka']}<br><p>{top_latest['Rainfall (mm)']} mm</p>")
]

row2_titles = [
    ("Talukas > 150 mm", more_than_150),
    ("Talukas > 100 mm", more_than_100),
    ("Talukas > 50 mm", more_than_50)
]

for col, (label, value) in zip(row1, row1_titles):
    with col:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>{label}</h4><h2>{value}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

for col, (label, value) in zip(row2, row2_titles):
    with col:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>{label}</h4><h2>{value}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

# --- Chart Section ---
st.markdown("### 📈 Rainfall Trend by Time Slot")
selected_talukas = st.multiselect("Select Taluka(s)", sorted(df_long['Taluka'].unique()), default=[top_taluka_row['Taluka']])

if selected_talukas:
    plot_df = df_long[df_long['Taluka'].isin(selected_talukas)]
    fig = px.line(
        plot_df,
        x="Time Slot Label",
        y="Rainfall (mm)",
        color="Taluka",
        markers=True,
        text="Rainfall (mm)",
        title="Rainfall Trend Over Time",
        labels={"Rainfall (mm)": "Rainfall (mm)"}
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(showlegend=True)
    fig.update_layout(modebar_remove=['toImage'])
    st.plotly_chart(fig, use_container_width=True)

# --- Choropleth Map Section ---
st.markdown("### 🗺️ Gujarat Rainfall Map (by Taluka)")

taluka_geojson = load_geojson("gujarat_taluka_clean.geojson")

if taluka_geojson:
    # Normalize names in both GeoJSON and DataFrame
    for feature in taluka_geojson["features"]:
        feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()

    df_map = df.copy()
    df_map["Taluka"] = df_map["Taluka"].str.strip().str.lower()

    # Apply new categorization
    df_map["Rainfall Category"] = df_map["Total_mm"].apply(categorize_rainfall)

    # Convert 'Rainfall Category' to a categorical type with defined order
    df_map["Rainfall Category"] = pd.Categorical(
        df_map["Rainfall Category"],
        categories=ordered_categories,
        ordered=True
    )

    fig = px.choropleth_mapbox(
        df_map,
        geojson=taluka_geojson,
        featureidkey="properties.SUB_DISTRICT",
        locations="Taluka",
        color="Rainfall Category",
        color_discrete_map=category_colors, # Use your custom colors
        mapbox_style="open-street-map",
        center={"lat": 22.5, "lon": 71.5},
        zoom=6,
        opacity=0.75,
        height=650,
        hover_name="Taluka",
        hover_data=["District", "Total_mm"],
        title="Gujarat Rainfall Distribution by Taluka"
    )
    fig.update_layout(
        margin={"r": 0, "t": 40, "l": 0, "b": 0}, # Adjusted top margin for title
        # Remove Plotly's default legend as we'll create a custom one
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Custom Legend below the map ---
    st.markdown("#### Rainfall Categories (mm)")
    legend_html = "<div class='legend-container'>"
    for category in ordered_categories:
        color = category_colors.get(category, "#CCCCCC") # Default grey if color not found
        range_str = category_ranges.get(category, "")
        legend_html += f"""
        <div class='legend-item'>
            <div class='legend-color-box' style='background-color: {color};'></div>
            <b>{category}:</b> {range_str}
        </div>
        """
    legend_html += "</div>"
    st.markdown(legend_html, unsafe_allow_html=True)


else:
    st.error("❌ GeoJSON file (gujarat_taluka_clean.geojson) not found. Please ensure it's in the same directory as your app.")

# --- Table Section ---
st.markdown("### 📋 Full Rainfall Data Table")
df_display = df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
df_display.index += 1
st.dataframe(df_display, use_container_width=True, height=600)
