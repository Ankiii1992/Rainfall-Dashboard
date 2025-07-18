import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import os

# --- Streamlit page settings ---
st.set_page_config(page_title="Rainfall Dashboard", layout="wide")

# --- Enhanced CSS ---
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

    /* These CSS rules for the download button will likely NOT WORK if unsafe_allow_html=True */
    /* does not permit direct injection of elements to hide Streamlit's native components */
    .stDataFrame header {
        display: none !important;
    }
    [data-testid="stDataFrameToolbar"] button {
        display: none !important;
    }
    [data-testid="stDataFrameToolbar"] {
        display: none !important;
    }

</style>

<script>
    document.addEventListener('contextmenu', event => event.preventDefault());
</script>
""", unsafe_allow_html=True)


# --- Rainfall Category & Color Mapping (for Plotly map) ---
color_map = {
    "No Rain": "#f8f8f8",
    "Very Light": "#e0ffe0",
    "Light": "#00ff01",
    "Moderate": "#00ffff",
    "Rather Heavy": "#ffeb3b",
    "Heavy": "#ff8c00",
    "Very Heavy": "#d50000",
    "Extremely Heavy": "#f820fe",
    "Exceptional": "#e8aaf5"
}

category_ranges = {
    "No Rain": "0 mm",
    "Very Light": "0.1 – 2.4 mm",
    "Light": "2.5 – 7.5 mm",
    "Moderate": "7.6 – 35.5 mm",
    "Rather Heavy": "35.6 – 64.4 mm",
    "Heavy": "64.5 – 124.4 mm",
    "Very Heavy": "124.5 – 244.4 mm",
    "Extremely Heavy": "244.5 – 350 mm",
    "Exceptional": "> 350 mm"
}

def classify_rainfall(rainfall):
    if pd.isna(rainfall) or rainfall == 0:
        return "No Rain"
    elif rainfall > 0 and rainfall <= 2.4:
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

# Ensure the order of categories for the Plotly color scale and legend
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
df = data_by_date[selected_tab].copy()
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
df['Total_mm'] = pd.to_numeric(df['Total_mm'], errors='coerce')
top_taluka_row = df.sort_values(by='Total_mm', ascending=False).iloc[0] if not df['Total_mm'].dropna().empty else pd.Series({'Taluka': 'N/A', 'Total_mm': 0})
df_latest_slot = df_long[df_long['Time Slot'] == existing_order[-1]]
top_latest = df_latest_slot.sort_values(by='Rainfall (mm)', ascending=False).iloc[0] if not df_latest_slot['Rainfall (mm)'].dropna().empty else pd.Series({'Taluka': 'N/A', 'Rainfall (mm)': 0})
num_talukas_with_rain_today = df[df['Total_mm'] > 0].shape[0]
more_than_150 = df[df['Total_mm'] > 150].shape[0]
more_than_100 = df[df['Total_mm'] > 100].shape[0]
more_than_50 = df[df['Total_mm'] > 50].shape[0]

st.markdown(f"#### 📊 Latest data available for time interval: **{slot_labels[existing_order[-1]]}**")

# --- Metric Tiles ---
st.markdown("### Overview")
row1 = st.columns(3)
row2 = st.columns(3)

last_slot_label = slot_labels[existing_order[-1]]

row1_titles = [
    ("Total Talukas with Rainfall", num_talukas_with_rain_today),
    ("Top Taluka by Total Rainfall", f"{top_taluka_row['Taluka']}<br><p>{top_taluka_row['Total_mm']:.1f} mm</p>"),
    (f"Top Taluka in last 2 hour({last_slot_label})", f"{top_latest['Taluka']}<br><p>{top_latest['Rainfall (mm)']:.1f} mm</p>")
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


# --- Reordered Chart Sections ---

# --- Rainfall Distribution Overview (Map and Insights) ---
st.markdown("### 🗺️ Rainfall Distribution Overview")

taluka_geojson = load_geojson("gujarat_taluka_clean.geojson")

if taluka_geojson:
    # Prepare df_map (using the original df to get categories as per the latest clarification)
    for feature in taluka_geojson["features"]:
        feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()

    df_map = df.copy()
    df_map["Taluka"] = df_map["Taluka"].str.strip().str.lower()
    df_map["Rainfall Category"] = df_map["Total_mm"].apply(classify_rainfall)
    df_map["Rainfall Category"] = pd.Categorical(
        df_map["Rainfall Category"],
        categories=ordered_categories,
        ordered=True
    )
    # Add rainfall range to df_map for hover text (only for the bar chart now)
    df_map["Rainfall Range"] = df_map["Rainfall Category"].map(category_ranges)


    # Create columns for the side-by-side layout (NOW 0.5, 0.5)
    map_col, insights_col = st.columns([0.5, 0.5])

    with map_col:
        st.markdown("#### Gujarat Rainfall Map (by Taluka)")
        fig_map = px.choropleth_mapbox(
            df_map,
            geojson=taluka_geojson,
            featureidkey="properties.SUB_DISTRICT",
            locations="Taluka",
            color="Rainfall Category",
            color_discrete_map=color_map,
            mapbox_style="open-street-map",
            center={"lat": 22.5, "lon": 71.5},
            zoom=6,
            opacity=0.75,
            height=650,
            hover_name="Taluka",
            hover_data={
                "District": True,
                "Total_mm": ":.1f mm", # Format Total_mm in hover
                "Rainfall Category": False, # DO NOT show Rainfall Category in map hover
                "Rainfall Range": False # DO NOT show Rainfall Range in map hover
            },
            title="Gujarat Rainfall Distribution by Taluka"
        )

        # Plotly Express map legend customization
        fig_map.update_layout(
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.15,
                xanchor="center",
                x=0.5,
                title_text="Rainfall Categories (mm)",
                font=dict(size=10),
                itemsizing='constant',
            )
        )
        st.plotly_chart(fig_map, use_container_width=True)

    with insights_col:
        st.markdown("#### Key Insights & Distributions")

        # --- Donut Chart for Percentage of Talukas with Rainfall ---
        TOTAL_TALUKAS_GUJARAT = 251 # Constant for total talukas
        talukas_without_rain = TOTAL_TALUKAS_GUJARAT - num_talukas_with_rain_today

        donut_data = pd.DataFrame({
            'Category': ['Talukas with Rainfall', 'Talukas without Rainfall'],
            'Count': [num_talukas_with_rain_today, talukas_without_rain]
        })

        fig_donut = px.pie(
            donut_data,
            values='Count',
            names='Category',
            title="Percentage of Talukas with Rainfall Today",
            hole=0.5,
            color='Category',
            color_discrete_map={
                'Talukas with Rainfall': '#28a745', # Green
                'Talukas without Rainfall': '#dc3545' # Red
            }
        )
        fig_donut.update_traces(textinfo='percent+label', pull=[0.05 if cat == 'Talukas with Rainfall' else 0 for cat in donut_data['Category']])
        fig_donut.update_layout(showlegend=False, height=300, margin=dict(l=0, r=0, t=50, b=0))
        st.plotly_chart(fig_donut, use_container_width=True)

        # --- Distribution of Talukas by Rainfall Category (Bar Chart) ---
        category_counts = df_map['Rainfall Category'].value_counts().reset_index()
        category_counts.columns = ['Category', 'Count']
        category_counts['Category'] = pd.Categorical(
            category_counts['Category'],
            categories=ordered_categories,
            ordered=True
        )
        category_counts = category_counts.sort_values('Category')
        # Add Rainfall Range to category_counts for hover
        category_counts['Rainfall Range'] = category_counts['Category'].map(category_ranges)


        fig_category_dist = px.bar(
            category_counts,
            x='Category',
            y='Count',
            title='Distribution of Talukas by Rainfall Category',
            labels={'Count': 'Number of Talukas'},
            color='Category',
            color_discrete_map=color_map,
            hover_data={
                'Category': True, # Show Category in hover
                'Rainfall Range': True, # Show Rainfall Range in hover
                'Count': True # Show Count in hover
            }
        )
        # Update x-axis tick labels to show only category names, no ranges
        fig_category_dist.update_layout(
            xaxis=dict(
                tickmode='array',
                tickvals=category_counts['Category'],
                ticktext=[cat for cat in category_counts['Category']], # Only category name
                tickangle=0 # Ensure horizontal display
            ),
            xaxis_title=None,
            showlegend=False,
            height=350,
            margin=dict(l=0, r=0, t=50, b=0)
        )
        st.plotly_chart(fig_category_dist, use_container_width=True)


else:
    st.error("❌ GeoJSON file (gujarat_taluka_clean.geojson) not found. Please ensure it's in the same directory as your app.")

# --- Top 10 Talukas by Total Rainfall (Bar Chart) ---
st.markdown("### 🏆 Top 10 Talukas by Total Rainfall")
df_top_10 = df.dropna(subset=['Total_mm']).sort_values(by='Total_mm', ascending=False).head(10)

if not df_top_10.empty:
    fig_top_10 = px.bar(
        df_top_10,
        x='Taluka',
        y='Total_mm',
        color='Total_mm', # Reverted to color by rainfall amount
        color_continuous_scale=px.colors.sequential.Bluyl, # Using a continuous scale
        labels={'Total_mm': 'Total Rainfall (mm)'},
        hover_data=['District'],
        text='Total_mm',
        title='Top 10 Talukas with Highest Total Rainfall'
    )
    fig_top_10.update_traces(texttemplate='%{text:.1f}', textposition='outside')
    fig_top_10.update_layout(
        xaxis_tickangle=-45,
        showlegend=False, # Ensure no discrete legend
        margin=dict(t=50),
        coloraxis_showscale=False # HIDE THE CONTINUOUS COLOR BAR LEGEND
    )
    st.plotly_chart(fig_top_10, use_container_width=True)
else:
    st.info("No rainfall data available to determine top 10 talukas.")


# --- Rainfall Trend by 2 hourly Time Interval (Line Chart) ---
st.markdown("### 📈 Rainfall Trend by 2 hourly Time Interval")
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
else:
    st.info("Please select at least one Taluka to view the rainfall trend.")


# --- Table Section ---
st.markdown("### 📋 Full Rainfall Data Table")
df_display = df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
df_display.index += 1
st.dataframe(df_display, use_container_width=True, height=600)
