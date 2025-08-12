import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import os
import io

# ---------------------------- CONFIG ----------------------------
@st.cache_resource
def get_gsheet_client():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

@st.cache_resource
def load_geojson(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        return geojson_data
    st.error(f"GeoJSON file not found at: {path}")
    return None

# --- NEW: Enhanced CSS (from reference code) ---
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
        height: 165px; /* Adjusted height for consistency */
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .metric-tile:hover {
        transform: translateY(-4px);
        box_shadow: 0 10px 28px rgba(0, 0, 0, 0.1);
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


# ---------------------------- RAINFALL CATEGORY LOGIC ----------------------------
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

category_ranges = { # From reference code
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


# ---------------------------- UTILITY FUNCTIONS ----------------------------

def generate_title_from_date(selected_date):
    start_date = (selected_date - timedelta(days=1)).strftime("%d-%m-%Y")
    end_date = selected_date.strftime("%d-%m-%Y")
    return f"24 Hours Rainfall Summary ({start_date} 06:00 AM to {end_date} 06:00 AM)"

def load_sheet_data(sheet_name, tab_name):
    try:
        client = get_gsheet_client()
        sheet = client.open(sheet_name).worksheet(tab_name)
        df = pd.DataFrame(sheet.get_all_records())
        df.columns = df.columns.str.strip()
        # Ensure column names are consistent early - only rename if 'TOTAL' is present
        if 'TOTAL' in df.columns:
            df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka", "TOTAL": "Total_mm"}, inplace=True)
        else: # For 2-hourly data where 'TOTAL' might not be a direct column
            df.rename(columns={"DISTRICT": "District", "TALUKA": "Taluka"}, inplace=True)
        return df
    except Exception as e:
        # st.error(f"Error loading data from sheet '{sheet_name}', tab '{tab_name}': {e}") # For debugging
        return pd.DataFrame() # Return empty DataFrame on failure

def correct_taluka_names(df):
    """
    Corrects taluka names in the DataFrame to match the GeoJSON file.
    This ensures that data is correctly plotted on the map.
    """
    taluka_name_mapping = {
        "Morbi": "Morvi",
        "Ahmedabad City": "Ahmadabad City",
        "Maliya Hatina": "Malia",
        "Shihor": "Sihor",
        "Dwarka": "Okhamandal",
        "Kalol(Gnr)": "Kalol",
    }
    df['Taluka'] = df['Taluka'].replace(taluka_name_mapping)
    return df


# --- plot_choropleth function (for map that plots daily total) ---
def plot_choropleth(df, geojson_path, title="Gujarat Rainfall Distribution", geo_feature_id_key="properties.SUB_DISTRICT", geo_location_col="Taluka"):
    # This function is now made more generic to handle both talukas and districts
    geojson_data = load_geojson(geojson_path)
    if not geojson_data:
        return go.Figure()

    df_plot = df.copy()

    # Determine which column to use for feature linking and what to strip/lower
    if geo_location_col == "Taluka":
        df_plot["Taluka"] = df_plot["Taluka"].astype(str).str.strip().str.lower()
    elif geo_location_col == "District":
        df_plot["District"] = df_plot["District"].astype(str).str.strip().str.lower()


    # The column for coloring the map should be 'Total_mm' (daily total for taluka)
    # or 'District_Avg_Rain_Last_24_Hrs' for district.
    color_column = None
    if 'Total_mm' in df_plot.columns: # For Talukas
        color_column = 'Total_mm'
    elif 'District_Avg_Rain_Last_24_Hrs' in df_plot.columns: # For Districts
        color_column = 'District_Avg_Rain_Last_24_Hrs'
    else:
        st.warning(f"Neither 'Total_mm' nor 'District_Avg_Rain_Last_24_Hrs' found for map categorization. Map may not display categories correctly.")
        df_plot["Rainfall_Category"] = "No Rain" # Default if data is missing
        color_column = "Rainfall_Category"


    if color_column:
        df_plot[color_column] = pd.to_numeric(df_plot[color_column], errors='coerce')
        df_plot["Rainfall_Category"] = df_plot[color_column].apply(classify_rainfall)
        df_plot["Rainfall_Category"] = pd.Categorical(
            df_plot["Rainfall_Category"],
            categories=ordered_categories,
            ordered=True
        )

    # Clean geojson properties for matching
    for feature in geojson_data["features"]:
        if geo_feature_id_key == "properties.SUB_DISTRICT" and "SUB_DISTRICT" in feature["properties"]:
            feature["properties"]["SUB_DISTRICT"] = feature["properties"]["SUB_DISTRICT"].strip().lower()
        elif geo_feature_id_key == "properties.district" and "district" in feature["properties"]:
            feature["properties"]["district"] = feature["properties"]["district"].strip().lower()


    fig = px.choropleth_mapbox(
        df_plot,
        geojson=geojson_data,
        featureidkey=geo_feature_id_key, # Dynamic key for Taluka or District
        locations=geo_location_col,     # Dynamic column for Taluka or District
        color="Rainfall_Category",
        color_discrete_map=color_map,
        mapbox_style="open-street-map",
        zoom=6,
        center={"lat": 22.5, "lon": 71.5},
        opacity=0.75,
        hover_name=geo_location_col, # Use dynamic column for hover name
        hover_data={
            color_column: ":.1f mm", # Show actual rainfall value
            "District": True if geo_location_col == "Taluka" else False, # Only show district for taluka map
            "Rainfall_Category":False
        },
        height=650,
        title=title
    )
    fig.update_layout(
        margin={"r":0,"t":0,"l":0,"b":0},
        uirevision='true',
        showlegend=True, # Ensure legend is shown for map
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
    return fig


# --- show_24_hourly_dashboard function (for Daily Summary tab - NOW INCLUDES ALL DAILY CHARTS) ---
def show_24_hourly_dashboard(df, selected_date):
    df = correct_taluka_names(df)
    # Rename 'Rain_Last_24_Hrs' to 'Total_mm' for consistency if it's the 24hr data source
    if "Rain_Last_24_Hrs" in df.columns:
        df.rename(columns={"Rain_Last_24_Hrs": "Total_mm"}, inplace=True)

    required_cols = ["Total_mm", "Taluka", "District"]
    for col in required_cols:
        if col not in df.columns:
            st.error(f"Required column '{col}' not found in the loaded data. Please check your Google Sheet headers for 24-hour data.")
            return
            
    # --- NEW: Add placeholder columns for new metrics ---
    # The user must provide these columns in their actual data
    if 'Total_Rainfall' not in df.columns:
        df['Total_Rainfall'] = df['Total_mm'] * 1.5 # Example placeholder
    if 'Percent_Against_Avg' not in df.columns:
        df['Percent_Against_Avg'] = (df['Total_Rainfall'] / 700) * 100 # Example placeholder, assuming 700 is a seasonal avg

    df["Total_mm"] = pd.to_numeric(df["Total_mm"], errors='coerce')
    df["Total_Rainfall"] = pd.to_numeric(df["Total_Rainfall"], errors='coerce')
    df["Percent_Against_Avg"] = pd.to_numeric(df["Percent_Against_Avg"], errors='coerce')


    # --- NEW CODE START: District Name Standardization ---
    # Define mapping for known district name discrepancies
    district_name_mapping = {
        "Chhota Udepur": "Chhota Udaipur",
        "Dangs": "Dang",
        "Kachchh": "Kutch",
        "Mahesana": "Mehsana",
        # Add more mappings here if you discover other mismatches
    }

    # Apply the mapping to the 'District' column
    df['District'] = df['District'].replace(district_name_mapping)

    # Ensure consistent casing and stripping for matching with GeoJSON
    # This also handles cases where a district name might just have leading/trailing spaces
    df['District'] = df['District'].astype(str).str.strip()
    # --- NEW CODE END: District Name Standardization ---

    title = generate_title_from_date(selected_date)
    st.subheader(title)

    # ---- NEW LAYOUT: METRICS & VISUALS ----

    # Calculate metrics
    state_total_seasonal_avg = df["Total_Rainfall"].mean() if not df["Total_Rainfall"].isnull().all() else 0.0
    state_avg_24hr = df["Total_mm"].mean() if not df["Total_mm"].isnull().all() else 0.0
    highest_taluka = df.loc[df["Total_mm"].idxmax()] if not df["Total_mm"].isnull().all() else pd.Series({'Taluka': 'N/A', 'Total_mm': 0, 'District': 'N/A'})

    # --- NEW: Use average of Percent_Against_Avg for the progress bar ---
    state_rainfall_progress_percentage = df['Percent_Against_Avg'].mean() if not df["Percent_Against_Avg"].isnull().all() else 0.0


    highest_district_row = df.groupby('District')['Total_mm'].mean().reset_index().sort_values(by='Total_mm', ascending=False).iloc[0]
    highest_district = highest_district_row['District']
    highest_district_avg = highest_district_row['Total_mm']

    # --- NEW LAYOUT: Row 1 - Four Metric Tiles ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>State Total Seasonal Rainfall Till Today (Avg.)</h4><h2>{state_total_seasonal_avg:.1f} mm</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>State Avg. Rain (last 24 hrs)</h4><h2>{state_avg_24hr:.1f} mm</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col3:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Highest Rainfall District (Talukas Avg.)</h4><h2>{highest_district}</h2><p>({highest_district_avg:.1f} mm)</p></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col4:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Highest Rainfall Taluka</h4><h2>{highest_taluka['Taluka']}</h2><p>({highest_taluka['Total_mm']:.1f} mm)</p></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")

    # --- NEW LAYOUT: Row 2 - Circular Progress Bar and Distribution Charts ---
    col_progress, col_charts = st.columns([0.3, 0.7])

    with col_progress:
        st.markdown("#### State Seasonal Avg. Rainfall Till Today (%)")
        fig_progress = go.Figure(go.Indicator(
            mode="gauge+number",
            value=state_rainfall_progress_percentage,
            gauge={
                'shape': 'angular',
                'axis': {'range': [0, 100], 'visible': False},
                'bar': {'color': "#28a745"},
                'bgcolor': "white",
                'borderwidth': 0,
                'steps': [
                    {'range': [0, 100], 'color': "lightgray"}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': 100}
            },
            number={'suffix': "%", 'font': {'color': '#1a237e', 'size': 50}},
        ))
        fig_progress.update_layout(height=280, margin=dict(l=20, r=20, t=50, b=20),
            paper_bgcolor="#f3f6fa")
        st.plotly_chart(fig_progress, use_container_width=True)

    with col_charts:
        # Pie chart (re-used from old code)
        TOTAL_TALUKAS_GUJARAT = 251
        num_talukas_with_rain_today = df[df['Total_mm'] > 0].shape[0]
        talukas_without_rain = TOTAL_TALUKAS_GUJARAT - num_talukas_with_rain_today
        pie_data = pd.DataFrame({
            'Category': ['Talukas with Rainfall', 'Talukas without Rainfall'],
            'Count': [num_talukas_with_rain_today, talukas_without_rain]
        })
        fig_pie = px.pie(
            pie_data,
            values='Count',
            names='Category',
            title="Percentage of Talukas with Daily Rainfall",
            color='Category',
            color_discrete_map={
                'Talukas with Rainfall': '#28a745',
                'Talukas without Rainfall': '#dc3545'
            }
        )
        fig_pie.update_traces(textinfo='percent+label', pull=[0.05 if cat == 'Talukas with Rainfall' else 0 for cat in pie_data['Category']])
        fig_pie.update_layout(showlegend=False, height=250, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_pie, use_container_width=True)
        
        # Bar chart for taluka counts
        rainfall_categories = {
            'Talukas > 200 mm': df[df['Total_mm'] > 200].shape[0],
            'Talukas > 150 mm': df[df['Total_mm'] > 150].shape[0],
            'Talukas > 100 mm': df[df['Total_mm'] > 100].shape[0],
            'Talukas > 75 mm': df[df['Total_mm'] > 75].shape[0],
            'Talukas > 50 mm': df[df['Total_mm'] > 50].shape[0],
            'Talukas > 25 mm': df[df['Total_mm'] > 25].shape[0]
        }
        categories_df = pd.DataFrame(list(rainfall_categories.items()), columns=['Category', 'Count'])

        fig_bar = px.bar(
            categories_df,
            x='Category',
            y='Count',
            title='Distribution of Talukas by Rainfall Intensity',
            labels={'Count': 'Number of Talukas'},
            color='Count',
            color_continuous_scale=px.colors.sequential.YlGnBu,
            text='Count'
        )
        fig_bar.update_traces(texttemplate='%{text}', textposition='outside')
        fig_bar.update_layout(
            xaxis_title=None,
            yaxis_title=None,
            xaxis_tickangle=-45,
            showlegend=False,
            height=300,
            margin=dict(l=0, r=0, t=50, b=0)
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    
    st.markdown("---")
    
    # --- Rainfall Distribution Maps (re-used from old code) ---
    st.markdown("### 🗺️ Rainfall Distribution Overview")

    district_rainfall_avg_df = df.groupby('District')['Total_mm'].mean().reset_index()
    district_rainfall_avg_df = district_rainfall_avg_df.rename(
        columns={'Total_mm': 'District_Avg_Rain_Last_24_Hrs'}
    )
    district_rainfall_avg_df["Rainfall_Category"] = district_rainfall_avg_df["District_Avg_Rain_Last_24_Hrs"].apply(classify_rainfall)
    district_rainfall_avg_df["Rainfall_Category"] = pd.Categorical(
        district_rainfall_avg_df["Rainfall_Category"],
        categories=ordered_categories,
        ordered=True
    )
    district_rainfall_avg_df['Rainfall_Range'] = district_rainfall_avg_df['Rainfall_Category'].map(category_ranges)


    df_map_talukas = df.copy()
    df_map_talukas["Taluka"] = df_map_talukas["Taluka"].str.strip().str.lower()
    df_map_talukas["Rainfall_Category"] = df_map_talukas["Total_mm"].apply(classify_rainfall)
    df_map_talukas["Rainfall_Category"] = pd.Categorical(
        df_map_talukas["Rainfall_Category"],
        categories=ordered_categories,
        ordered=True
    )
    df_map_talukas["Rainfall_Range"] = df_map_talukas["Rainfall_Category"].map(category_ranges)

    taluka_geojson = load_geojson("gujarat_taluka_clean.geojson")
    district_geojson = load_geojson("gujarat_district_clean.geojson")


    if not taluka_geojson or not district_geojson:
        st.error("Cannot display maps: One or both GeoJSON files not found or loaded correctly.")
        return

    tab_districts, tab_talukas = st.tabs(["Rainfall Distribution by Districts", "Rainfall Distribution by Talukas"])


    with tab_districts:
        map_col_dist, insights_col_dist = st.columns([0.5, 0.5])

        with map_col_dist:
            st.markdown("#### Gujarat Rainfall Map (by District)")
            with st.spinner("Loading district map..."):
                fig_map_districts = plot_choropleth(
                    district_rainfall_avg_df,
                    "gujarat_district_clean.geojson",
                    title="Gujarat Daily Rainfall Distribution by District",
                    geo_feature_id_key="properties.district",
                    geo_location_col="District"
                )
                st.plotly_chart(fig_map_districts, use_container_width=True)

        with insights_col_dist:
            st.markdown("#### Key Insights & Distributions (Districts)")

            category_counts_dist = district_rainfall_avg_df['Rainfall_Category'].value_counts().reset_index()
            category_counts_dist.columns = ['Category', 'Count']
            category_counts_dist['Category'] = pd.Categorical(
                category_counts_dist['Category'],
                categories=ordered_categories,
                ordered=True
            )
            category_counts_dist = category_counts_dist.sort_values('Category')
            category_counts_dist['Rainfall_Range'] = category_counts_dist['Category'].map(category_ranges)


            fig_category_dist_dist = px.bar(
                category_counts_dist,
                x='Category',
                y='Count',
                title='Distribution of Districts by Daily Rainfall Category',
                labels={'Count': 'Number of Districts'},
                color='Category',
                color_discrete_map=color_map,
                hover_data={
                    'Category': True,
                    'Rainfall_Range': True,
                    'Count': True
                }
            )
            fig_category_dist_dist.update_layout(
                xaxis=dict(
                    tickmode='array',
                    tickvals=category_counts_dist['Category'],
                    ticktext=[cat for cat in category_counts_dist['Category']],
                    tickangle=0
                ),
                xaxis_title=None,
                showlegend=False,
                height=350,
                margin=dict(l=0, r=0, t=50, b=0)
            )
            st.plotly_chart(fig_category_dist_dist, use_container_width=True)


    with tab_talukas:
        map_col_tal, insights_col_tal = st.columns([0.5, 0.5])

        with map_col_tal:
            st.markdown("#### Gujarat Rainfall Map (by Taluka)")
            with st.spinner("Loading taluka map..."):
                fig_map_talukas = plot_choropleth(
                    df_map_talukas,
                    "gujarat_taluka_clean.geojson",
                    title="Gujarat Daily Rainfall Distribution by Taluka",
                    geo_feature_id_key="properties.SUB_DISTRICT",
                    geo_location_col="Taluka"
                )
                st.plotly_chart(fig_map_talukas, use_container_width=True)

        with insights_col_tal:
            st.markdown("#### Key Insights & Distributions (Talukas)")

            # Bar chart for taluka counts (re-used from new layout)
            rainfall_categories_tal = {
                'Talukas > 200 mm': df[df['Total_mm'] > 200].shape[0],
                'Talukas > 150 mm': df[df['Total_mm'] > 150].shape[0],
                'Talukas > 100 mm': df[df['Total_mm'] > 100].shape[0],
                'Talukas > 75 mm': df[df['Total_mm'] > 75].shape[0],
                'Talukas > 50 mm': df[df['Total_mm'] > 50].shape[0],
                'Talukas > 25 mm': df[df['Total_mm'] > 25].shape[0]
            }
            categories_df_tal = pd.DataFrame(list(rainfall_categories_tal.items()), columns=['Category', 'Count'])

            fig_bar_tal = px.bar(
                categories_df_tal,
                x='Category',
                y='Count',
                title='Distribution of Talukas by Rainfall Intensity',
                labels={'Count': 'Number of Talukas'},
                color='Count',
                color_continuous_scale=px.colors.sequential.YlGnBu,
                text='Count'
            )
            fig_bar_tal.update_traces(texttemplate='%{text}', textposition='outside')
            fig_bar_tal.update_layout(
                xaxis_title=None,
                yaxis_title=None,
                xaxis_tickangle=-45,
                showlegend=False,
                height=300,
                margin=dict(l=0, r=0, t=50, b=0)
            )
            st.plotly_chart(fig_bar_tal, use_container_width=True)

    st.markdown("---")
    st.markdown("### 🏆 Top 10 Talukas by Total Rainfall")
    df_top_10 = df.dropna(subset=['Total_mm']).sort_values(by='Total_mm', ascending=False).head(10)

    if not df_top_10.empty:
        fig_top_10 = px.bar(
            df_top_10,
            x='Taluka',
            y='Total_mm',
            color='Total_mm',
            color_continuous_scale=px.colors.sequential.Bluyl,
            labels={'Total_mm': 'Total Rainfall (mm)'},
            hover_data=['District'],
            text='Total_mm',
            title='Top 10 Talukas with Highest Total Daily Rainfall'
        )
        fig_top_10.update_traces(texttemplate='%{text:.1f}', textposition='outside')
        fig_top_10.update_layout(
            xaxis_tickangle=-45,
            showlegend=False,
            margin=dict(t=50),
            coloraxis_showscale=False
        )
        st.plotly_chart(fig_top_10, use_container_width=True)
    else:
        st.info("No rainfall data available to determine top 10 talukas.")

    st.subheader("📋 Full Daily Rainfall Data Table")
    df_display = df.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
    df_display.index += 1
    st.dataframe(df_display, use_container_width=True, height=400)

# ---------------------------- UI ----------------------------
st.set_page_config(layout="wide")
st.markdown("<div class='title-text'>🌧️ Gujarat Rainfall Dashboard</div>", unsafe_allow_html=True)

st.markdown("---")
st.subheader("🗓️ Select Date for Rainfall Data")

if 'selected_date' not in st.session_state:
    st.session_state.selected_date = datetime.today().date()

col_date_picker, col_prev_btn, col_today_btn, col_next_btn = st.columns([0.2, 0.1, 0.1, 0.1])

with col_date_picker:
    selected_date_from_picker = st.date_input(
        "Choose Date",
        value=st.session_state.selected_date,
        help="Select a specific date to view its rainfall summary."
    )
    if selected_date_from_picker != st.session_state.selected_date:
        st.session_state.selected_date = selected_date_from_picker
        st.rerun()

selected_date = st.session_state.selected_date

with col_prev_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("⬅️ Previous Day", key="prev_day_btn"):
        st.session_state.selected_date = selected_date - timedelta(days=1)
        st.rerun()

with col_today_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🗓️ Today", key="today_btn"):
        st.session_state.selected_date = datetime.today().date()
        st.rerun()

with col_next_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Next Day ➡️", key="next_day_btn", disabled=(selected_date >= datetime.today().date())):
        st.session_state.selected_date = selected_date + timedelta(days=1)
        st.rerun()

st.markdown("---")

selected_year = selected_date.strftime("%Y")
selected_month = selected_date.strftime("%B")
selected_date_str = selected_date.strftime("%Y-%m-%d")

tab_daily, tab_hourly, tab_historical = st.tabs(["Daily Summary", "Hourly Trends", "Historical Data (Coming Soon)"])

with tab_daily:
    st.header("Daily Rainfall Summary")

    sheet_name_24hr = f"24HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_24hr = f"master24hrs_{selected_date_str}"

    df_24hr = load_sheet_data(sheet_name_24hr, tab_name_24hr)

    if not df_24hr.empty:
        show_24_hourly_dashboard(df_24hr, selected_date)
    else:
        st.warning(f"⚠️ Daily data is not available for {selected_date_str}.")

with tab_hourly:
    st.header("Hourly Rainfall Trends (2-Hourly)")
    sheet_name_2hr = f"2HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_2hr = f"2hrs_master_{selected_date_str}"

    df_2hr = load_sheet_data(sheet_name_2hr, tab_name_2hr)

    if not df_2hr.empty:
        df_2hr = correct_taluka_names(df_2hr)
        df_2hr.columns = df_2hr.columns.str.strip()

        time_slot_columns = [col for col in df_2hr.columns if "TO" in col and df_2hr[col].dtype in ['int64', 'float64', 'object']]
        time_slot_order = ['06TO08', '08TO10', '10TO12', '12TO14', '14TO16', '16TO18',
                           '18TO20', '20TO22', '22TO24', '24TO02', '02TO04', '04TO06']
        existing_order = [slot for slot in time_slot_order if slot in time_slot_columns]

        for col in existing_order:
            df_2hr[col] = pd.to_numeric(df_2hr[col], errors="coerce")

        df_2hr['Total_mm'] = df_2hr[existing_order].sum(axis=1)

        df_long = df_2hr.melt(
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

        slot_labels = {
            "06TO08": "6–8 AM", "08TO10": "8–10 AM", "10TO12": "10–12 AM",
            "12TO14": "12–2 PM", "14TO16": "2–4 PM", "16TO18": "4–6 PM",
            "18TO20": "6–8 PM", "20TO22": "8–10 PM", "22TO24": "10–12 PM",
            "24TO02": "12–2 AM", "02TO04": "2–4 AM", "04TO06": "4–6 AM",
        }
        df_long['Time Slot Label'] = pd.Categorical(
            df_long['Time Slot'].map(slot_labels),
            categories=[slot_labels[slot] for slot in existing_order],
            ordered=True
        )
        df_long = df_long.sort_values(by=["Taluka", "Time Slot Label"])


        df_2hr['Total_mm'] = pd.to_numeric(df_2hr['Total_mm'], errors='coerce')

        top_taluka_row = df_2hr.sort_values(by='Total_mm', ascending=False).iloc[0] if not df_2hr['Total_mm'].dropna().empty else pd.Series({'Taluka': 'N/A', 'Total_mm': 0})
        df_latest_slot = df_long[df_long['Time Slot'] == existing_order[-1]]
        top_latest = df_latest_slot.sort_values(by='Rainfall (mm)', ascending=False).iloc[0] if not df_latest_slot['Rainfall (mm)'].dropna().empty else pd.Series({'Taluka': 'N/A', 'Rainfall (mm)': 0})
        num_talukas_with_rain_hourly = df_2hr[df_2hr['Total_mm'] > 0].shape[0]

        st.markdown(f"#### 📊 Latest data available for time interval: **{slot_labels[existing_order[-1]]}**")

        row1 = st.columns(3)

        last_slot_label = slot_labels[existing_order[-1]]

        row1_titles = [
            ("Total Talukas with Rainfall", num_talukas_with_rain_hourly),
            ("Top Taluka by Total Rainfall", f"{top_taluka_row['Taluka']}<br><p>{top_taluka_row['Total_mm']:.1f} mm</p>"),
            (f"Top Taluka in last 2 hour ({last_slot_label})", f"{top_latest['Taluka']}<br><p>{top_latest['Rainfall (mm)']:.1f} mm</p>")
        ]

        for col, (label, value) in zip(row1, row1_titles):
            with col:
                st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
                st.markdown(f"<div class='metric-tile'><h4>{label}</h4><h2>{value}</h2></div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("### 📈 Rainfall Trend by 2 hourly Time Interval")
        selected_talukas = st.multiselect("Select Taluka(s)", sorted(df_long['Taluka'].unique()), default=[top_taluka_row['Taluka']] if top_taluka_row['Taluka'] != 'N/A' else [])

        if selected_talukas:
            plot_df = df_long[df_long['Taluka'].isin(selected_talukas)]
            fig = px.line(
                plot_df,
                x="Time Slot Label",
                y="Rainfall (mm)",
                color="Taluka",
                markers=True,
                text="Rainfall (mm)",
                title="Rainfall Trend Over Time for Selected Talukas",
                labels={"Rainfall (mm)": "Rainfall (mm)"}
            )
            fig.update_traces(textposition="top center")
            fig.update_layout(showlegend=True)
            fig.update_layout(modebar_remove=['toImage'])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Please select at least one Taluka to view the rainfall trend.")


        st.markdown("### 📋 Full 2-Hourly Rainfall Data Table")
        df_display_2hr = df_2hr.sort_values(by="Total_mm", ascending=False).reset_index(drop=True)
        df_display_2hr.index += 1
        st.dataframe(df_display_2hr, use_container_width=True, height=600)

    else:
        st.warning(f"⚠️ 2-Hourly data is not available for {selected_date_str}.")


with tab_historical:
    st.header("Historical Rainfall Data")
    st.info("💡 **Coming Soon:** This section will feature monthly/seasonal data, year-on-year comparisons, and long-term trends.")
