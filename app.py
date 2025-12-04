import streamlit as st
import time
import requests
import os

# --- 1. 环境配置与 Import ---
# 强制使用 Pyogrio 引擎 (自带 GDAL 二进制，解决 Linux 依赖冲突)
os.environ["USE_PYGEOS"] = "0" 

try:
    import geopandas as gpd
    # 尝试设置默认引擎为 pyogrio，如果失败则回退
    try:
        import pyogrio
        gpd.options.io_engine = "pyogrio"
    except ImportError:
        pass

    from shapely.geometry import box, Point
    from geopy.geocoders import Nominatim
    from geopy.distance import distance as geodist
    import folium
    from streamlit_folium import st_folium
except ImportError as e:
    st.error(f"""
    ❌ **环境加载失败**: {e}
    
    请确保 requirements.txt 中包含: `geopandas`, `pyogrio`
    并且 **请务必删除 packages.txt 文件** (如果存在)，因为它会导致系统冲突。
    """)
    st.stop()

# --- 2. 页面样式配置 ---
st.set_page_config(page_title="Geo Data Master", page_icon="🌍", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f5f5f7; }
    div[data-testid="stSidebar"] { background-color: rgba(255,255,255,0.9); }
    .stButton>button { border-radius: 8px; font-weight: 600; border: 1px solid #e0e0e0; }
    .stButton>button:hover { border-color: #007AFF; color: #007AFF; }
    h1, h2, h3 { color: #1d1d1f; }
</style>
""", unsafe_allow_html=True)

# --- 3. 核心逻辑函数 ---

def get_location(query):
    """搜索地点坐标"""
    geolocator = Nominatim(user_agent="geo_master_app_v3")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except Exception as e:
        st.sidebar.error(f"搜索服务繁忙: {e}")
    return None

def generate_geometry(lat, lon, shape, width_km, height_km, radius_km):
    """生成几何图形"""
    center_loc = (lat, lon)
    center_pt = Point(lon, lat)
    
    if shape == "矩形 (Rectangle)":
        # 计算矩形边界 (Geodesic)
        north = geodist(kilometers=height_km/2).destination(center_loc, 0).latitude
        south = geodist(kilometers=height_km/2).destination(center_loc, 180).latitude
        east = geodist(kilometers=width_km/2).destination(center_loc, 90).longitude
        west = geodist(kilometers=width_km/2).destination(center_loc, 270).longitude
        
        geom = box(west, south, east, north)
        bounds = (west, south, east, north)
        desc = f"{width_km}x{height_km}km"
    else:
        # 近似圆 (Buffer in degrees)
        # 简单近似：1度纬度 ≈ 111km
        approx_deg = radius_km / 111.0
        geom = center_pt.buffer(approx_deg)
        bounds = geom.bounds
        desc = f"R{radius_km}km"
        
    return geom, bounds, desc

def fetch_opentopo_dem(bounds, api_key):
    """请求 OpenTopography API"""
    minx, miny, maxx, maxy = bounds
    
    # 清洗精度，保留5位小数
    minx, miny, maxx, maxy = [round(x, 5) for x in [minx, miny, maxx, maxy]]
    
    # Copernicus GLO-30 (COP30) 是最好的 30m 全球数据
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
                return False, f"API 错误: {r.text[:200]}"
            return True, r.content
        else:
            return False, f"HTTP Error {r.status_code}: {r.reason}"
    except Exception as e:
        return False, str(e)

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🎛️ 参数面板")
    
    # 状态初始化
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 27.9881, 'lon': 86.9250, 'addr': 'Mount Everest'})
    
    # 搜索
    query = st.text_input("📍 地点搜索", "珠穆朗玛峰")
    if st.button("Go"):
        res = get_location(query)
        if res:
            st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
            st.success("已定位")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("未找到")

    st.divider()

    # 形状
    shape_type = st.selectbox("形状", ["矩形 (Rectangle)", "圆形 (Circle)"])
    if shape_type == "矩形 (Rectangle)":
        c1, c2 = st.columns(2)
        w_km = c1.number_input("宽 (km)", 1.0, 500.0, 10.0)
        h_km = c2.number_input("高 (km)", 1.0, 500.0, 10.0)
        r_km = 0
    else:
        r_km = st.number_input("半径 (km)", 1.0, 200.0, 5.0)
        w_km, h_km = 0, 0

    st.divider()
    
    with st.expander("🔑 API Key (建议填写)", expanded=True):
        api_key = st.text_input("OpenTopography Key", type="password", help="免费申请: my.opentopography.org")

# --- 5. 主界面 ---

st.title("Geo Data Master")
st.caption(f"当前中心: {st.session_state['addr']}")

# 计算几何
geom, bounds, desc = generate_geometry(
    st.session_state['lat'], st.session_state['lon'], 
    shape_type, w_km, h_km, r_km
)

# 生成 GeoDataFrame (明确指定 crs)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")

# 地图预览
m = folium.Map(location=[st.session_state['lat'], st.session_state['lon']], zoom_start=11, tiles="OpenStreetMap")
folium.GeoJson(
    gdf,
    style_function=lambda x: {'fillColor': '#007AFF', 'color': '#007AFF', 'weight': 2, 'fillOpacity': 0.2}
).add_to(m)
folium.Marker([st.session_state['lat'], st.session_state['lon']]).add_to(m)

st_folium(m, height=450, width="100%")

st.divider()

# --- 6. 下载区域 ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. 矢量范围 (GeoJSON)")
    st.info("WGS84 坐标系")
    st.download_button(
        label="⬇️ 下载 .geojson",
        data=gdf.to_json(),
        file_name=f"Area_{desc}.geojson",
        mime="application/geo+json",
        use_container_width=True
    )

with col2:
    st.subheader("2. 高程数据 (DEM)")
    st.write("Copernicus GLO-30 (30m)")

    # 缓存管理
    if 'dem_data' not in st.session_state:
        st.session_state['dem_data'] = None
    
    # 获取按钮
    if st.button("🚀 获取 DEM 数据", use_container_width=True):
        if not api_key:
            st.error("请在侧边栏填写 API Key 才能下载数据。")
        else:
            with st.spinner("正在请求卫星数据..."):
                ok, res = fetch_opentopo_dem(bounds, api_key)
                if ok:
                    st.session_state['dem_data'] = res
                    st.success("成功！")
                else:
                    st.error(f"失败: {res}")

    # 保存按钮 (独立显示)
    if st.session_state['dem_data']:
        st.download_button(
            label="💾 保存 .tif 文件",
            data=st.session_state['dem_data'],
            file_name=f"DEM_{desc}.tif",
            mime="image/tiff",
            use_container_width=True,
            type="primary"
        )
