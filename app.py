import streamlit as st
import os

# --- 1. 基础环境设置 ---
# 强制使用纯 Python 模式，避免 Linux 依赖冲突
os.environ["USE_PYGEOS"] = "0" 

try:
    import geopandas as gpd
    # 尝试设置引擎，如果失败也没关系，GeoPandas 会自动回退
    try:
        import pyogrio
        gpd.options.io_engine = "pyogrio"
    except:
        pass

    from shapely.geometry import box, Point
    from geopy.geocoders import Nominatim
    from geopy.distance import distance as geodist
    import folium
    from streamlit_folium import st_folium

except ImportError as e:
    st.error(f"环境缺少库: {e}")
    st.stop()

# --- 2. 页面配置 ---
st.set_page_config(page_title="Geo Data Master", page_icon="🌍", layout="wide")
st.markdown("""
<style>
    .stApp { background-color: #f5f5f7; }
    .stButton>button { width: 100%; border-radius: 8px; }
    .info-box { background: #e0f2fe; padding: 15px; border-radius: 8px; color: #0284c7; border: 1px solid #bae6fd; }
</style>
""", unsafe_allow_html=True)

# --- 3. 逻辑函数 ---

def get_location(query):
    """搜索地点"""
    geolocator = Nominatim(user_agent="geo_web_link_v1")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except:
        return None
    return None

def generate_geometry(lat, lon, shape, width_km, height_km, radius_km):
    """生成几何范围"""
    center_loc = (lat, lon)
    center_pt = Point(lon, lat)
    
    if shape == "矩形 (Rectangle)":
        north = geodist(kilometers=height_km/2).destination(center_loc, 0).latitude
        south = geodist(kilometers=height_km/2).destination(center_loc, 180).latitude
        east = geodist(kilometers=width_km/2).destination(center_loc, 90).longitude
        west = geodist(kilometers=width_km/2).destination(center_loc, 270).longitude
        
        # 强制坐标顺序，防止 Min > Max 导致错误
        minx, maxx = sorted([west, east])
        miny, maxy = sorted([south, north])
        
        geom = box(minx, miny, maxx, maxy)
        desc = f"{width_km}x{height_km}km"
    else:
        # 近似圆
        geom = center_pt.buffer(radius_km / 111.0)
        desc = f"R{radius_km}km"
        
    return geom, desc

def get_portal_url(bounds):
    """生成 OpenTopography 官方网页的直达链接"""
    minx, miny, maxx, maxy = bounds
    
    # 强制保留5位小数
    minx = f"{minx:.5f}"
    miny = f"{miny:.5f}"
    maxx = f"{maxx:.5f}"
    maxy = f"{maxy:.5f}"
    
    # 这是 OpenTopography 的 WEB 界面接口 (不是 API)
    # opentopoID=OTSRTM.082015.4326.1 代表 SRTM GL1 (30m)
    base = "https://portal.opentopography.org/raster"
    params = f"opentopoID=OTSRTM.082015.4326.1&minx={minx}&miny={miny}&maxx={maxx}&maxy={maxy}"
    
    return f"{base}?{params}"

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🎛️ 參數设置")
    
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 34.4871, 'lon': 110.0847, 'addr': 'Hua Shan'})
        
    q = st.text_input("📍 地点搜索", "华山")
    if st.button("搜索"):
        res = get_location(q)
        if res:
            st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
            st.success("已定位")
            st.rerun()
            
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

# --- 5. 主界面 ---

st.title("Geo Data Master (Web Direct)")
st.caption(f"当前中心: {st.session_state['addr']}")

# 计算
geom, desc = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
bounds = geom.bounds # (minx, miny, maxx, maxy)

# 地图
m = folium.Map([st.session_state['lat'], st.session_state['lon']], zoom_start=12)
folium.GeoJson(gdf, style_function=lambda x: {'color':'#007AFF', 'fillOpacity':0.2}).add_to(m)
st_folium(m, height=400, width="100%")

st.divider()

# 下载区
c1, c2 = st.columns(2)

with c1:
    st.subheader("1. 矢量数据")
    st.download_button("⬇️ 下载 GeoJSON", gdf.to_json(), f"Area_{desc}.geojson", "application/geo+json", use_container_width=True)

with c2:
    st.subheader("2. 高程数据 (DEM)")
    
    # 生成链接
    portal_url = get_portal_url(bounds)
    
    st.markdown("""
    <div class="info-box">
    <b>🚀 最稳健的下载方式：</b><br>
    由于 API 限制，我们直接跳转到 OpenTopography 官网下载。<br>
    坐标范围已自动填入，无需 API Key。
    </div>
    """, unsafe_allow_html=True)
    
    st.write("") # Spacer
    
    # 使用 link_button 直接跳转
    st.link_button("👉 点击
