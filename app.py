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
    .stButton>button { border-radius: 8px; font-weight: 600; }
    .debug-box { background: #eee; padding: 10px; border-radius: 5px; font-family: monospace; font-size: 12px; word-break: break-all;}
</style>
""", unsafe_allow_html=True)

# --- 3. 逻辑函数 ---

def get_location(query):
    geolocator = Nominatim(user_agent="geo_debugger_v6")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except Exception as e:
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
        geom = center_pt.buffer(radius_km / 111.0)
        desc = f"R{radius_km}km"
        
    return geom, desc

def get_opentopo_url(bounds, api_key):
    """只生成 URL，不下载，方便调试"""
    minx, miny, maxx, maxy = [round(x, 5) for x in bounds]
    
    # 强制修正：防止范围过小导致 API 报错
    if (maxx - minx) < 0.001: maxx += 0.001; minx -= 0.001
    if (maxy - miny) < 0.001: maxy += 0.001; miny -= 0.001

    base_url = "https://portal.opentopography.org/API/globalDem"
    params = f"demType=SRTMGL1&south={miny}&north={maxy}&west={minx}&east={maxx}&outputFormat=GTiff&API_Key={api_key}"
    
    return f"{base_url}?{params}"

# --- 4. 侧边栏 ---

with st.sidebar:
    st.title("🎛️ Geo Master Debug")
    
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 34.4871, 'lon': 110.0847, 'addr': 'Hua Shan'}) 
    
    q = st.text_input("📍 地点", "华山")
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
        
    st.divider()
    api_key = st.text_input("🔑 API Key (必填)", type="password", help="没有 Key 肯定会失败")
    if not api_key:
        st.error("⚠️ 必须填写 API Key")

# --- 5. 主界面 ---

st.title("Geo Data Master")
st.caption(f"当前中心: {st.session_state['addr']}")

geom, desc = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
bounds = geom.bounds

# 地图
map_key = f"map_{st.session_state['lat']}_{st.session_state['lon']}_{shape}_{w}"
m = folium.Map([st.session_state['lat'], st.session_state['lon']], zoom_start=12)
folium.GeoJson(gdf).add_to(m)
folium.Marker([st.session_state['lat'], st.session_state['lon']]).add_to(m)
st_folium(m, height=400, width="100%", key=map_key)

st.divider()

c1, c2 = st.columns(2)
with c1:
    st.subheader("1. 矢量 (GeoJSON)")
    st.download_button("⬇️ 下载 GeoJSON", gdf.to_json(), f"{desc}.geojson", "application/geo+json", use_container_width=True)

with c2:
    st.subheader("2. 高程 (DEM)")
    
    # 生成直接下载链接
    direct_url = get_opentopo_url(bounds, api_key)
    
    # 状态：Python 后端下载
    if 'dem_file' not in st.session_state: st.session_state['dem_file'] = None

    if st.button("🚀 获取 DEM (SRTM 30m)", use_container_width=True):
        if not api_key:
            st.error("请先填写 API Key")
        else:
            with st.spinner("正在请求数据..."):
                try:
                    # 使用 generated URL 请求
                    r = requests.get(direct_url, stream=True, timeout=60)
                    if r.status_code == 200:
                        if 'text/html' in r.headers.get('Content-Type', ''):
                             st.error("API 返回了错误页面，请查看下方调试链接")
                        else:
                            st.session_state['dem_file'] = r.content
                            st.success("成功！")
                            st.rerun()
                    elif r.status_code == 401:
                        st.error("API Key 错误 (401)")
                    elif r.status_code == 404:
                        st.error("404: 范围无效或数据源不支持该区域")
                    else:
                        st.error(f"HTTP {r.status_code}")
                except Exception as e:
                    st.error(f"连接超时: {e}")

    # 保存按钮
    if st.session_state['dem_file']:
        st.download_button("💾 保存文件", st.session_state['dem_file'], f"DEM_{desc}.tif", "image/tiff", type="primary", use_container_width=True)

    # === 调试区域 (Plan B) ===
    st.markdown("---")
    st.caption("🛠️ **调试与备用方案**")
    st.write("如果上方按钮失败，请直接点击下方链接下载。如果浏览器打开显示 'Unauthorized'，说明 Key 错；显示 'Coverage' 错误，说明该地无数据。")
    st.link_button("👉 点击直接在浏览器下载 (Plan B)", direct_url)
    with st.expander("查看生成的 API 链接"):
        st.code(direct_url)
