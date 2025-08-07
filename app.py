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
import re

# ---------------------------- CONFIG ----------------------------
@st.cache_resource
def get_gsheet_client():
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
    "No Rain": "#f8f8f8", "Very Light": "#e0ffe0", "Light": "#00ff01",
    "Moderate": "#00ffff", "Rather Heavy": "#ffeb3b", "Heavy": "#ff8c00",
    "Very Heavy": "#d50000", "Extremely Heavy": "#f820fe", "Exceptional": "#e8aaf5"
}

category_ranges = {
    "No Rain": "0 mm", "Very Light": "0.1 – 2.4 mm", "Light": "2.5 – 7.5 mm",
    "Moderate": "7.6 – 35.5 mm", "Rather Heavy": "35.6 – 64.4 mm",
    "Heavy": "64.5 – 124.4 mm", "Very Heavy": "124.5 – 244.4 mm",
    "Extremely Heavy": "244.5 – 350 mm", "Exceptional": "> 350 mm"
}

def classify_rainfall(rainfall):
    if pd.isna(rainfall) or rainfall == 0: return "No Rain"
    if rainfall <= 2.4: return "Very Light"
    if rainfall <= 7.5: return "Light"
    if rainfall <= 35.5: return "Moderate"
    if rainfall <= 64.4: return "Rather Heavy"
    if rainfall <= 124.4: return "Heavy"
    if rainfall <= 244.4: return "Very Heavy"
    if rainfall <= 350: return "Extremely Heavy"
    return "Exceptional"

ordered_categories = list(color_map.keys())


# ---------------------------- UTILITY FUNCTIONS ----------------------------
def generate_title_from_date(selected_date):
    start_date = (selected_date - timedelta(days=1)).strftime("%d-%m-%Y")
    end_date = selected_date.strftime("%d-%m-%Y")
    return f"24 Hours Rainfall Summary ({start_date} 06:00 AM to {end_date} 06:00 AM)"

@st.cache_data(ttl=600)
def load_sheet_data(sheet_name, tab_name):
    client = get_gsheet_client()
    if client is None: return pd.DataFrame()
    try:
        df = pd.DataFrame(client.open(sheet_name).worksheet(tab_name).get_all_records())
        df.columns = df.columns.str.strip().str.replace(' ', '_').str.lower()
        return df
    except (gspread.exceptions.SpreadsheetNotFound, gspread.exceptions.WorksheetNotFound):
        return pd.DataFrame()
    except Exception as e:
        st.error(f"An error occurred while loading data: {e}")
        return pd.DataFrame()

def get_zonal_data(df):
    df_copy = df.copy()
    df_copy['zone'] = df_copy['zone'].str.strip().str.upper().str.replace('GUJARA T', 'GUJARAT')

    col_mapping = {
        'zone': 'zone', 'avg_rain': 'avg_rain', 'rain_till_yesterday': 'rain_till',
        'rain_last_24_hrs': 'rain_last', 'total_rainfall': 'total_rain',
        'percent_against_avg': 'percent_a'
    }
    
    found_cols = {req: next((col for col in df_copy.columns if req in col and col_mapping[req] == req), None)
                  for req in col_mapping}
    
    if not all(found_cols.values()):
        missing = [req for req, found in found_cols.items() if not found]
        st.error(f"Required column(s) not found in data source: {', '.join(missing)}")
        return pd.DataFrame()

    df_copy.rename(columns=found_cols, inplace=True)
    for col in list(col_mapping.keys())[1:]:
        df_copy[col] = pd.to_numeric(df_copy[col].astype(str).str.replace(' mm|%', '', regex=True), errors='coerce')

    unique_zones = sorted(df_copy['zone'].unique())
    zonal_averages = df_copy.groupby('zone')[list(col_mapping.keys())[1:]].mean().round(2)
    final_results = zonal_averages.reindex(unique_zones).reset_index()

    display_col_names = {
        'zone': 'Zone', 'avg_rain': 'Avg_Rain', 'rain_till_yesterday': 'Rain_Till_Yesterday',
        'rain_last_24_hrs': 'Rain_Last_24_Hrs', 'total_rainfall': 'Total_Rainfall',
        'percent_against_avg': 'Percent_Against_Avg'
    }
    return final_results.rename(columns=display_col_names)


def generate_zonal_summary_table(df_zonal_averages, df_full_data):
    if df_zonal_averages.empty or df_full_data.empty: return pd.DataFrame()
    
    state_avg = df_full_data[['Avg_Rain', 'Rain_Till_Yesterday', 'Rain_Last_24_Hrs', 'Total_Rainfall', 'Percent_Against_Avg']].mean().round(2)
    state_avg_row = pd.DataFrame([state_avg.to_dict()]).assign(Zone='State Avg.')
    final_table = pd.concat([df_zonal_averages, state_avg_row], ignore_index=True)
    
    for col in ['Avg_Rain', 'Rain_Till_Yesterday', 'Rain_Last_24_Hrs', 'Total_Rainfall']:
        final_table[col] = final_table[col].astype(str) + ' mm'
    final_table['Percent_Against_Avg'] = final_table['Percent_Against_Avg'].astype(str) + '%'
    
    return final_table.rename(columns={
        'Avg_Rain': 'Avg_Rain (mm)', 'Rain_Till_Yesterday': 'Rain_Till_Yesterday (mm)',
        'Rain_Last_24_Hrs': 'Rain_Last_24_Hrs (mm)', 'Total_Rainfall': 'Total_Rainfall (mm)'
    })


def create_zonal_dual_axis_chart(data):
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig.add_trace(go.Bar(x=data['Zone'], y=data['Total_Rainfall'], name='Total Rainfall (mm)',
                         marker_color='rgb(100, 149, 237)', text=data['Total_Rainfall'], textposition='inside'), secondary_y=False)
    fig.add_trace(go.Scatter(x=data['Zone'], y=data['Percent_Against_Avg'], name='% Against Avg. Rainfall',
                             mode='lines+markers+text', marker=dict(size=8, color='rgb(255, 165, 0)'),
                             line=dict(color='rgb(255, 165, 0)'), text=[f'{p:.1f}%' for p in data['Percent_Against_Avg']],
                             textposition='top center'), secondary_y=True)
    
    fig.update_layout(title_text='Zonewise Total Rainfall vs. % Against Average', height=450, margin=dict(l=0, r=0, t=50, b=0),
                      legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5))
    fig.update_yaxes(title_text="Total Rainfall (mm)", secondary_y=False)
    fig.update_yaxes(title_text="% Against Avg. Rainfall", secondary_y=True)
    
    return fig

def plot_choropleth(df, geojson_path, title="Gujarat Rainfall Distribution", geo_feature_id_key="properties.SUB_DISTRICT", geo_location_col="taluka"):
    geojson_data = load_geojson(geojson_path)
    if not geojson_data: return go.Figure()

    df_plot = df.copy()
    df_plot.columns = df_plot.columns.str.strip().str.replace(' ', '_').str.lower()
    geo_location_col = geo_location_col.lower()

    color_column = 'rain_last_24_hrs' if 'rain_last_24_hrs' in df_plot.columns else 'district_avg_rain_last_24_hrs'
    if not color_column:
        st.warning("Rainfall data not found for map categorization.")
        df_plot["rainfall_category"] = "No Rain"
        color_column = "rainfall_category"

    df_plot[color_column] = pd.to_numeric(df_plot[color_column], errors='coerce')
    df_plot["rainfall_category"] = pd.Categorical(df_plot[color_column].apply(classify_rainfall), categories=ordered_categories, ordered=True)

    for feature in geojson_data["features"]:
        prop_key = geo_feature_id_key.split('.')[1]
        if prop_key in feature["properties"]:
            feature["properties"][prop_key] = feature["properties"][prop_key].strip().lower()

    fig = px.choropleth_mapbox(df_plot, geojson=geojson_data, featureidkey=geo_feature_id_key,
                               locations=geo_location_col, color="rainfall_category", color_discrete_map=color_map,
                               mapbox_style="open-street-map", zoom=6, center={"lat": 22.5, "lon": 71.5},
                               opacity=0.75, hover_name=geo_location_col,
                               hover_data={color_column: ":.1f mm", "district": geo_location_col == "taluka", "rainfall_category": False},
                               height=650, title=title)
    fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0}, uirevision='true', showlegend=True,
                      legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5,
                                  title_text="Rainfall Categories (mm)", font=dict(size=10), itemsizing='constant'))
    return fig


def show_24_hourly_dashboard(df_daily, selected_date):
    df_daily_copy = df_daily.copy()
    df_daily_copy.columns = df_daily_copy.columns.str.strip().str.replace(' ', '_').str.lower()
    
    required_cols = ["rain_last_24_hrs", "taluka", "district"]
    if not all(col in df_daily_copy.columns for col in required_cols):
        st.error(f"Required column(s) not found in the loaded data.")
        return

    df_daily_copy["rain_last_24_hrs"] = pd.to_numeric(df_daily_copy["rain_last_24_hrs"], errors='coerce')
    df_daily_copy["percent_against_avg"] = pd.to_numeric(df_daily_copy["percent_against_avg"], errors='coerce')

    district_name_mapping = {"Chhota Udepur": "Chhota Udaipur", "Dangs": "Dang", "Kachchh": "Kutch", "Mahesana": "Mehsana"}
    df_daily_copy['district'] = df_daily_copy['district'].replace(district_name_mapping).str.strip()

    st.subheader(generate_title_from_date(selected_date))
    
    # Refactored metrics display into a loop
    state_avg = df_daily_copy["rain_last_24_hrs"].mean() if not df_daily_copy["rain_last_24_hrs"].isnull().all() else 0.0
    highest_taluka = df_daily_copy.loc[df_daily_copy["rain_last_24_hrs"].idxmax()] if not df_daily_copy["rain_last_24_hrs"].isnull().all() and not df_daily_copy.empty else pd.Series({'taluka': 'N/A', 'rain_last_24_hrs': 0})
    percent_against_avg = df_daily_copy["percent_against_avg"].mean() if "percent_against_avg" in df_daily_copy.columns and not df_daily_copy["percent_against_avg"].isnull().all() else 0.0

    metrics = [
        {"title": "State Rainfall (Avg.)", "value": f"{state_avg:.1f} mm"},
        {"title": "Highest Rainfall Taluka", "value": f"{highest_taluka['taluka']}", "subtitle": f"({highest_taluka['rain_last_24_hrs']} mm)"},
        {"title": "State Avg Rainfall (%) Till Today", "value": f"{percent_against_avg:.1f}%"},
    ]
    cols = st.columns(3)
    for i, col in enumerate(cols):
        with col:
            st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
            subtitle_html = f"<p>({metrics[i]['subtitle']})</p>" if 'subtitle' in metrics[i] else ""
            st.markdown(f"<div class='metric-tile'><h4>{metrics[i]['title']}</h4><h2>{metrics[i]['value']}</h2>{subtitle_html}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    
    more_than_200 = df_daily_copy[df_daily_copy['rain_last_24_hrs'] > 200].shape[0]
    more_than_100 = df_daily_copy[df_daily_copy['rain_last_24_hrs'] > 100].shape[0]
    more_than_50 = df_daily_copy[df_daily_copy['rain_last_24_hrs'] > 50].shape[0]

    daily_metrics = [
        {"title": "Talukas > 200 mm", "value": more_than_200},
        {"title": "Talukas > 100 mm", "value": more_than_100},
        {"title": "Talukas > 50 mm", "value": more_than_50},
    ]
    cols_daily = st.columns(3)
    for i, col in enumerate(cols_daily):
        with col:
            st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
            st.markdown(f"<div class='metric-tile'><h4>{daily_metrics[i]['title']}</h4><h2>{daily_metrics[i]['value']}</h2></div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    st.header("Zonewise Rainfall (Average) Summary Table")

    zonal_summary_averages = get_zonal_data(df_daily_copy)

    if not zonal_summary_averages.empty:
        col_table, col_chart = st.columns([1, 1])
        df_daily_renamed_for_table = df_daily_copy.rename(columns={
            'avg_rain': 'Avg_Rain', 'rain_till_yesterday': 'Rain_Till_Yesterday',
            'rain_last_24_hrs': 'Rain_Last_24_Hrs', 'total_rainfall': 'Total_Rainfall',
            'percent_against_avg': 'Percent_Against_Avg'
        })
        zonal_summary_table_df = generate_zonal_summary_table(zonal_summary_averages, df_daily_renamed_for_table)

        with col_table:
            st.markdown("#### Rainfall Averages by Zone")
            st.dataframe(zonal_summary_table_df.style.set_properties(**{'font-weight': 'bold'}, subset=pd.IndexSlice[-1:, :]), use_container_width=True)
        with col_chart:
            st.markdown("#### Zonewise Rainfall vs. % Against Avg.")
            st.plotly_chart(create_zonal_dual_axis_chart(zonal_summary_averages), use_container_width=True)
    else:
        st.warning("Could not generate Zonewise Summary.")

    st.markdown("---")
    st.markdown("### 🗺️ Rainfall Distribution Overview")

    district_rainfall_avg_df = df_daily_copy.groupby('district')['rain_last_24_hrs'].mean().reset_index()
    district_rainfall_avg_df = district_rainfall_avg_df.rename(columns={'rain_last_24_hrs': 'district_avg_rain_last_24_hrs'})
    district_rainfall_avg_df["district"] = district_rainfall_avg_df["district"].str.lower()
    district_rainfall_avg_df["rainfall_category"] = pd.Categorical(district_rainfall_avg_df["district_avg_rain_last_24_hrs"].apply(classify_rainfall), ordered_categories, ordered=True)

    df_map_talukas = df_daily_copy.copy()
    df_map_talukas["taluka"] = df_map_talukas["taluka"].str.strip().str.lower()
    df_map_talukas["rainfall_category"] = pd.Categorical(df_map_talukas["rain_last_24_hrs"].apply(classify_rainfall), ordered_categories, ordered=True)

    taluka_geojson, district_geojson = load_geojson("gujarat_taluka_clean.geojson"), load_geojson("gujarat_district_clean.geojson")
    if not taluka_geojson or not district_geojson:
        st.error("Cannot display maps: One or both GeoJSON files not found.")
        return

    tab_districts, tab_talukas = st.tabs(["Rainfall Distribution by Districts", "Rainfall Distribution by Talukas"])

    with tab_districts:
        map_col_dist, insights_col_dist = st.columns([0.5, 0.5])
        with map_col_dist:
            st.markdown("#### Gujarat Rainfall Map (by District)")
            with st.spinner("Loading district map..."):
                fig_map_districts = plot_choropleth(district_rainfall_avg_df, "gujarat_district_clean.geojson",
                                                    title="Gujarat Daily Rainfall Distribution by District",
                                                    geo_feature_id_key="properties.district", geo_location_col="district")
                st.plotly_chart(fig_map_districts, use_container_width=True)

        with insights_col_dist:
            st.markdown("#### Key Insights & Distributions (Districts)")
            category_counts_dist = df_daily_copy['rainfall_category'].value_counts().reset_index()
            category_counts_dist.columns = ['category', 'count']
            category_counts_dist['category'] = pd.Categorical(category_counts_dist['category'], categories=ordered_categories, ordered=True)
            st.plotly_chart(px.bar(category_counts_dist.sort_values('category'), x='category', y='count',
                                    title='Distribution of Districts by Daily Rainfall Category', labels={'count': 'Number of Districts'},
                                    color='category', color_discrete_map=color_map), use_container_width=True)

    with tab_talukas:
        map_col_tal, insights_col_tal = st.columns([0.5, 0.5])
        with map_col_tal:
            st.markdown("#### Gujarat Rainfall Map (by Taluka)")
            with st.spinner("Loading taluka map..."):
                fig_map_talukas = plot_choropleth(df_map_talukas, "gujarat_taluka_clean.geojson",
                                                  title="Gujarat Daily Rainfall Distribution by Taluka",
                                                  geo_feature_id_key="properties.SUB_DISTRICT", geo_location_col="taluka")
                st.plotly_chart(fig_map_talukas, use_container_width=True)
        with insights_col_tal:
            st.markdown("#### Key Insights & Distributions (Talukas)")
            TOTAL_TALUKAS_GUJARAT = 251
            num_talukas_with_rain_today = df_map_talukas[df_map_talukas['rain_last_24_hrs'] > 0].shape[0]
            pie_data = pd.DataFrame({'category': ['Talukas with Rainfall', 'Talukas without Rainfall'],
                                     'count': [num_talukas_with_rain_today, TOTAL_TALUKAS_GUJARAT - num_talukas_with_rain_today]})
            fig_pie = px.pie(pie_data, values='count', names='category', title="Percentage of Talukas with Daily Rainfall",
                             color='category', color_discrete_map={'Talukas with Rainfall': '#28a745', 'Talukas without Rainfall': '#dc3545'})
            fig_pie.update_traces(textinfo='percent+label', pull=[0.05 if cat == 'Talukas with Rainfall' else 0 for cat in pie_data['category']])
            st.plotly_chart(fig_pie, use_container_width=True)

            category_counts_tal = df_map_talukas['rainfall_category'].value_counts().reset_index()
            category_counts_tal.columns = ['category', 'count']
            category_counts_tal['category'] = pd.Categorical(category_counts_tal['category'], categories=ordered_categories, ordered=True)
            st.plotly_chart(px.bar(category_counts_tal.sort_values('category'), x='category', y='count',
                                    title='Distribution of Talukas by Daily Rainfall Category', labels={'count': 'Number of Talukas'},
                                    color='category', color_discrete_map=color_map), use_container_width=True)

    st.markdown("---")
    st.markdown("### 🏆 Top 10 Talukas by Total Rainfall")
    df_top_10 = df_daily_copy.dropna(subset=['rain_last_24_hrs']).sort_values(by='rain_last_24_hrs', ascending=False).head(10)
    fig_top_10 = px.bar(df_top_10, x='taluka', y='rain_last_24_hrs', color='rain_last_24_hrs', color_continuous_scale=px.colors.sequential.Bluyl,
                        labels={'rain_last_24_hrs': 'Rainfall (mm)', 'taluka': 'Taluka'}, hover_data=['district'], text='rain_last_24_hrs',
                        title='Top 10 Talukas with Highest Daily Rainfall')
    fig_top_10.update_traces(texttemplate='%{text:.1f}', textposition='outside')
    st.plotly_chart(fig_top_10, use_container_width=True)

    st.subheader("📋 Full Daily Rainfall Data Table")
    df_display = df_daily_copy.sort_values(by="rain_last_24_hrs", ascending=False).reset_index(drop=True)
    df_display.index += 1
    display_cols_mapping = {
        'zone': 'Zone', 'district': 'District', 'taluka': 'Taluka',
        'avg_rain': 'Avg_Rain', 'rain_till_yesterday': 'Rain_Till_Yesterday',
        'rain_last_24_hrs': 'Rain_Last_24_Hrs', 'total_rainfall': 'Total_Rainfall',
        'percent_against_avg': 'Percent_Against_Avg'
    }
    st.dataframe(df_display.rename(columns=display_cols_mapping), use_container_width=True, height=400)


# ---------------------------- UI ----------------------------
st.set_page_config(layout="wide")
st.markdown("<div class='title-text'>🌧️ Gujarat Rainfall Dashboard</div>", unsafe_allow_html=True)
st.markdown("---")

st.subheader("🗓️ Select Date for Rainfall Data")
if 'selected_date' not in st.session_state:
    st.session_state.selected_date = datetime.today().date()

col_date_picker, col_prev_btn, col_today_btn, col_next_btn = st.columns([0.2, 0.1, 0.1, 0.1])
with col_date_picker:
    selected_date_from_picker = st.date_input("Choose Date", value=st.session_state.selected_date)
    if selected_date_from_picker != st.session_state.selected_date:
        st.session_state.selected_date = selected_date_from_picker
        st.rerun()

with col_prev_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("⬅️ Previous Day"):
        st.session_state.selected_date -= timedelta(days=1)
        st.rerun()

with col_today_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🗓️ Today"):
        st.session_state.selected_date = datetime.today().date()
        st.rerun()

with col_next_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Next Day ➡️", disabled=(st.session_state.selected_date >= datetime.today().date())):
        st.session_state.selected_date += timedelta(days=1)
        st.rerun()

st.markdown("---")
selected_date = st.session_state.selected_date
selected_year, selected_month, selected_date_str = selected_date.strftime("%Y"), selected_date.strftime("%B"), selected_date.strftime("%Y-%m-%d")

tab_daily, tab_hourly, tab_historical = st.tabs(["Daily Summary", "Hourly Trends", "Historical Data (Coming Soon)"])

with tab_daily:
    st.header("Daily Rainfall Summary")
    df_daily = load_sheet_data(f"24HR_Rainfall_{selected_month}_{selected_year}", f"master24hrs_{selected_date_str}")
    if not df_daily.empty:
        show_24_hourly_dashboard(df_daily, selected_date)
    else:
        st.warning(f"⚠️ Daily data is not available for {selected_date_str}.")

with tab_hourly:
    st.header("Hourly Rainfall Trends (2-Hourly)")
    df_2hr = load_sheet_data(f"2HR_Rainfall_{selected_month}_{selected_year}", f"2hrs_master_{selected_date_str}")
    if not df_2hr.empty:
        time_slot_order = ['06to08', '08to10', '10to12', '12to14', '14to16', '16to18', '18to20', '20to22', '22to24', '24to02', '02to04', '04to06']
        existing_order = [col for col in time_slot_order if col in df_2hr.columns]
        for col in existing_order:
            df_2hr[col] = pd.to_numeric(df_2hr[col], errors="coerce")
        df_2hr['rain_last_24_hrs'] = df_2hr[existing_order].sum(axis=1) if 'rain_last_24_hrs' not in df_2hr.columns else df_2hr['rain_last_24_hrs']

        df_long = df_2hr.melt(id_vars=["district", "taluka", "rain_last_24_hrs"], value_vars=existing_order, var_name="time_slot", value_name="rainfall_mm").dropna(subset=["rainfall_mm"])
        df_long['taluka'] = df_long['taluka'].str.strip()
        df_long = df_long.groupby(["district", "taluka", "time_slot"], as_index=False).agg({"rainfall_mm": "sum", "rain_last_24_hrs": "first"})
        
        slot_labels = {"06to08": "6–8 AM", "08to10": "8–10 AM", "10to12": "10–12 AM", "12to14": "12–2 PM", "14to16": "2–4 PM", "16to18": "4–6 PM", "18to20": "6–8 PM", "20to22": "8–10 PM", "22to24": "10–12 PM", "24to02": "12–2 AM", "02to04": "2–4 AM", "04to06": "4–6 AM"}
        df_long['time_slot_label'] = pd.Categorical(df_long['time_slot'].map(slot_labels), categories=[slot_labels[slot] for slot in existing_order], ordered=True)

        df_2hr['rain_last_24_hrs'] = pd.to_numeric(df_2hr['rain_last_24_hrs'], errors='coerce')
        top_taluka_row = df_2hr.sort_values(by='rain_last_24_hrs', ascending=False).iloc[0] if not df_2hr['rain_last_24_hrs'].dropna().empty else pd.Series({'taluka': 'N/A', 'rain_last_24_hrs': 0})
        df_latest_slot = df_long[df_long['time_slot'] == existing_order[-1]]
        top_latest = df_latest_slot.sort_values(by='rainfall_mm', ascending=False).iloc[0] if not df_latest_slot['rainfall_mm'].dropna().empty else pd.Series({'taluka': 'N/A', 'rainfall_mm': 0})
        num_talukas_with_rain_hourly = df_2hr[df_2hr['rain_last_24_hrs'] > 0].shape[0]

        st.markdown(f"#### 📊 Latest data available for time interval: **{slot_labels[existing_order[-1]]}**")
        
        hourly_metrics = [
            {"title": "Total Talukas with Rainfall", "value": num_talukas_with_rain_hourly},
            {"title": "Top Taluka by Total Rainfall", "value": f"{top_taluka_row['taluka']}<br><p>{top_taluka_row['rain_last_24_hrs']:.1f} mm</p>"},
            {"title": f"Top Taluka in last 2 hour ({slot_labels[existing_order[-1]]})", "value": f"{top_latest['taluka']}<br><p>{top_latest['rainfall_mm']:.1f} mm</p>"}
        ]
        cols_hourly = st.columns(3)
        for i, col in enumerate(cols_hourly):
            with col:
                st.markdown("<div class='metric-container'>", unsafe_allow_html=True)
                st.markdown(f"<div class='metric-tile'><h4>{hourly_metrics[i]['title']}</h4><h2>{hourly_metrics[i]['value']}</h2></div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("### 📈 Rainfall Trend by 2 hourly Time Interval")
        selected_talukas = st.multiselect("Select Taluka(s)", sorted(df_long['taluka'].unique()), default=[top_taluka_row['taluka']] if top_taluka_row['taluka'] != 'N/A' else [])
        if selected_talukas:
            plot_df = df_long[df_long['taluka'].isin(selected_talukas)]
            fig = px.line(plot_df, x="time_slot_label", y="rainfall_mm", color="taluka", markers=True, text="rainfall_mm",
                          title="Rainfall Trend Over Time for Selected Talukas", labels={"rainfall_mm": "Rainfall (mm)"})
            fig.update_traces(textposition="top center")
            fig.update_layout(showlegend=True, modebar_remove=['toImage'])
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Please select at least one Taluka to view the rainfall trend.")
        
        st.markdown("### 📋 Full 2-Hourly Rainfall Data Table")
        df_display_2hr = df_2hr.sort_values(by="rain_last_24_hrs", ascending=False).reset_index(drop=True)
        df_display_2hr.index += 1
        st.dataframe(df_display_2hr, use_container_width=True, height=600)
    else:
        st.warning(f"⚠️ 2-Hourly data is not available for {selected_date_str}.")

with tab_historical:
    st.header("Historical Rainfall Data")
    st.info("💡 **Coming Soon:** This section will feature monthly/seasonal data, year-on-year comparisons, and long-term trends.")
