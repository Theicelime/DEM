import streamlit as st
import time
import requests
import os

# --- 1. 核心环境配置 ---
# 这一步非常关键：告诉系统优先使用 Pyogrio (自带GDAL)，而不是去寻找不存在的系统库
os.environ["USE_PYGEOS"] = "0" 

try:
    # 尝试导入必要的库
    import pyogrio
    import geopandas as gpd
    
    # 强制 GeoPandas 使用 Pyogrio 引擎
    gpd.options.io_engine = "pyogrio"
    
    from shapely.geometry import box, Point
    from geopy.geocoders import Nominatim
    from geopy.distance import distance as geodist
    import folium
    from streamlit_folium import st_folium

except ImportError as e:
    # 这里的错误提示更新了，不再误导你去改 packages.txt
    st.error(f"""
    ❌ **核心组件加载失败**
    
    原因: {e}
    
    **修复方法**:
    1. 确保 GitHub 仓库中 **已删除 packages.txt** (必须删除)。
    2. 确保 requirements.txt 中包含 `pyogrio`。
    3. 在 Streamlit 后台点击 'Reboot App' 清除缓存。
    """)
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
    geolocator = Nominatim(user_agent="geo_tool_final")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except:
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

def fetch_opentopo_dem(bounds, api_key):
    minx, miny, maxx, maxy = [round(x, 5) for x in bounds]
    
    url = "https://portal.opentopography.org/API/usgsDem"
    params = {
        'datasetName': 'COP30', 
        'south': miny, 'north': maxy, 'west': minx, 'east': maxx,
        'outputFormat': 'GTiff',
        'API_Key': api_key
    }
    
    try:
        r = requests.get(url, params=params, stream=True, timeout=60)
        if r.status_code == 200:
            if 'text/html' in r.headers.get('Content-Type', ''):
                return False, f"API Error: {r.text[:200]}"
            return True, r.content
        return False, f"Status {r.status_code}"
    except Exception as e:
        return False, str(e)

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🎛️ Geo Master")
    
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 27.9881, 'lon': 86.9250, 'addr': 'Everest'})
    
    q = st.text_input("📍 地点", "珠穆朗玛峰")
    if st.button("搜索"):
        res = get_location(q)
        if res:
            st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
            st.success("已定位")
            st.rerun()
        else:
            st.error("无结果")
            
    st.divider()
    
    shape = st.selectbox("形状", ["矩形 (Rectangle)", "圆形 (Circle)"])
    if shape == "矩形 (Rectangle)":
        c1, c2 = st.columns(2)
        w = c1.number_input("宽 (km)", 1.0, 500.0, 10.0)
        h = c2.number_input("高 (km)", 1.0, 500.0, 10.0)
        r = 0
    else:
        r = st.number_input("半径 (km)", 1.0, 200.0, 5.0)
        w, h = 0, 0
        
    st.divider()
    api_key = st.text_input("🔑 OpenTopo API Key", type="password")

# --- 5. 主界面 ---

st.title("Geo Data Master")
st.caption(f"当前: {st.session_state['addr']}")

geom, desc = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
bounds = geom.bounds

# 地图
m = folium.Map([st.session_state['lat'], st.session_state['lon']], zoom_start=11)
folium.GeoJson(gdf, style_function=lambda x: {'color':'#007AFF', 'fillOpacity':0.2}).add_to(m)
st_folium(m, height=400, width="100%")

st.divider()

c1, c2 = st.columns(2)
with c1:
    st.subheader("1. 矢量 (GeoJSON)")
    st.download_button("⬇️ 下载 GeoJSON", gdf.to_json(), f"{desc}.geojson", "application/geo+json", use_container_width=True)

with c2:
    st.subheader("2. 高程 (DEM)")
    
    if 'dem_data' not in st.session_state: st.session_state['dem_data'] = None
    
    if st.button("🚀 获取 DEM", use_container_width=True):
        if not api_key:
            st.error("需要 API Key")
        else:
            with st.spinner("下载中..."):
                ok, d = fetch_opentopo_dem(bounds, api_key)
                if ok:
                    st.session_state['dem_data'] = d
                    st.rerun()
                else:
                    st.error(d)
                    
    if st.session_state['dem_data']:
        st.download_button("💾 保存 .TIF", st.session_state['dem_data'], f"DEM_{desc}.tif", "image/tiff", type="primary", use_container_width=True)
