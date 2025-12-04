import streamlit as st
import time
import requests
import os

# --- 1. 环境配置 ---
os.environ["USE_PYGEOS"] = "0" 

try:
    import pyogrio
    import geopandas as gpd
    gpd.options.io_engine = "pyogrio"
    from shapely.geometry import box, Point
    from geopy.geocoders import Nominatim
    from geopy.distance import distance as geodist
    import folium
    from streamlit_folium import st_folium
except ImportError as e:
    st.error(f"❌ 环境错误: {e}")
    st.stop()

# --- 2. 页面设置 ---
st.set_page_config(page_title="Geo Data Master", page_icon="🌍", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f5f5f7; }
    div[data-testid="stSidebar"] { background-color: rgba(255,255,255,0.95); }
    .stButton>button { border-radius: 8px; font-weight: 600; border: 1px solid #d1d1d6; }
    .stButton>button:hover { border-color: #007AFF; color: #007AFF; background: #fff; }
</style>
""", unsafe_allow_html=True)

# --- 3. 逻辑函数 ---

def get_location(query):
    geolocator = Nominatim(user_agent="geo_app_v_final_fix")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except Exception:
        return None
    return None

def generate_geometry(lat, lon, shape, width_km, height_km, radius_km):
    center_loc = (lat, lon)
    center_pt = Point(lon, lat)
    
    if shape == "矩形 (Rectangle)":
        north = geodist(kilometers=height_km/2).destination(center_loc, 0).latitude
        south = geodist(kilometers=height_km/2).destination(center_loc, 180).latitude
        east = geodist(kilometers=width_km/2).destination(center_loc, 90).longitude
        west = geodist(kilometers=width_km/2).destination(center_loc, 270).longitude
        geom = box(west, south, east, north)
        desc = f"{width_km}x{height_km}km"
    else:
        # 近似圆
        geom = center_pt.buffer(radius_km / 111.0)
        desc = f"R{radius_km}km"
        
    return geom, desc

def fetch_opentopo_dem(bounds, api_key, dataset="SRTMGL1"):
    """
    双引擎下载逻辑：
    SRTMGL1 -> 使用 usgsDem 接口 (极其稳定)
    COP30   -> 使用 globalDem 接口 (不稳定，容易404)
    """
    minx, miny, maxx, maxy = [round(x, 5) for x in bounds]
    
    if dataset == "SRTMGL1":
        # 方案 A: SRTM (稳健)
        url = "https://portal.opentopography.org/API/usgsDem"
        params = {
            'datasetName': 'SRTMGL1', # 30m 精度
            'south': miny, 'north': maxy, 'west': minx, 'east': maxx,
            'outputFormat': 'GTiff',
            'API_Key': api_key
        }
    else:
        # 方案 B: Copernicus (新，但不稳)
        url = "https://portal.opentopography.org/API/globalDem"
        params = {
            'demType': 'COP30',
            'south': miny, 'north': maxy, 'west': minx, 'east': maxx,
            'outputFormat': 'GTiff',
            'API_Key': api_key
        }
    
    try:
        r = requests.get(url, params=params, stream=True, timeout=60)
        
        if r.status_code == 200:
            ctype = r.headers.get('Content-Type', '')
            if 'text/html' in ctype:
                return False, f"API 返回错误信息 (可能是 Key 无效或范围过大): {r.text[:300]}"
            return True, r.content
        elif r.status_code == 404:
            return False, f"404 未找到。原因：所选数据源 {dataset} 在该区域无覆盖，或 API 暂时不可用。请尝试切换数据源为 SRTMGL1。"
        elif r.status_code == 401:
            return False, "401 未授权。请检查 API Key 是否正确。"
        else:
            return False, f"HTTP Error {r.status_code}: {r.reason}"
    except Exception as e:
        return False, str(e)

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🎛️ 设置面板")
    
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 34.4871, 'lon': 110.0847, 'addr': 'Hua Shan'})
    
    q = st.text_input("📍 地点搜索", "华山")
    if st.button("搜索"):
        res = get_location(q)
        if res:
            st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
            st.success("已定位")
            st.rerun()
        else:
            st.error("未找到")
            
    st.divider()
    
    shape = st.selectbox("形状", ["矩形 (Rectangle)", "圆形 (Circle)"])
    if shape == "矩形 (Rectangle)":
        c1, c2 = st.columns(2)
        w = c1.number_input("宽 (km)", 0.1, 200.0, 10.0)
        h = c2.number_input("高 (km)", 0.1, 200.0, 10.0)
        r = 0
    else:
        r = st.number_input("半径 (km)", 0.1, 100.0, 5.0)
        w, h = 0, 0
        
    st.divider()
    
    # === 关键修改：数据源选择 ===
    st.subheader("📡 数据源")
    dem_source = st.selectbox(
        "选择高程数据类型", 
        ["SRTMGL1 (推荐, 最稳)", "COP30 (新, 易报错)"],
        index=0
    )
    dataset_code = "SRTMGL1" if "SRTM" in dem_source else "COP30"
    
    api_key = st.text_input("🔑 API Key (必填)", type="password")
    if not api_key:
        st.warning("请填写 Key，否则 99% 会下载失败")

# --- 5. 主界面 ---

st.title("Geo Data Master")
st.caption(f"当前中心: {st.session_state['addr']}")

geom, desc = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
bounds = geom.bounds

# 动态地图 Key
map_key = f"map_{st.session_state['lat']}_{st.session_state['lon']}_{w}_{h}_{r}"

m = folium.Map([st.session_state['lat'], st.session_state['lon']], zoom_start=12)
folium.GeoJson(gdf, style_function=lambda x: {'color':'#007AFF', 'fillOpacity':0.2}).add_to(m)
folium.Marker([st.session_state['lat'], st.session_state['lon']]).add_to(m)

st_folium(m, height=400, width="100%", key=map_key)

st.divider()

c1, c2 = st.columns(2)
with c1:
    st.subheader("1. 矢量 (GeoJSON)")
    st.download_button("⬇️ 下载 GeoJSON", gdf.to_json(), f"{desc}.geojson", "application/geo+json", use_container_width=True)

with c2:
    st.subheader("2. 高程 (DEM)")
    st.caption(f"当前使用源: {dataset_code}")
    
    if 'dem_data' not in st.session_state: st.session_state['dem_data'] = None
    
    if st.button("🚀 获取 DEM", use_container_width=True):
        if not api_key:
            st.error("❌ 必须填写 API Key 才能使用 API 下载")
        else:
            with st.spinner(f"正在从 {dataset_code} 下载..."):
                # 调用函数
                ok, d = fetch_opentopo_dem(bounds, api_key, dataset_code)
                if ok:
                    st.session_state['dem_data'] = d
                    st.success("✅ 下载成功！")
                    st.rerun()
                else:
                    st.error(d)
                    
    if st.session_state['dem_data']:
        st.download_button("💾 保存 .TIF", st.session_state['dem_data'], f"DEM_{desc}_{dataset_code}.tif", "image/tiff", type="primary", use_container_width=True)
