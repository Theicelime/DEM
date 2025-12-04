import streamlit as st
import geopandas as gpd
from shapely.geometry import box, Point, Polygon
from geopy.geocoders import Nominatim
from geopy.distance import distance as geodist
import folium
from streamlit_folium import st_folium
import requests
import json
import io

# --- 页面配置 ---
st.set_page_config(page_title="Geo Data Master", page_icon="🌍", layout="wide")

# Apple 风格 CSS 注入
st.markdown("""
<style>
    .stApp { background-color: #f5f5f7; }
    .css-1d391kg { padding-top: 2rem; }
    /* 侧边栏样式 */
    section[data-testid="stSidebar"] {
        background-color: rgba(255, 255, 255, 0.8);
        backdrop-filter: blur(20px);
    }
    /* 按钮样式 */
    .stButton>button {
        width: 100%;
        border-radius: 12px;
        height: 3em;
        font-weight: 600;
        border: none;
        transition: 0.3s;
    }
    .stButton>button:hover { transform: scale(0.98); opacity: 0.9; }
</style>
""", unsafe_allow_html=True)

# --- 核心函数 ---

def get_location(query):
    """搜索地点坐标"""
    geolocator = Nominatim(user_agent="geo_master_tool")
    try:
        location = geolocator.geocode(query)
        if location:
            return location.latitude, location.longitude, location.address
    except:
        return None
    return None

def generate_geometry(lat, lon, shape, width_km, height_km, radius_km):
    """基于 WGS84 测地线生成几何图形"""
    center = Point(lon, lat) # Shapely use (Lon, Lat)
    
    if shape == "矩形 (Rectangle)":
        # 使用 geopy 计算四个方向的距离
        # 注意：这是估算矩形，从中心向四周扩散
        center_loc = (lat, lon)
        
        # 计算北边界和南边界
        north_pt = geodist(kilometers=height_km/2).destination(center_loc, 0)
        south_pt = geodist(kilometers=height_km/2).destination(center_loc, 180)
        
        # 计算东边界和西边界
        east_pt = geodist(kilometers=width_km/2).destination(center_loc, 90)
        west_pt = geodist(kilometers=width_km/2).destination(center_loc, 270)
        
        minx = west_pt.longitude
        maxx = east_pt.longitude
        miny = south_pt.latitude
        maxy = north_pt.latitude
        
        geom = box(minx, miny, maxx, maxy)
        bounds = (minx, miny, maxx, maxy)
        desc = f"{width_km}x{height_km}km"
        
    else: # 圆形
        # 在 Web Mercator 下画圆会有形变，为了 GeoJSON 兼容性，我们生成近似圆的多边形
        # 这里为了简单，生成一个基于 buffer 的圆（注意：Shapely buffer 是平面计算，但在小尺度下可接受）
        # 更严谨的做法是生成多点再连线，这里简化处理
        # 估算度数：1度 ≈ 111km
        approx_deg = radius_km / 111.0 
        geom = center.buffer(approx_deg)
        bounds = geom.bounds
        desc = f"R{radius_km}km"
        
    return geom, bounds, desc

def download_dem_from_opentopo(bounds, api_key):
    """后端直接请求 OpenTopography API"""
    minx, miny, maxx, maxy = bounds
    
    # URL 构建 (使用 SRTM GL1 30m 或 Copernicus)
    # 推荐使用 Copernicus GLO-30 (COP30)
    base_url = "https://portal.opentopography.org/API/usgsDem"
    
    params = {
        'datasetName': 'COP30', # 或者 SRTMGL1
        'south': miny,
        'north': maxy,
        'west': minx,
        'east': maxx,
        'outputFormat': 'GTiff',
        'API_Key': api_key
    }
    
    try:
        response = requests.get(base_url, params=params, stream=True, timeout=60)
        if response.status_code == 200:
            # 检查内容类型，防止返回报错 HTML
            if 'text/html' in response.headers.get('Content-Type', ''):
                return False, f"API 错误: {response.text[:200]}"
            return True, response.content
        else:
            return False, f"HTTP 错误: {response.status_code} - {response.reason}"
    except Exception as e:
        return False, str(e)

# --- 侧边栏 UI ---

with st.sidebar:
    st.title("🎛️ 控制面板")
    
    # 1. API Key 设置
    with st.expander("🔑 设置 API Key (推荐)", expanded=True):
        api_key = st.text_input("OpenTopography API Key", type="password", help="去 opentopography.org 免费申请。不填可能无法下载 DEM。")
        st.caption("虽然部分数据免费，但拥有 Key 能保证下载稳健。")

    # 2. 搜索
    st.subheader("1. 定位")
    loc_input = st.text_input("输入地点", "珠穆朗玛峰")
    if st.button("🔍 搜索地点"):
        res = get_location(loc_input)
        if res:
            st.session_state['lat'] = res[0]
            st.session_state['lon'] = res[1]
            st.session_state['addr'] = res[2]
            st.success("已定位")
        else:
            st.error("未找到地点")

    # 3. 参数
    st.subheader("2. 形状参数")
    shape_type = st.selectbox("形状类型", ["矩形 (Rectangle)", "圆形 (Circle)"])
    
    if shape_type == "矩形 (Rectangle)":
        col1, col2 = st.columns(2)
        w_km = col1.number_input("宽度 (km)", 1.0, 500.0, 10.0)
        h_km = col2.number_input("高度 (km)", 1.0, 500.0, 10.0)
        r_km = 0
    else:
        r_km = st.number_input("半径 (km)", 1.0, 250.0, 5.0)
        w_km, h_km = 0, 0

# --- 主界面 ---

st.title("Geo Data Master (Python Edition)")
st.caption("WGS84 坐标系 | Python 后端处理 | 稳健下载")

# 检查 Session State
if 'lat' not in st.session_state:
    st.session_state['lat'] = 27.9881
    st.session_state['lon'] = 86.9250
    st.session_state['addr'] = "Mount Everest"

# 计算几何
geom, bounds, size_desc = generate_geometry(
    st.session_state['lat'], 
    st.session_state['lon'], 
    shape_type, w_km, h_km, r_km
)

# 生成 GeoDataFrame
gdf = gpd.GeoDataFrame(
    {'name': [loc_input], 'desc': [size_desc]}, 
    geometry=[geom], 
    crs="EPSG:4326"
)

# 地图预览
m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=11, tiles="CartoDB voyager")
folium.GeoJson(
    gdf,
    style_function=lambda x: {'fillColor': '#007AFF', 'color': '#007AFF', 'weight': 2, 'fillOpacity': 0.2}
).add_to(m)
folium.Marker([st.session_state['lat'], st.session_state['lon']], tooltip=st.session_state['addr']).add_to(m)

st_folium(m, height=400, width="100%")

# --- 下载区域 ---

st.divider()
st.subheader("📂 数据导出")

col_d1, col_d2 = st.columns(2)

# 1. GeoJSON 下载
with col_d1:
    st.info("🌐 **矢量范围数据**")
    geojson_str = gdf.to_json()
    file_name_geo = f"{loc_input}_{size_desc}_WGS84.geojson"
    
    st.download_button(
        label=f"⬇️ 下载 GeoJSON ({file_name_geo})",
        data=geojson_str,
        file_name=file_name_geo,
        mime="application/geo+json",
        use_container_width=True
    )

# 2. DEM 下载
with col_d2:
    st.success("⛰️ **高程模型数据 (DEM)**")
    st.write(f"数据源: Copernicus GLO-30 (30m精度)")
    
    dem_file_name = f"{loc_input}_{size_desc}_DEM.tif"
    
    # 按钮逻辑：点击后由 Python 后端下载
    if st.button("⬇️ 开始处理并下载 GeoTIFF", use_container_width=True):
        if not api_key:
            st.warning("⚠️ 未检测到 API Key。如果没有 Key，下载可能会失败。建议在左侧侧边栏填入。")
        
        with st.spinner("正在连接 OpenTopography 服务器下载数据 (请稍候)..."):
            success, data = download_dem_from_opentopo(bounds, api_key)
            
            if success:
                st.download_button(
                    label="✅ 数据已准备好，点击保存",
                    data=data,
                    file_name=dem_file_name,
                    mime="image/tiff",
                    key="dem_save_btn",
                    use_container_width=True
                )
            else:
                st.error(f"下载失败: {data}")
                st.markdown("[点击这里手动去 OpenTopography 下载](https://portal.opentopography.org/datasets)")
