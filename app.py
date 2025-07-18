import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go # Import plotly.graph_objects for fine control
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import os

# --- Streamlit page settings ---
st.set_page_config(page_title="Rainfall Dashboard", layout="wide")

# --- Enhanced CSS (Still apply this, assuming it works for general styling) ---
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
    "No Rain": "#f0f0f0",
    "Very Light": "#c8e6c9",
    "Light": "#00ff01",
    "Moderate": "#ffff00",
    "Rather Heavy": "#ffa500",
    "Heavy": "#d61a1c",
    "Very Heavy": "#3b0030",
    "Extremely Heavy": "#4c0073",
    "Exceptional": "#ffdbff"
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
num_talukas_with_rain = df[df['Total_mm'] > 0].shape[0]
more_than_150 = df[df['Total_mm'] > 150].shape[0]
more_than_100 = df[df['Total_mm'] > 100].shape[0]
more_than_50 = df[df['Total_mm'] > 50].shape[0]

st.markdown(f"#### 📊 Latest data available for time slot: **{slot_labels[existing_order[-1]]}**")

# --- Metric Tiles ---
st.markdown("### Overview")
row1 = st.columns(3)
row2 = st.columns(3)

last_slot_label = slot_labels[existing_order[-1]]

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
    for feature in taluka_geojson["features"]:
        feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()

    df_map = df.copy()
    df_map["Taluka"] = df_map["Taluka"].str.strip().str.lower()
    df_map["Rainfall Category"] = df_map["Total_mm"].apply(classify_rainfall)
    df_map["Rainfall Category"] = pd.Categorical(
        df_map["Rainfall Category"],
        categories=ordered_categories, # Ensure the DataFrame's category column also follows the order
        ordered=True
    )

    # Initialize a new Figure object from graph_objects
    fig = go.Figure()

    # Create a custom colorscale for the choropleth map based on ordered categories
    # Map categories to numerical indices (0, 1, 2, ...) for the z-value
    # and create a colorscale that matches these numerical indices to your specific colors.
    num_categories = len(ordered_categories)
    discrete_colorscale = []
    for i, category in enumerate(ordered_categories):
        color = color_map[category]
        # For each discrete category, map a small range around its index to the color
        # This helps Plotly apply the color distinctly for categorical data
        if num_categories > 1:
            scale_point_low = i / (num_categories - 1)
            scale_point_high = (i + 0.999) / (num_categories - 1)
        else: # Handle case with only one category to avoid division by zero
            scale_point_low = 0
            scale_point_high = 1

        discrete_colorscale.append([scale_point_low, color])
        discrete_colorscale.append([scale_point_high, color])
    
    # Prepare `z` values (numerical representation of categories) for the choropleth trace
    df_map['Category_Index'] = df_map['Rainfall Category'].apply(lambda x: ordered_categories.index(x))

    # Add the Choroplethmapbox trace
    fig.add_trace(go.Choroplethmapbox(
        geojson=taluka_geojson,
        locations=df_map["Taluka"].tolist(),
        featureidkey="properties.SUB_DISTRICT",
        z=df_map["Category_Index"].tolist(), # Use the numerical index for coloring
        colorscale=discrete_colorscale,      # Apply the custom discrete colorscale
        marker_opacity=0.75,
        marker_line_width=0,
        customdata=df_map[["District", "Total_mm", "Rainfall Category"]].values.tolist(), # Add category to customdata
        hovertemplate="<b>%{hover_name}</b><br>District: %{customdata[0]}<br>Total Rainfall: %{customdata[1]:.1f} mm<br>Category: %{customdata[2]}<extra></extra>",
        showscale=False # Important: Do NOT show the default color scale, we're making our own legend
    ))

    # Add invisible scatter traces for the custom legend entries
    # This loop ensures that the legend entries are created in the specified `ordered_categories` sequence
    # and that their names include the range.
    for i, category in enumerate(ordered_categories):
        # Only add a legend entry if the category actually exists in the data
        # or if you want to show all categories regardless of data presence.
        # For now, we'll always add it to ensure order.
        
        color = color_map[category]
        range_text = category_ranges.get(category, '')
        
        # Format the legend label: "Category Name (Range)"
        legend_label = f"{category} ({range_text})" if range_text else category

        fig.add_trace(go.Scatter(
            x=[None], # No actual data points to plot
            y=[None],
            mode='markers',
            marker=dict(size=10, color=color, symbol='square'), # Square marker for the legend item
            name=legend_label,
            showlegend=True,
            legendgroup='categories', # Group all these dummy traces in one legend
            legendrank=i # Crucially, this ensures the correct order in the legend
        ))

    # Update map layout
    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=6,
        mapbox_center={"lat": 22.5, "lon": 71.5},
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        # Configure the main legend for bottom, horizontal placement
        showlegend=True, # Explicitly enable the legend
        legend=dict(
            orientation="h",       # Horizontal legend
            yanchor="top",         # Anchor legend from its top edge
            y=-0.15,               # Position below the map (adjust this value if needed)
            xanchor="center",      # Center horizontally
            x=0.5,                 # Center horizontally
            title_text="Rainfall Categories (mm)", # Legend title
            itemsizing='constant', # Ensure consistent item sizing
            font=dict(size=10),    # Adjust font size as needed
            # Optional: control spacing between legend items
            itemwidth=50 # Gives more space if ranges are long
        )
    )

    st.plotly_chart(fig, use_container_width=True)

else:
    st.error("❌ GeoJSON file (gujarat_taluka_clean.geojson) not found. Please ensure it's in the same directory as your app.")

# --- Table Section ---
st.markdown("### 📋 Full Rainfall Data Table")
df_display = df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
df_display.index += 1
st.dataframe(df_display, use_container_width=True, height=600)
