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
    # 更换 User-Agent 防止被 OpenStreetMap 拦截
    geolocator = Nominatim(user_agent="my_geo_app_v5_unique")
    try:
        location = geolocator.geocode(query, timeout=15) # 增加超时时间
        if location:
            return location.latitude, location.longitude, location.address
    except Exception as e:
        print(f"Geocoding error: {e}") # 在后台打印错误
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
    
    # --- 关键修复：使用 globalDem 接口 ---
    url = "https://portal.opentopography.org/API/globalDem"
    params = {
        'demType': 'COP30',  # 参数名从 datasetName 改为 demType
        'south': miny, 
        'north': maxy, 
        'west': minx, 
        'east': maxx,
        'outputFormat': 'GTiff',
        'API_Key': api_key
    }
    
    try:
        r = requests.get(url, params=params, stream=True, timeout=60)
        
        # 调试信息：如果失败，尝试打印原因
        if r.status_code == 200:
            if 'text/html' in r.headers.get('Content-Type', ''):
                return False, f"API 鉴权失败或忙: {r.text[:200]}"
            return True, r.content
        elif r.status_code == 401:
            return False, "API Key 无效或未填写"
        elif r.status_code == 404:
            return False, "404 错误：该区域无 COP30 数据覆盖，或 API 地址变动"
        else:
            return False, f"HTTP Error {r.status_code}: {r.reason}"
    except Exception as e:
        return False, str(e)

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🎛️ Geo Master")
    
    # 状态初始化
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 34.4871, 'lon': 110.0847, 'addr': 'Hua Shan (Default)'}) # 默认改为华山附近
    
    q = st.text_input("📍 地点", "华山")
    if st.button("搜索"):
        with st.spinner("正在搜索..."):
            res = get_location(q)
            if res:
                st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
                st.success(f"已定位: {res[2][:20]}...")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("未找到地点，请尝试输入英文拼音 (e.g. 'Hua Shan')")
            
    st.divider()
    
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
    api_key = st.text_input("🔑 OpenTopo API Key", type="password")
    if not api_key:
        st.caption("⚠️ 注意：COP30 数据通常必须要有 API Key 才能下载")

# --- 5. 主界面 ---

st.title("Geo Data Master")
st.caption(f"当前中心: {st.session_state['addr']}")

geom, desc = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
bounds = geom.bounds

# 地图 - 关键修复：添加动态 Key
# 这里的 key=... 确保了当坐标改变时，地图会被完全重绘，而不是没反应
map_key = f"map_{st.session_state['lat']}_{st.session_state['lon']}_{shape}_{w}_{h}_{r}"

m = folium.Map([st.session_state['lat'], st.session_state['lon']], zoom_start=12)
folium.GeoJson(gdf, style_function=lambda x: {'color':'#007AFF', 'fillOpacity':0.2}).add_to(m)
folium.Marker([st.session_state['lat'], st.session_state['lon']]).add_to(m)

# 渲染地图
st_folium(m, height=400, width="100%", key=map_key)

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
            st.error("请在侧边栏填写 API Key (必填)")
        else:
            with st.spinner(f"正在下载 {desc} 范围的 DEM 数据..."):
                ok, d = fetch_opentopo_dem(bounds, api_key)
                if ok:
                    st.session_state['dem_data'] = d
                    st.success("下载成功！请点击下方按钮保存。")
                    st.rerun()
                else:
                    st.error(d)
                    
    if st.session_state['dem_data']:
        st.download_button("💾 保存 .TIF", st.session_state['dem_data'], f"DEM_{desc}.tif", "image/tiff", type="primary", use_container_width=True)
