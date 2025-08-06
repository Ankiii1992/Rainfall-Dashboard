import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import os
import io

# ---------------------------- CONFIG ----------------------------
@st.cache_resource
def get_gsheet_client():
    """
    Establishes a connection to Google Sheets using service account credentials.
    The credentials should be stored in Streamlit secrets.
    """
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Error connecting to Google Sheets: {e}")
        st.info("Please ensure your Google service account credentials are set up correctly in Streamlit's secrets.")
        return None

@st.cache_resource
def load_geojson(path):
    """Loads GeoJSON data from a local file path."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
        return geojson_data
    except FileNotFoundError:
        st.error(f"GeoJSON file not found at: {path}. Make sure the file is in the same directory as the script.")
        return None
    except json.JSONDecodeError:
        st.error(f"Failed to decode GeoJSON file: {path}. Check the file for syntax errors.")
        return None

# --- Custom CSS for Styling ---
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

    [data-testid="stDataFrameToolbar"] button {
        display: none !important;
    }
</style>
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

ordered_categories = [
    "No Rain", "Very Light", "Light", "Moderate", "Rather Heavy",
    "Heavy", "Very Heavy", "Extremely Heavy", "Exceptional"
]


# ---------------------------- UTILITY FUNCTIONS ----------------------------

def generate_title_from_date(selected_date):
    """Generates a formatted title string for the dashboard."""
    start_date = (selected_date - timedelta(days=1)).strftime("%d-%m-%Y")
    end_date = selected_date.strftime("%d-%m-%Y")
    return f"24 Hours Rainfall Summary ({start_date} 06:00 AM to {end_date} 06:00 AM)"

@st.cache_data(ttl=600)
def load_sheet_data(sheet_name, tab_name):
    """
    Loads data from a specified Google Sheet and tab.
    Caches the data for 10 minutes to reduce API calls.
    """
    client = get_gsheet_client()
    if client is None:
        return pd.DataFrame()
    try:
        sheet = client.open(sheet_name).worksheet(tab_name)
        df = pd.DataFrame(sheet.get_all_records())
        
        # Clean column headers
        df.columns = df.columns.str.strip().str.replace(' ', '_').str.lower()
        return df
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"Spreadsheet '{sheet_name}' not found.")
        return pd.DataFrame()
    except gspread.exceptions.WorksheetNotFound:
        # st.warning(f"Tab '{tab_name}' not found in sheet '{sheet_name}'.") # This is expected behavior for some dates
        return pd.DataFrame()
    except Exception as e:
        st.error(f"An error occurred while loading data: {e}")
        return pd.DataFrame()


# --- CORRECTED get_zonal_data function ---
def get_zonal_data(df):
    """
    Generates a zonal summary from a DataFrame that already contains all required columns.
    It standardizes column names and handles data types.
    """
    # Standardize column names for reliable lookup
    # This step is now redundant as load_sheet_data already does this, but kept for safety.
    df.columns = df.columns.str.strip().str.replace(' ', '_').str.lower()

    # The required columns list is now lowercase with underscores
    # CORRECTED: Using 'total_mm' instead of 'rain_last_24_hrs' based on your data headers
    required_cols_standardized = ['zone', 'avg_rain', 'rain_till_yesterday', 'total_mm', 'total_rainfall', 'percent_against_avg']
    
    # Check for the standardized columns
    for col in required_cols_standardized:
        if col not in df.columns:
            st.error(f"Required column '{col}' not found in the data source after standardization. Please check your headers.")
            return pd.DataFrame()

    # Convert columns to numeric, handling potential errors
    for col in required_cols_standardized[1:]: # Skip 'zone'
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # CORRECTED: Using 'total_mm' in groupby
    zonal_averages = df.groupby('zone')[['avg_rain', 'rain_till_yesterday', 'total_mm', 'total_rainfall', 'percent_against_avg']].mean().round(2)
    
    # Reorder the DataFrame according to our desired order
    new_order = ['kutch region', 'saurashtra', 'north gujarat', 'east-central gujarat', 'south gujarat']
    final_results = zonal_averages.reindex(new_order).reset_index()
    
    # Revert column names to the original format for display
    final_results = final_results.rename(columns={
        'zone': 'Zone',
        'avg_rain': 'Avg_Rain',
        'rain_till_yesterday': 'Rain_Till_Yesterday',
        'total_mm': 'Rain_Last_24_Hrs', # Re-name for display in the table
        'total_rainfall': 'Total_Rainfall',
        'percent_against_avg': 'Percent_Against_Avg'
    })

    return final_results


def generate_zonal_summary_table(df_zonal_averages, df_full_data):
    """Generates a formatted table with zonal averages and a state-wide average row."""
    if df_zonal_averages.empty or df_full_data.empty:
        return pd.DataFrame()

    df_zonal_averages_copy = df_zonal_averages.copy()
    
    # Calculate state-wide averages from the full dataset
    state_avg = df_full_data[['Avg_Rain', 'Rain_Till_Yesterday', 'Rain_Last_24_Hrs', 'Total_Rainfall', 'Percent_Against_Avg']].mean().round(2)
    
    # Create a new DataFrame for the state average row
    state_avg_row = pd.DataFrame([state_avg.to_dict()])
    state_avg_row['Zone'] = 'State Avg.'
    
    # Concatenate the zonal averages with the state average row
    final_table = pd.concat([df_zonal_averages_copy, state_avg_row], ignore_index=True)
    
    # Format the columns for display
    final_table['Avg_Rain'] = final_table['Avg_Rain'].astype(str) + ' mm'
    final_table['Rain_Till_Yesterday'] = final_table['Rain_Till_Yesterday'].astype(str) + ' mm'
    final_table['Rain_Last_24_Hrs'] = final_table['Rain_Last_24_Hrs'].astype(str) + ' mm'
    final_table['Total_Rainfall'] = final_table['Total_Rainfall'].astype(str) + ' mm'
    final_table['Percent_Against_Avg'] = final_table['Percent_Against_Avg'].astype(str) + '%'
    
    # Rename columns for better display
    final_table = final_table.rename(columns={
        'Avg_Rain': 'Avg_Rain (mm)',
        'Rain_Till_Yesterday': 'Rain_Till_Yesterday (mm)',
        'Rain_Last_24_Hrs': 'Rain_Last_24_Hrs (mm)',
        'Total_Rainfall': 'Total_Rainfall (mm)',
        'Percent_Against_Avg': 'Percent_Against_Avg'
    })
    
    return final_table


def create_zonal_dual_axis_chart(data):
    """Creates a dual-axis chart for zonal rainfall."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig.add_trace(
        go.Bar(
            x=data['Zone'],
            y=data['Total_Rainfall'],
            name='Total Rainfall (mm)',
            marker_color='rgb(100, 149, 237)',
            text=data['Total_Rainfall'],
            textposition='inside',
        ),
        secondary_y=False,
    )
    
    fig.add_trace(
        go.Scatter(
            x=data['Zone'],
            y=data['Percent_Against_Avg'],
            name='% Against Avg. Rainfall',
            mode='lines+markers+text',
            marker=dict(size=8, color='rgb(255, 165, 0)'),
            line=dict(color='rgb(255, 165, 0)'),
            text=[f'{p:.1f}%' for p in data['Percent_Against_Avg']],
            textposition='top center',
        ),
        secondary_y=True,
    )
    
    fig.update_layout(
        title_text='Zonewise Total Rainfall vs. % Against Average',
        height=450,
        margin=dict(l=0, r=0, t=50, b=0),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.3,
            xanchor="center",
            x=0.5
        )
    )
    
    fig.update_yaxes(title_text="Total Rainfall (mm)", secondary_y=False)
    fig.update_yaxes(title_text="% Against Avg. Rainfall", secondary_y=True)
    
    return fig


def plot_choropleth(df, geojson_path, title="Gujarat Rainfall Distribution", geo_feature_id_key="properties.SUB_DISTRICT", geo_location_col="Taluka"):
    """
    Generates a choropleth map using Plotly.
    It can handle both Taluka and District level GeoJSON data.
    """
    geojson_data = load_geojson(geojson_path)
    if not geojson_data:
        return go.Figure()

    df_plot = df.copy()
    
    # Standardize column names
    df_plot.columns = df_plot.columns.str.strip().str.replace(' ', '_').str.lower()
    geo_location_col = geo_location_col.lower()
    
    # Determine the column to be used for coloring the map
    color_column = None
    if 'total_mm' in df_plot.columns:
        color_column = 'total_mm'
    elif 'district_avg_rain_last_24_hrs' in df_plot.columns:
        color_column = 'district_avg_rain_last_24_hrs'
    else:
        st.warning(f"Neither 'total_mm' nor 'district_avg_rain_last_24_hrs' found for map categorization.")
        df_plot["rainfall_category"] = "No Rain"
        color_column = "rainfall_category"

    if color_column:
        df_plot[color_column] = pd.to_numeric(df_plot[color_column], errors='coerce')
        df_plot["rainfall_category"] = df_plot[color_column].apply(classify_rainfall)
        df_plot["rainfall_category"] = pd.Categorical(
            df_plot["rainfall_category"],
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
        featureidkey=geo_feature_id_key,
        locations=geo_location_col,
        color="rainfall_category",
        color_discrete_map=color_map,
        mapbox_style="open-street-map",
        zoom=6,
        center={"lat": 22.5, "lon": 71.5},
        opacity=0.75,
        hover_name=geo_location_col,
        hover_data={
            color_column: ":.1f mm",
            "district": True if geo_location_col == "taluka" else False,
            "rainfall_category":False
        },
        height=650,
        title=title
    )
    fig.update_layout(
        margin={"r":0,"t":0,"l":0,"b":0},
        uirevision='true',
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
    return fig


# --- CORRECTED show_24_hourly_dashboard function ---
def show_24_hourly_dashboard(df_daily, selected_date):
    """
    Displays the full daily rainfall dashboard, including metrics,
    zonal summary, and maps.
    """
    
    # We now assume the 'Total_mm' column is already present in the data
    required_cols_metrics = ["total_mm", "taluka", "district"]
    for col in required_cols_metrics:
        if col not in df_daily.columns:
            st.error(f"Required column '{col}' not found in the loaded data.")
            return

    df_daily["total_mm"] = pd.to_numeric(df_daily["total_mm"], errors='coerce')
    df_daily["percent_against_avg"] = pd.to_numeric(df_daily["percent_against_avg"], errors='coerce')

    # District Name Standardization
    district_name_mapping = {
        "Chhota Udepur": "Chhota Udaipur",
        "Dangs": "Dang",
        "Kachchh": "Kutch",
        "Mahesana": "Mehsana",
    }
    df_daily['district'] = df_daily['district'].replace(district_name_mapping)
    df_daily['district'] = df_daily['district'].astype(str).str.strip()

    title = generate_title_from_date(selected_date)
    st.subheader(title)

    # ---- Metrics ----
    state_avg = df_daily["total_mm"].mean() if not df_daily["total_mm"].isnull().all() else 0.0
    
    if not df_daily["total_mm"].isnull().all() and not df_daily.empty:
        highest_taluka = df_daily.loc[df_daily["total_mm"].idxmax()]
    else:
        highest_taluka = pd.Series({'taluka': 'N/A', 'total_mm': 0})
    
    percent_against_avg = df_daily["percent_against_avg"].mean() if "percent_against_avg" in df_daily.columns and not df_daily["percent_against_avg"].isnull().all() else 0.0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>State Rainfall (Avg.)</h4><h2>{state_avg:.1f} mm</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Highest Rainfall Taluka</h4><h2>{highest_taluka['taluka']}</h2><p>({highest_taluka['total_mm']} mm)</p></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col3:
        st.markdown("<div classt class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>State Avg Rainfall (%) Till Today</h4><h2>{percent_against_avg:.1f}%</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    col_daily_1, col_daily_2, col_daily_3 = st.columns(3)

    more_than_200_daily = df_daily[df_daily['total_mm'] > 200].shape[0]
    more_than_100_daily = df_daily[df_daily['total_mm'] > 100].shape[0]
    more_than_50_daily = df_daily[df_daily['total_mm'] > 50].shape[0]

    with col_daily_1:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Talukas > 200 mm</h4><h2>{more_than_200_daily}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col_daily_2:
        st.markdown("<div classt class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Talukas > 100 mm</h4><h2>{more_than_100_daily}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with col_daily_3:
        st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
        st.markdown(f"<div class='metric-tile'><h4>Talukas > 50 mm</h4><h2>{more_than_50_daily}</h2></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # --- MODIFIED: ZONAL SUMMARY SECTION ---
    st.header("Zonewise Rainfall (Average) Summary Table")

    zonal_summary_averages = get_zonal_data(df_daily)

    if not zonal_summary_averages.empty:
        col_table, col_chart = st.columns([1, 1])
        
        # 'df_daily' is the standardized dataframe, so we need to rename some columns for 'generate_zonal_summary_table'
        df_for_table = zonal_summary_averages.copy()
        
        # We also need a copy of the original DF with the correct column names for the table function
        df_daily_renamed_for_table = df_daily.rename(columns={
            'avg_rain': 'Avg_Rain', 'rain_till_yesterday': 'Rain_Till_Yesterday',
            'total_mm': 'Rain_Last_24_Hrs', 'total_rainfall': 'Total_Rainfall',
            'percent_against_avg': 'Percent_Against_Avg'
        })
        
        zonal_summary_table_df = generate_zonal_summary_table(df_for_table, df_daily_renamed_for_table)

        with col_table:
            st.markdown("#### Rainfall Averages by Zone")
            st.dataframe(zonal_summary_table_df.style.set_properties(**{'font-weight': 'bold'}, subset=pd.Index([5])), use_container_width=True)

        with col_chart:
            st.markdown("#### Zonewise Rainfall vs. % Against Avg.")
            fig = create_zonal_dual_axis_chart(zonal_summary_averages)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Could not generate Zonewise Summary. Please ensure your data source contains the required columns and is loaded correctly.")
    # --- MODIFIED: END ZONAL SUMMARY SECTION ---

    st.markdown("---")
    st.markdown("### 🗺️ Rainfall Distribution Overview")

    district_rainfall_avg_df = df_daily.groupby('district')['total_mm'].mean().reset_index()
    district_rainfall_avg_df = district_rainfall_avg_df.rename(
        columns={'total_mm': 'district_avg_rain_last_24_hrs'}
    )
    district_rainfall_avg_df["rainfall_category"] = district_rainfall_avg_df["district_avg_rain_last_24_hrs"].apply(classify_rainfall)
    district_rainfall_avg_df["rainfall_category"] = pd.Categorical(
        district_rainfall_avg_df["rainfall_category"],
        categories=ordered_categories,
        ordered=True
    )
    district_rainfall_avg_df['rainfall_range'] = district_rainfall_avg_df['rainfall_category'].map(category_ranges)


    df_map_talukas = df_daily.copy()
    df_map_talukas["taluka"] = df_map_talukas["taluka"].str.strip().str.lower()
    df_map_talukas["rainfall_category"] = df_map_talukas["total_mm"].apply(classify_rainfall)
    df_map_talukas["rainfall_category"] = pd.Categorical(
        df_map_talukas["rainfall_category"],
        categories=ordered_categories,
        ordered=True
    )
    df_map_talukas["rainfall_range"] = df_map_talukas["rainfall_category"].map(category_ranges)

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
                    geo_location_col="district"
                )
                st.plotly_chart(fig_map_districts, use_container_width=True)

        with insights_col_dist:
            st.markdown("#### Key Insights & Distributions (Districts)")

            category_counts_dist = district_rainfall_avg_df['rainfall_category'].value_counts().reset_index()
            category_counts_dist.columns = ['category', 'count']
            category_counts_dist['category'] = pd.Categorical(
                category_counts_dist['category'],
                categories=ordered_categories,
                ordered=True
            )
            category_counts_dist = category_counts_dist.sort_values('category')
            category_counts_dist['rainfall_range'] = category_counts_dist['category'].map(category_ranges)


            fig_category_dist_dist = px.bar(
                category_counts_dist,
                x='category',
                y='count',
                title='Distribution of Districts by Daily Rainfall Category',
                labels={'count': 'Number of Districts'},
                color='category',
                color_discrete_map=color_map,
                hover_data={
                    'category': True,
                    'rainfall_range': True,
                    'count': True
                }
            )
            fig_category_dist_dist.update_layout(
                xaxis=dict(
                    tickmode='array',
                    tickvals=category_counts_dist['category'],
                    ticktext=[cat for cat in category_counts_dist['category']],
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
                    geo_location_col="taluka"
                )
                st.plotly_chart(fig_map_talukas, use_container_width=True)

        with insights_col_tal:
            st.markdown("#### Key Insights & Distributions (Talukas)")

            TOTAL_TALUKAS_GUJARAT = 251
            num_talukas_with_rain_today = df_map_talukas[df_map_talukas['total_mm'] > 0].shape[0]
            talukas_without_rain = TOTAL_TALUKAS_GUJARAT - num_talukas_with_rain_today

            pie_data = pd.DataFrame({
                'category': ['Talukas with Rainfall', 'Talukas without Rainfall'],
                'count': [num_talukas_with_rain_today, talukas_without_rain]
            })

            fig_pie = px.pie(
                pie_data,
                values='count',
                names='category',
                title="Percentage of Talukas with Daily Rainfall",
                color='category',
                color_discrete_map={
                    'Talukas with Rainfall': '#28a745',
                    'Talukas without Rainfall': '#dc3545'
                }
            )
            fig_pie.update_traces(textinfo='percent+label', pull=[0.05 if cat == 'Talukas with Rainfall' else 0 for cat in pie_data['category']])
            fig_pie.update_layout(showlegend=False, height=300, margin=dict(l=0, r=0, t=50, b=0))
            st.plotly_chart(fig_pie, use_container_width=True)

            category_counts_tal = df_map_talukas['rainfall_category'].value_counts().reset_index()
            category_counts_tal.columns = ['category', 'count']
            category_counts_tal['category'] = pd.Categorical(
                category_counts_tal['category'],
                categories=ordered_categories,
                ordered=True
            )
            category_counts_tal = category_counts_tal.sort_values('category')
            category_counts_tal['rainfall_range'] = category_counts_tal['category'].map(category_ranges)


            fig_category_dist_tal = px.bar(
                category_counts_tal,
                x='category',
                y='count',
                title='Distribution of Talukas by Daily Rainfall Category',
                labels={'count': 'Number of Talukas'},
                color='category',
                color_discrete_map=color_map,
                hover_data={
                    'category': True,
                    'rainfall_range': True,
                    'count': True
                }
            )
            fig_category_dist_tal.update_layout(
                xaxis=dict(
                    tickmode='array',
                    tickvals=category_counts_tal['category'],
                    ticktext=[cat for cat in category_counts_tal['category']],
                    tickangle=0
                ),
                xaxis_title=None,
                showlegend=False,
                height=350,
                margin=dict(l=0, r=0, t=50, b=0)
            )
            st.plotly_chart(fig_category_dist_tal, use_container_width=True)


    st.markdown("---")
    st.markdown("### 🏆 Top 10 Talukas by Total Rainfall")
    df_top_10 = df_daily.dropna(subset=['total_mm']).sort_values(by='total_mm', ascending=False).head(10)
    df_top_10 = df_top_10.rename(columns={'taluka': 'Taluka', 'total_mm': 'Total_mm'})

    if not df_top_10.empty:
        fig_top_10 = px.bar(
            df_top_10,
            x='Taluka',
            y='Total_mm',
            color='Total_mm',
            color_continuous_scale=px.colors.sequential.Bluyl,
            labels={'Total_mm': 'Total Rainfall (mm)'},
            hover_data=['district'],
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
    df_display = df_daily.sort_values(by="total_mm", ascending=False).reset_index(drop=True)
    df_display.index += 1
    # Rename columns for display to be more readable
    df_display = df_display.rename(columns={
        'zone': 'Zone',
        'district': 'District',
        'taluka': 'Taluka',
        'avg_rain': 'Avg_Rain',
        'rain_till_yesterday': 'Rain_Till_Yesterday',
        'total_mm': 'Total_mm',
        'total_rainfall': 'Total_Rainfall',
        'percent_against_avg': 'Percent_Against_Avg'
    })
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

# You MUST ensure these sheet and tab names match your Google Sheet exactly.
# Example format: '24HR_Rainfall_July_2025' and 'master24hrs_2025-07-21'
sheet_name_daily = f"24HR_Rainfall_{selected_month}_{selected_year}"
tab_name_daily = f"master24hrs_{selected_date_str}"


tab_daily, tab_hourly, tab_historical = st.tabs(["Daily Summary", "Hourly Trends", "Historical Data (Coming Soon)"])

with tab_daily:
    st.header("Daily Rainfall Summary")

    # Load the single DataFrame for the daily summary
    df_daily = load_sheet_data(sheet_name_daily, tab_name_daily)

    if not df_daily.empty:
        show_24_hourly_dashboard(df_daily, selected_date)
    else:
        st.warning(f"⚠️ Daily data is not available for {selected_date_str}. Please check the sheet and tab names in your code.")


with tab_hourly:
    st.header("Hourly Rainfall Trends (2-Hourly)")
    sheet_name_2hr = f"2HR_Rainfall_{selected_month}_{selected_year}"
    tab_name_2hr = f"2hrs_master_{selected_date_str}"

    df_2hr = load_sheet_data(sheet_name_2hr, tab_name_2hr)

    if not df_2hr.empty:
        time_slot_columns = [col for col in df_2hr.columns if "to" in col]
        time_slot_order = ['06to08', '08to10', '10to12', '12to14', '14to16', '16to18',
                           '18to20', '20to22', '22to24', '24to02', '02to04', '04to06']
        existing_order = [slot for slot in time_slot_order if slot in time_slot_columns]

        for col in existing_order:
            df_2hr[col] = pd.to_numeric(df_2hr[col], errors="coerce")

        df_2hr['total_mm'] = df_2hr[existing_order].sum(axis=1)

        df_long = df_2hr.melt(
            id_vars=["district", "taluka", "total_mm"],
            value_vars=existing_order,
            var_name="time_slot",
            value_name="rainfall_mm"
        )
        df_long = df_long.dropna(subset=["rainfall_mm"])
        df_long['taluka'] = df_long['taluka'].str.strip()

        df_long = df_long.groupby(["district", "taluka", "time_slot"], as_index=False).agg({
            "rainfall_mm": "sum",
            "total_mm": "first"
        })

        slot_labels = {
            "06to08": "6–8 AM", "08to10": "8–10 AM", "10to12": "10–12 AM",
            "12to14": "12–2 PM", "14to16": "2–4 PM", "16to18": "4–6 PM",
            "18to20": "6–8 PM", "20to22": "8–10 PM", "22to24": "10–12 PM",
            "24to02": "12–2 AM", "02to04": "2–4 AM", "04to06": "4–6 AM",
        }
        df_long['time_slot_label'] = pd.Categorical(
            df_long['time_slot'].map(slot_labels),
            categories=[slot_labels[slot] for slot in existing_order],
            ordered=True
        )
        df_long = df_long.sort_values(by=["taluka", "time_slot_label"])


        df_2hr['total_mm'] = pd.to_numeric(df_2hr['total_mm'], errors='coerce')

        top_taluka_row = df_2hr.sort_values(by='total_mm', ascending=False).iloc[0] if not df_2hr['total_mm'].dropna().empty else pd.Series({'taluka': 'N/A', 'total_mm': 0})
        df_latest_slot = df_long[df_long['time_slot'] == existing_order[-1]]
        top_latest = df_latest_slot.sort_values(by='rainfall_mm', ascending=False).iloc[0] if not df_latest_slot['rainfall_mm'].dropna().empty else pd.Series({'taluka': 'N/A', 'rainfall_mm': 0})
        num_talukas_with_rain_hourly = df_2hr[df_2hr['total_mm'] > 0].shape[0]

        st.markdown(f"#### 📊 Latest data available for time interval: **{slot_labels[existing_order[-1]]}**")

        row1 = st.columns(3)

        last_slot_label = slot_labels[existing_order[-1]]

        row1_titles = [
            ("Total Talukas with Rainfall", num_talukas_with_rain_hourly),
            ("Top Taluka by Total Rainfall", f"{top_taluka_row['taluka']}<br><p>{top_taluka_row['total_mm']:.1f} mm</p>"),
            (f"Top Taluka in last 2 hour ({last_slot_label})", f"{top_latest['taluka']}<br><p>{top_latest['rainfall_mm']:.1f} mm</p>")
        ]

        for col, (label, value) in zip(row1, row1_titles):
            with col:
                st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
                st.markdown(f"<div class='metric-tile'><h4>{label}</h4><h2>{value}</h2></div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("### 📈 Rainfall Trend by 2 hourly Time Interval")
        selected_talukas = st.multiselect("Select Taluka(s)", sorted(df_long['taluka'].unique()), default=[top_taluka_row['taluka']] if top_taluka_row['taluka'] != 'N/A' else [])

        if selected_talukas:
            plot_df = df_long[df_long['taluka'].isin(selected_talukas)]
            fig = px.line(
                plot_df,
                x="time_slot_label",
                y="rainfall_mm",
                color="taluka",
                markers=True,
                text="rainfall_mm",
                title="Rainfall Trend Over Time for Selected Talukas",
                labels={"rainfall_mm": "Rainfall (mm)"}
            )
            fig.update_traces(textposition="top center")
            fig.update_layout(showlegend=True)
            fig.update_layout(modebar_remove=['toImage'])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Please select at least one Taluka to view the rainfall trend.")


        st.markdown("### 📋 Full 2-Hourly Rainfall Data Table")
        df_display_2hr = df_2hr.sort_values(by="total_mm", ascending=False).reset_index(drop=True)
        df_display_2hr.index += 1
        st.dataframe(df_display_2hr, use_container_width=True, height=600)

    else:
        st.warning(f"⚠️ 2-Hourly data is not available for {selected_date_str}.")


with tab_historical:
    st.header("Historical Rainfall Data")
    st.info("💡 **Coming Soon:** This section will feature monthly/seasonal data, year-on-year comparisons, and long-term trends.")
