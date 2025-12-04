import streamlit as st
import time
import requests
import os

# --- 1. 环境与依赖初始化 ---
# 强制使用 Pyogrio 引擎 (自带 GDAL 二进制，解决 Linux 依赖冲突)
os.environ["USE_PYGEOS"] = "0" 

try:
    import pyogrio
    import geopandas as gpd
    # 尝试设置默认引擎
    gpd.options.io_engine = "pyogrio"
    
    from shapely.geometry import box, Point
    from geopy.geocoders import Nominatim
    from geopy.distance import distance as geodist
    import folium
    from streamlit_folium import st_folium
except ImportError as e:
    st.error(f"""
    ❌ 环境加载失败: {e}
    请确保 requirements.txt 包含: streamlit, geopandas, shapely>=2.0, pyogrio, folium, streamlit-folium, geopy, requests
    并删除 packages.txt。
    """)
    st.stop()

# --- 2. 页面配置 ---
st.set_page_config(page_title="Geo Data Master", page_icon="⛰️", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #f5f5f7; }
    div[data-testid="stSidebar"] { background-color: rgba(255,255,255,0.95); }
    .stButton>button { border-radius: 8px; border: 1px solid #d1d1d6; font-weight:600; }
    .stButton>button:hover { border-color: #007AFF; color: #007AFF; }
</style>
""", unsafe_allow_html=True)

# --- 3. 核心逻辑 ---

def get_location(query):
    """搜索地点"""
    # 使用自定义 User-Agent 避免被 OpenStreetMap 403 拒绝
    geolocator = Nominatim(user_agent="geo_master_fix_v8")
    try:
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except Exception as e:
        print(f"Geo error: {e}")
    return None

def generate_geometry(lat, lon, shape, width_km, height_km, radius_km):
    """生成几何图形"""
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
        # 缓冲圆
        geom = center_pt.buffer(radius_km / 111.0)
        desc = f"R{radius_km}km"
        
    return geom, desc

def fetch_dem_data(bounds, dataset, api_key):
    """
    下载 DEM 数据的核心函数 (已修正 API 端点)
    """
    minx, miny, maxx, maxy = [round(x, 5) for x in bounds]
    
    # 修正点：使用 globalDem 接口，参数名为 demType
    url = "https://portal.opentopography.org/API/globalDem"
    
    params = {
        'demType': dataset,  # SRTMGL1 或 COP30
        'south': miny,
        'north': maxy,
        'west': minx,
        'east': maxx,
        'outputFormat': 'GTiff',
        'API_Key': api_key
    }
    
    try:
        response = requests.get(url, params=params, stream=True, timeout=90)
        
        # 状态码判断
        if response.status_code == 200:
            # 检查是否返回了纯文本错误 (API 有时返回 200 但内容是 Error)
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' in content_type or 'application/json' in content_type:
                 # 尝试读取前200个字符看是不是报错
                try:
                    error_text = response.text[:300]
                    if "Invalid public API key" in error_text:
                        return False, "API Key 无效或未授权"
                    return False, f"API 返回错误信息: {error_text}"
                except:
                    pass
            return True, response.content
            
        elif response.status_code == 401:
            return False, "401 未授权: 必须填写正确的 API Key"
        elif response.status_code == 400:
            return False, "400 请求错误: 可能是范围太大(超过1亿个点)或参数不对"
        elif response.status_code == 404:
            return False, "404 未找到: 该区域可能没有数据覆盖"
        elif response.status_code == 500:
            return False, "500 服务器错误: OpenTopography 服务器暂时繁忙"
        else:
            return False, f"HTTP {response.status_code}"
            
    except Exception as e:
        return False, str(e)

# --- 4. 侧边栏 ---

with st.sidebar:
    st.header("🎛️ 设置面板")
    
    # Session State
    if 'lat' not in st.session_state:
        st.session_state.update({'lat': 27.9881, 'lon': 86.9250, 'addr': 'Mount Everest'})
    
    # 1. 搜索
    q = st.text_input("📍 地点搜索", "珠穆朗玛峰")
    if st.button("🔍 定位"):
        res = get_location(q)
        if res:
            st.session_state['lat'], st.session_state['lon'], st.session_state['addr'] = res
            st.success("已定位")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("未找到，请尝试英文名称")

    st.divider()

    # 2. 形状参数
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

    # 3. DEM 选项
    st.subheader("⛰️ DEM 数据源")
    dem_source = st.selectbox(
        "选择数据集", 
        ["COP30 (Copernicus 30m)", "SRTMGL1 (SRTM 30m)"], 
        index=0,
        help="COP30 质量更好，但 SRTM 有时下载更容易"
    )
    dataset_code = "COP30" if "COP30" in dem_source else "SRTMGL1"
    
    api_key = st.text_input("🔑 API Key (必填)", type="password", help="去 my.opentopography.org 申请")
    if not api_key:
        st.warning("⚠️ 必须填写 API Key 才能下载")

# --- 5. 主界面 ---

st.title("Geo Data Master")
st.caption(f"📍 当前中心: {st.session_state['addr']}")

# 计算
geom, desc = generate_geometry(st.session_state['lat'], st.session_state['lon'], shape, w, h, r)
gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs="EPSG:4326")
bounds = geom.bounds # (minx, miny, maxx, maxy)

# 地图 Key 强制刷新
map_key = f"m_{st.session_state['lat']}_{st.session_state['lon']}_{shape}_{w}_{h}"

m = folium.Map([st.session_state['lat'], st.session_state['lon']], zoom_start=12, tiles="OpenStreetMap")
folium.GeoJson(gdf, style_function=lambda x: {'color':'#007AFF', 'fillOpacity':0.15}).add_to(m)
folium.Marker([st.session_state['lat'], st.session_state['lon']], tooltip="Center").add_to(m)

st_folium(m, height=450, width="100%", key=map_key)

st.divider()

# --- 6. 下载区 ---

c1, c2 = st.columns(2)

with c1:
    st.subheader("1. 范围文件")
    st.download_button(
        "⬇️ 下载 GeoJSON",
        gdf.to_json(),
        f"{q}_{desc}.geojson",
        "application/geo+json",
        use_container_width=True
    )

with c2:
    st.subheader("2. 高程数据")
    
    # 状态缓存
    if 'dem_blob' not in st.session_state: st.session_state['dem_blob'] = None
    
    btn_text = f"🚀 获取 {dataset_code} 数据"
    if st.button(btn_text, use_container_width=True):
        if not api_key:
            st.error("请先在左侧填写 API Key！")
        else:
            with st.spinner(f"正在向 OpenTopography 请求 {dataset_code} ..."):
                success, data = fetch_dem_data(bounds, dataset_code, api_key)
                
                if success:
                    st.session_state['dem_blob'] = data
                    st.success("下载成功！请点击下方按钮保存。")
                    st.rerun() # 刷新以显示下载按钮
                else:
                    st.error(f"下载失败: {data}")

    # 只有当数据存在时才显示保存按钮
    if st.session_state['dem_blob']:
        st.download_button(
            label="💾 保存 .TIF 文件",
            data=st.session_state['dem_blob'],
            file_name=f"{q}_{desc}_{dataset_code}.tif",
            mime="image/tiff",
            type="primary",
            use_container_width=True
        )
