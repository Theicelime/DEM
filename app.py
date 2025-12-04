import streamlit as st
import time
import requests
import os

# --- 1. 环境配置 ---
os.environ["USE_PYGEOS"] = "0" 

try:
    import pyogrio
    import geopandas as gpd
    # 强制使用 Pyogrio，避免系统依赖冲突
    gpd.options.io_engine = "pyogrio"
    
    from shapely.geometry import box, Point
    from geopy.geocoders import Nominatim
    from geopy.distance import distance as geodist
    import folium
    from streamlit_folium import st_folium
except ImportError as e:
    st.error(f"❌ 环境错误: {e}")
    st.stop()

# --- 2. 页面配置 ---
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
    # 随机化 User-Agent 避免被拦截
    geolocator = Nominatim(user_agent="geo_app_v8_final")
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

def fetch_opentopo_dem(bounds, api_key, dataset_id):
    minx, miny, maxx, maxy = [round(x, 5) for x in bounds]
    
    # 统一使用 globalDem 接口
    url = "https://portal.opentopography.org/API/globalDem"
    
    params = {
        'demType': dataset_id,  # SRTMGL1, COP30, AW3D30
        'south': miny, 
        'north': maxy, 
        'west': minx, 
        'east': maxx,
        'outputFormat': 'GTiff',
        'API_Key': api_key
    }
    
    try:
        # 增加超时时间到 90秒，防止大文件下载断开
        r = requests.get(url, params=params, stream=True, timeout=90)
        
        if r.status_code == 200:
            ctype = r.headers.get('Content-Type', '')
            if 'text/html' in ctype:
                # API 虽然返回200，但内容是报错页面
                return False, f"API 返回错误信息 (请检查API Key或更换数据源): {r.text[:300]}"
            return True, r.content
        elif r.status_code == 401:
            return False, "❌ 401 未授权：API Key 错误或未填写。"
        elif r.status_code == 404:
            return False, f"❌ 404 错误：数据源 '{dataset_id}' 在此区域无覆盖，请尝试切换到 'SRTMGL1'。"
        else:
            return False, f"HTTP Error {r.status_code}: {r.reason}"
    except Exception as e:
        return False, str(e)

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🎛️ Geo Master")
    
    # 状态初始化
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 27.9881, 'lon': 86.9250, 'addr': 'Mount Everest'})
    
    # 搜索
    q = st.text_input("📍 地点搜索", "珠穆朗玛峰")
    if st.button("Go"):
        res = get_location(q)
        if res:
            st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
            st.success("已定位")
            st.rerun()
        else:
            st.error("未找到")
            
    st.divider()
    
    # 形状参数
    shape = st.selectbox("形状", ["矩形 (Rectangle)", "圆形 (Circle)"])
    if shape == "矩形 (Rectangle)":
        c1, c2 = st.columns(2)
        w = c1.number_input("宽 (km)", 0.1, 500.0, 10.0)
        h = c2.number_input("高 (km)", 0.1, 500.0, 10.0)
        r = 0
    else:
        r = st.number_input("半径 (km)", 0.1, 200.0, 5.0)
        w, h = 0, 0

    st.divider()

    # --- 关键修改：数据源选择 ---
    st.subheader("📡 数据源设置")
    dataset_choice = st.selectbox(
        "DEM 数据源", 
        ["SRTMGL1 (NASA 30m - 最稳)", "COP30 (Copernicus 30m - 最新)", "AW3D30 (ALOS 30m)"],
        index=0 # 默认选 SRTM，防止 404
    )
    
    # 提取实际 ID
    dataset_map = {
        "SRTMGL1 (NASA 30m - 最稳)": "SRTMGL1",
        "COP30 (Copernicus 30m - 最新)": "COP30",
        "AW3D30 (ALOS 30m)": "AW3D30"
    }
    dataset_id = dataset_map[dataset_choice]

    api_key = st.text_input("🔑 OpenTopo API Key", type="password")
    if not api_key:
        st.warning("提示: 大部分数据源现在强制要求 API Key")

# --- 5. 主界面 ---

st.title("Geo Data Master")
st.caption(f"当前中心: {st.session_state['addr']}")

# 计算几何
geom, desc = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
bounds = geom.bounds

# 动态地图 Key，强制刷新
map_key = f"m_{st.session_state['lat']}_{w}_{h}_{r}"
m = folium.Map([st.session_state['lat'], st.session_state['lon']], zoom_start=11)
folium.GeoJson(gdf, style_function=lambda x: {'color':'#007AFF', 'fillOpacity':0.2}).add_to(m)
folium.Marker([st.session_state['lat'], st.session_state['lon']]).add_to(m)
st_folium(m, height=400, width="100%", key=map_key)

st.divider()

c1, c2 = st.columns(2)

with c1:
    st.subheader("1. 矢量 (GeoJSON)")
    st.download_button("⬇️ 下载 GeoJSON", gdf.to_json(), f"{desc}.geojson", "application/geo+json", use_container_width=True)

with c2:
    st.subheader(f"2. 高程 ({dataset_id})")
    
    if 'dem_data' not in st.session_state: st.session_state['dem_data'] = None
    
    if st.button("🚀 获取 DEM 数据", use_container_width=True):
        if not api_key:
            st.error("请先在侧边栏填写 API Key！")
        else:
            with st.spinner(f"正在从 OpenTopography 请求 {dataset_id}..."):
                ok, res = fetch_opentopo_dem(bounds, api_key, dataset_id)
                if ok:
                    st.session_state['dem_data'] = res
                    st.success("下载成功！")
                    st.rerun()
                else:
                    st.error(res)
                    
    if st.session_state['dem_data']:
        st.download_button("💾 保存 .TIF", st.session_state['dem_data'], f"DEM_{dataset_id}_{desc}.tif", "image/tiff", type="primary", use_container_width=True)
