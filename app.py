import streamlit as st
import time
import requests

# --- 1. 稳健的 Import 检查 ---
try:
    import geopandas as gpd
    from shapely.geometry import box, Point
    from geopy.geocoders import Nominatim
    from geopy.distance import distance as geodist
    import folium
    from streamlit_folium import st_folium
except ImportError as e:
    st.error(f"""
    ❌ **环境配置错误**: 缺少必要的 GIS 库。
    
    如果是 Streamlit Cloud，请确保仓库根目录包含 **packages.txt** 文件，内容为:
    `gdal-bin`
    `libgdal-dev`
    
    详细错误: {e}
    """)
    st.stop()

# --- 2. 页面配置 ---
st.set_page_config(page_title="Geo Data Master", page_icon="🌍", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f5f5f7; }
    div[data-testid="stSidebar"] { background-color: rgba(255,255,255,0.9); }
    .stButton>button { border-radius: 8px; font-weight: 600; }
    .success-box { padding: 10px; background-color: #d1fae5; border-radius: 8px; color: #065f46; margin-bottom: 10px;}
</style>
""", unsafe_allow_html=True)

# --- 3. 核心功能函数 ---

def get_location(query):
    """搜索地点坐标，增加重试机制"""
    geolocator = Nominatim(user_agent="geo_master_v2")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except Exception as e:
        st.sidebar.error(f"搜索超时或错误: {e}")
    return None

def generate_geometry(lat, lon, shape, width_km, height_km, radius_km):
    """生成几何形状"""
    center_loc = (lat, lon)
    center_pt = Point(lon, lat)
    
    if shape == "矩形 (Rectangle)":
        # 计算矩形边界 (WGS84 Geodesic)
        north = geodist(kilometers=height_km/2).destination(center_loc, 0).latitude
        south = geodist(kilometers=height_km/2).destination(center_loc, 180).latitude
        east = geodist(kilometers=width_km/2).destination(center_loc, 90).longitude
        west = geodist(kilometers=width_km/2).destination(center_loc, 270).longitude
        
        geom = box(west, south, east, north)
        bounds = (west, south, east, north)
        desc = f"{width_km}x{height_km}km"
    else:
        # 近似圆 (Buffer in degrees)
        # 1度纬度 ~= 111km, 简单近似处理用于显示和大致范围
        approx_deg = radius_km / 111.0
        geom = center_pt.buffer(approx_deg)
        bounds = geom.bounds
        desc = f"R{radius_km}km"
        
    return geom, bounds, desc

def fetch_opentopo_dem(bounds, api_key):
    """请求 OpenTopography API"""
    minx, miny, maxx, maxy = bounds
    
    # 强制精度控制，防止 API 报错
    minx, miny, maxx, maxy = [round(x, 5) for x in [minx, miny, maxx, maxy]]
    
    url = "https://portal.opentopography.org/API/usgsDem"
    params = {
        'datasetName': 'COP30', # Copernicus 30m
        'south': miny, 'north': maxy, 'west': minx, 'east': maxx,
        'outputFormat': 'GTiff',
        'API_Key': api_key
    }
    
    try:
        # Stream=True 防止内存爆炸
        r = requests.get(url, params=params, stream=True, timeout=90)
        if r.status_code == 200:
            content_type = r.headers.get('Content-Type', '')
            if 'text/html' in content_type:
                return False, f"API 返回了错误页面: {r.text[:200]}"
            return True, r.content
        else:
            return False, f"HTTP Error {r.status_code}: {r.reason}"
    except Exception as e:
        return False, str(e)

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🎛️ 设置")
    
    # Session State 初始化
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 27.9881, 'lon': 86.9250, 'addr': 'Mount Everest'})
    
    # 搜索
    query = st.text_input("📍 地点搜索", "珠穆朗玛峰")
    if st.button("Go", key="search_btn"):
        res = get_location(query)
        if res:
            st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
            st.success("已定位")
            # 强制刷新以更新地图中心
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("未找到该地点")

    st.divider()

    # 参数
    shape_type = st.selectbox("形状", ["矩形 (Rectangle)", "圆形 (Circle)"])
    if shape_type == "矩形 (Rectangle)":
        c1, c2 = st.columns(2)
        w_km = c1.number_input("宽 (km)", 1.0, 200.0, 10.0)
        h_km = c2.number_input("高 (km)", 1.0, 200.0, 10.0)
        r_km = 0
    else:
        r_km = st.number_input("半径 (km)", 1.0, 100.0, 5.0)
        w_km, h_km = 0, 0

    st.divider()
    
    # API Key
    with st.expander("🔑 API Key (建议)", expanded=True):
        api_key = st.text_input("OpenTopo Key", type="password", help="免费申请: my.opentopography.org")
        if not api_key:
            st.warning("无 Key 可能导致下载失败")

# --- 5. 主界面 ---

st.title("Geo Data Master")
st.caption(f"当前中心: {st.session_state['addr']}")

# 计算
geom, bounds, desc = generate_geometry(
    st.session_state['lat'], st.session_state['lon'], 
    shape_type, w_km, h_km, r_km
)

# 1. 地图预览
m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=11, tiles="OpenStreetMap")

# 创建 GeoDataFrame 用于绘图
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")

# 样式
folium.GeoJson(
    gdf,
    style_function=lambda x: {'fillColor': '#007AFF', 'color': '#007AFF', 'weight': 2, 'fillOpacity': 0.2}
).add_to(m)

folium.Marker(
    [st.session_state['lat'], st.session_state['lon']], 
    icon=folium.Icon(color="red", icon="info-sign")
).add_to(m)

st_folium(m, height=450, width="100%")

st.divider()

# --- 6. 下载区域 (逻辑优化版) ---
c1, c2 = st.columns(2)

with c1:
    st.subheader("1. 矢量数据 (GeoJSON)")
    st.info("包含您选定的范围框 (WGS84)")
    geojson_data = gdf.to_json()
    st.download_button(
        label="⬇️ 下载 GeoJSON",
        data=geojson_data,
        file_name=f"Area_{desc}.geojson",
        mime="application/geo+json",
        use_container_width=True
    )

with c2:
    st.subheader("2. 高程数据 (DEM)")
    st.write("Copernicus GLO-30 (30m精度)")

    # 状态管理：检查是否有已缓存的 DEM 数据
    # 如果不使用 session_state，点击下载按钮后页面刷新，数据就会丢失，导致无法保存
    if 'dem_file_cache' not in st.session_state:
        st.session_state['dem_file_cache'] = None
    
    # 获取按钮
    if st.button("🚀 获取 DEM 数据", use_container_width=True):
        if not api_key:
            st.error("请在侧边栏填写 API Key，否则无法下载数据。")
        else:
            with st.spinner("正在连接卫星数据服务器... (可能需要30秒)"):
                success, result = fetch_opentopo_dem(bounds, api_key)
                if success:
                    st.session_state['dem_file_cache'] = result
                    st.success("✅ 数据获取成功！请点击下方按钮保存文件。")
                else:
                    st.error(f"下载失败: {result}")

    # 如果有缓存数据，显示保存按钮
    if st.session_state['dem_file_cache']:
        st.download_button(
            label="💾 保存 .TIF 文件到本地",
            data=st.session_state['dem_file_cache'],
            file_name=f"DEM_{desc}.tif",
            mime="image/tiff",
            use_container_width=True,
            type="primary"
        )
