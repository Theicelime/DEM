import streamlit as st
import time
import requests
import os
import math

# --- 1. 环境配置 ---
os.environ["USE_PYGEOS"] = "0" 

try:
    import pyogrio
    import geopandas as gpd
    # 强制使用 Pyogrio
    gpd.options.io_engine = "pyogrio"
    
    from shapely.geometry import box, Point, Polygon
    from geopy.geocoders import Nominatim
    from geopy.distance import distance as geodist
    import folium
    from streamlit_folium import st_folium
except ImportError as e:
    st.error(f"❌ 环境错误: {e}")
    st.stop()

# --- 2. 页面设置 ---
st.set_page_config(page_title="Geo Data Master Pro", page_icon="🏔️", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f5f5f7; }
    div[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
    .stButton>button { border-radius: 6px; border: 1px solid #ccc; font-weight: 600; }
    .stButton>button:hover { border-color: #007AFF; color: #007AFF; }
    /* 样式微调 */
    .metric-box { background: #eee; padding: 10px; border-radius: 5px; margin-bottom: 10px; font-family: monospace; }
</style>
""", unsafe_allow_html=True)

# --- 3. 核心算法 ---

def get_location(query):
    geolocator = Nominatim(user_agent="geo_master_pro_v7")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except:
        return None
    return None

def generate_geodesic_circle(lat, lon, radius_km):
    """
    生成真正的测地线圆（解决高纬度椭圆变形问题）。
    原理：从中心点向 0-360 度方向分别计算 radius_km 处的坐标点，连成多边形。
    """
    center_loc = (lat, lon)
    points = []
    # 每 5 度取一个点，共 72 个点，足够圆滑
    for bearing in range(0, 361, 5):
        dest = geodist(kilometers=radius_km).destination(center_loc, bearing)
        points.append((dest.longitude, dest.latitude))
    
    return Polygon(points)

def generate_geometry(lat, lon, shape, width_km, height_km, radius_km):
    center_loc = (lat, lon)
    
    if shape == "矩形 (Rectangle)":
        north = geodist(kilometers=height_km/2).destination(center_loc, 0).latitude
        south = geodist(kilometers=height_km/2).destination(center_loc, 180).latitude
        east = geodist(kilometers=width_km/2).destination(center_loc, 90).longitude
        west = geodist(kilometers=width_km/2).destination(center_loc, 270).longitude
        geom = box(west, south, east, north)
        desc = f"{width_km}x{height_km}km"
    else:
        # 使用新算法生成正圆
        geom = generate_geodesic_circle(lat, lon, radius_km)
        desc = f"R{radius_km}km"
        
    return geom, desc

def fetch_opentopo_dem(bounds, api_key):
    minx, miny, maxx, maxy = [round(x, 5) for x in bounds]
    
    # 依然保留 OpenTopo 作为备选，因为它是唯一能自动下载的
    url = "https://portal.opentopography.org/API/globalDem"
    params = {
        'demType': 'SRTMGL1', # 回归最稳的 SRTM
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
        return False, f"HTTP Error {r.status_code}: {r.reason}"
    except Exception as e:
        return False, str(e)

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🏔️ Geo Master Pro")
    
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 34.5000, 'lon': 110.1000, 'addr': 'Hua Shan Region'})
    
    with st.expander("📍 1. 地点搜索", expanded=True):
        q = st.text_input("输入地名", "华山")
        if st.button("搜索"):
            res = get_location(q)
            if res:
                st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
                st.success("已定位")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("未找到，请试着用拼音")

    with st.expander("📐 2. 范围设置", expanded=True):
        shape = st.selectbox("形状", ["矩形 (Rectangle)", "圆形 (Circle)"])
        if shape == "矩形 (Rectangle)":
            c1, c2 = st.columns(2)
            w = c1.number_input("宽 (km)", 0.1, 500.0, 20.0)
            h = c2.number_input("高 (km)", 0.1, 500.0, 20.0)
            r = 0
        else:
            r = st.number_input("半径 (km)", 0.1, 200.0, 10.0)
            w, h = 0, 0

    st.divider()

    # --- 地理空间数据云助手 ---
    st.subheader("🇨🇳 地理空间数据云助手")
    st.info("GSCloud 必须手动下载。请复制以下坐标用于其高级搜索：")
    
    # 这里需要先计算一次bounds来显示
    _, temp_bounds, _ = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r) if 'generate_geodesic_circle' not in globals() else (None, None, None) # Placeholder fix logic below
    
    # 重新实时计算用于显示的 Bounds
    temp_geom, _ = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
    b = temp_geom.bounds # minx, miny, maxx, maxy
    
    st.text_input("最小经度 (Min Lon)", f"{b[0]:.5f}")
    st.text_input("最大经度 (Max Lon)", f"{b[2]:.5f}")
    st.text_input("最小纬度 (Min Lat)", f"{b[1]:.5f}")
    st.text_input("最大纬度 (Max Lat)", f"{b[3]:.5f}")
    
    st.markdown("[👉 前往地理空间数据云 (gscloud.cn)](http://www.gscloud.cn/search)")

# --- 5. 主界面 ---

st.subheader(f"🗺️ {st.session_state['addr']}")

geom, desc = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
bounds = geom.bounds

# --- 地图设置 (DEM 风格) ---
# 使用 OpenTopoMap，它带有明显的等高线和地形阴影
map_key = f"map_{st.session_state['lat']}_{st.session_state['lon']}_{shape}_{w}_{h}_{r}"
m = folium.Map(
    location=[st.session_state['lat'], st.session_state['lon']], 
    zoom_start=11,
    tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attr='Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)'
)

# 绘制几何
folium.GeoJson(
    gdf,
    style_function=lambda x: {
        'fillColor': '#007AFF', 
        'color': '#007AFF', 
        'weight': 3, 
        'fillOpacity': 0.1
    }
).add_to(m)

# 中心点
folium.Marker(
    [st.session_state['lat'], st.session_state['lon']],
    icon=folium.Icon(color='red', icon='info-sign')
).add_to(m)

st_folium(m, height=500, width="100%", key=map_key)

# --- 下载区 ---
st.divider()
c1, c2 = st.columns(2)

with c1:
    st.markdown("### 📥 1. 矢量范围")
    st.download_button(
        "下载 GeoJSON", 
        gdf.to_json(), 
        f"ROI_{desc}.geojson", 
        "application/geo+json", 
        use_container_width=True
    )

with c2:
    st.markdown("### ⛰️ 2. 高程数据 (DEM)")
    
    tab1, tab2 = st.tabs(["OpenTopo API (自动)", "GSCloud (手动)"])
    
    with tab1:
        st.caption("源: SRTM 30m (美国服务器)")
        api_key = st.text_input("OpenTopo API Key", type="password", key="main_key")
        
        if 'dem_data' not in st.session_state: st.session_state['dem_data'] = None
        
        if st.button("🚀 开始下载", use_container_width=True):
            if not api_key:
                st.error("请输入 API Key")
            else:
                with st.spinner("下载中..."):
                    ok, d = fetch_opentopo_dem(bounds, api_key)
                    if ok:
                        st.session_state['dem_data'] = d
                        st.success("完成！")
                    else:
                        st.error(d)
        
        if st.session_state['dem_data']:
            st.download_button("💾 保存 .TIF", st.session_state['dem_data'], f"DEM_{desc}.tif", "image/tiff", use_container_width=True, type="primary")

    with tab2:
        st.write("**地理空间数据云** 无法自动下载，请使用以下信息：")
        st.code(f"""
        数据集选择: GDEMV3 30M 分辨率数字高程数据
        最小经度: {bounds[0]:.5f}
        最大经度: {bounds[2]:.5f}
        最小纬度: {bounds[1]:.5f}
        最大纬度: {bounds[3]:.5f}
        """, language="text")
        st.link_button("前往 GSCloud 高级检索", "http://www.gscloud.cn/search")
