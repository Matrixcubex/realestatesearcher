import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import random
import requests
import polyline
from bs4 import BeautifulSoup
import re
from googlesearch import search
import time
import concurrent.futures
import pandas as pd
import urllib.parse
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

def load_favoritos():
    return []

def save_favoritos():
    pass

# ==========================================
# Configuración y Diseño de la página
# ==========================================
st.set_page_config(page_title="Buscador de Bienes Raíces", page_icon="🏠", layout="wide")

st.markdown("""
<style>
    .main { background-color: #f7f9fa; }
    h1 { color: #1f3c88; font-weight: 800; }
    .stButton>button { width: 100%; border-radius: 8px; background-color: #03a9f4; color: white; font-weight: bold; border: none; }
    .stButton>button:hover { background-color: #0288d1; color: white; }
    .card { background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

def geocode_address(address):
    """Convierte una dirección en texto a coordenadas usando OpenStreetMap (Nominatim)"""
    url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json&limit=1"
    headers = {'User-Agent': 'BuscadorBienesRaices/1.0'}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        pass
    return None, None

def download_url_offline(url, house_id):
    """Obtiene el HTML crudo de la propiedad en memoria o el link de YouTube nativo"""
    if 'youtube.com' in url or 'youtu.be' in url:
        return url, "video"
            
    # Asumir que es HTML regular 
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        # Inyectar una etiqueta <base> para que intente cargar imagenes relativas
        domain = "/".join(url.split("/")[:3])
        html_injected = r.text.replace("<head>", f"<head><base href='{domain}/'>")
        return html_injected, "html"
    except Exception as e:
        return None, None

# ==========================================
# Lógica de Web Scraping Multi-Nivel Real
# ==========================================
def fetch_url_content(url):
    """Obtiene el HTML de una URL con requests."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)',
        'Accept-Language': 'es-MX,es;q=0.9,en;q=0.8'
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return url, r.text
    except:
        pass
    return url, None

def extract_property_cards_from_html(html, base_url):
    """
    Intenta adivinar y extraer enlaces a propiedades (tarjetas) desde un HTML.
    Devuelve las URLs completas a las propiedades individuales.
    """
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    
    # Buscar enlaces que parezcan apuntar a una propiedad
    for a in soup.find_all('a', href=True):
        href = a['href']
        if re.search(r'(inmueble|propiedad|casa|departamento|venta|\d{5,})', href.lower()):
            full_url = urllib.parse.urljoin(base_url, href)
            # Evitar enlaces repetidos y a redes sociales/búsquedas cíclicas
            if full_url not in links and "facebook" not in full_url and "twitter" not in full_url:
                links.append(full_url)
                
    # Retornar máximo 15 tarjetas por sitio para no saturar
    return links[:15]

def extract_data_from_card_url(url, lat_base, lon_base, search_term=""):
    """
    Extrae la información final del inmueble de la tarjeta individual.
    Llamada desde un hilo (Thread) con retrasos para imitar humanos.
    """
    time.sleep(1) # IMPORTANTE: Retraso de 1s para parecer una persona y no banear (CPU Friendly)
    
    headers = {
        'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.{random.randint(1000, 9999)}.124 Safari/537.36'
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200:
            return None
            
        soup = BeautifulSoup(r.text, 'html.parser')
        texto_pagina = soup.get_text().lower()
        search_term = search_term.lower()
        
        # 1. Buscar precio más inteligentemente usando regex y clases de tarjetas
        precio = None
        
        # Intentar extraer de meta tags o schema.org primero (la forma más limpia)
        meta_price = soup.find('meta', itemprop='price')
        if meta_price and meta_price.get('content'):
            precio = float(meta_price['content'])
            
        if not precio:
            # Buscar en textos comunes de los ejemplos enviados
            for price_class in ['card-precio', 'price__actual', 'snippet__content__price', 'value__title', 'p-detalle', 'div-verde']:
                price_tags = soup.find_all(class_=re.compile(price_class, re.I))
                for price_tag in price_tags:
                    p_str = price_tag.get_text()
                    val = re.sub(r'[^\d.]', '', p_str) # Quitar '$', 'MXN', comas
                    if val and len(val) >= 5: # Validar que al menos parezca precio > 10,000
                        try:
                            precio_candidato = float(val)
                            if precio_candidato >= 50000:
                                precio = precio_candidato
                                break
                        except:
                            pass
                if precio: break

        # Si seguimos sin nada, barrido por fuerza bruta en toda la página
        if not precio:
            precios_encontrados = re.findall(r'\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', texto_pagina)
            if precios_encontrados:
                for p_str in precios_encontrados:
                    p_val = float(p_str.replace(',', ''))
                    if p_val > 50000: # Asumimos propiedades > $50k
                        precio = int(p_val)
                        break
                        
        if not precio or precio < 50000: return None # Descartar si no hay precio claro
        
        # 2. Adivinar tipo
        tipo = "Casa"
        if "departamento" in texto_pagina or "apartment" in texto_pagina:
            tipo = "Departamento"
        elif "terreno" in texto_pagina or "lote" in texto_pagina:
            tipo = "Terreno"
            
        # 3. Extraer m2
        m2 = 0
        m2_match = re.search(r'(\d{2,4})\s*(?:m2|mts|metros|m²)', texto_pagina)
        if m2_match:
            try:
                m2 = int(m2_match.group(1))
            except:
                pass
                
        # 4. Extraer recamaras y baños básicos si existen
        recamaras = 0
        rec_match = re.search(r'(\d+)\s*(?:recámara|recamara|habitaci[óo]n|cuarto)', texto_pagina)
        if rec_match:
            try: recamaras = int(rec_match.group(1))
            except: pass
            
        banos = 0
        banos_match = re.search(r'(\d+)\s*(?:baño|bano)', texto_pagina)
        if banos_match:
            try: banos = int(banos_match.group(1))
            except: pass
            
        titulo = soup.title.string.strip() if soup.title else url
        titulo_corto = titulo[:40] + "..." if len(titulo) > 40 else titulo
        dominio = urllib.parse.urlparse(url).netloc
        
        return {
            "id": random.randint(10000, 99999), 
            "tipo": tipo,
            "precio": precio,
            "moneda": "MXN",
            "m2": m2,
            "zona": titulo_corto,
            "estado": "Extraído",
            "pais": "Web Search",
            "lat": lat_base + (random.random() - 0.5) * 0.08, # Variación geográfica
            "lon": lon_base + (random.random() - 0.5) * 0.08,
            "fuente": dominio,
            "url": url,
            "is_real": True,
            # Nuevos campos extendidos para favoritos/comparativa
            "recamaras": recamaras,
            "banos": banos,
            "cocina": "N/D",
            "estudio": "N/D",
            "estacionamientos": 0,
            "niveles": 0,
            "antiguedad": "N/D",
            "uso_suelo": "N/D",
            "cuartos_servicio": "N/D",
            "jaula_tendido": "N/D",
            "estado_inmueble": "N/D",
            "cuarto_lavado": "N/D",
            "medio_bano": "N/D",
            "ubicacion": "N/D",
            "tel_contacto": "N/D",
            "correo": "N/D",
            "horario_atencion": "N/D"
        }
    except:
        return None

def process_site_workflow(base_url, lat, lon, search_term):
    """Flujo de trabajo por sitio base: Descarga -> Busca tarjetas -> Lanza hilos -> Extrae -> Retorna."""
    resultado_casas = []
    
    # 1. Descargar página base
    _, html = fetch_url_content(base_url)
    if not html: return []
    
    # 2. Extraer tarjetas
    card_urls = extract_property_cards_from_html(html, base_url)
    if not card_urls: return []
    
    # 3. Extraer info de cada tarjeta en hilos con contexto Streamlit
    ctx = get_script_run_ctx()
    
    def wrapped_extract(u, lat, lon, sterm):
        if ctx:
            add_script_run_ctx(ctx=ctx)
        return extract_data_from_card_url(u, lat, lon, sterm)
        
    # LIMITADO A 2 WORKERS PARA NO SATURAR LA RAM EN STREAMLIT CLOUD
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(wrapped_extract, u, lat, lon, search_term): u for u in card_urls}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                resultado_casas.append(res)
                
    return resultado_casas

def run_real_scraping_engine(query, custom_sites, lat, lon, max_links=10, progress_chart=None):
    """
    Agente principal. Busca en Google general y específico de sitios, 
    recopila URLs base y despacha de manera concurrente con Threading.
    """
    casas_encontradas = []
    base_urls = []
    
    # 1. Añadir sitios web crudos dados por el usuario
    if custom_sites:
        for site in custom_sites:
            if not site.startswith('http'):
                site = 'https://' + site
            if site not in base_urls:
                base_urls.append(site)

    # 2. Buscar en Google la query general del usuario (Protegido por si Google banea la IP)
    if query:
        try:
            for url in search(query, num_results=max_links):
                if url not in base_urls:
                    base_urls.append(url)
        except Exception as e:
            st.warning(f"⚠️ Google bloqueó la búsqueda automática (muy común en la nube). Usa sitios personalizados abajo. Error: {e}")
    
    if not base_urls:
        return []

    # Variables para gráfico en tiempo real
    total_sites = len(base_urls)
    sites_processed = 0
    chart_data = pd.DataFrame({"Sitios Procesados": [0], "Casas Extraídas": [0]})
    
    if progress_chart:
        progress_chart.line_chart(chart_data)
        
    ctx = get_script_run_ctx()
    
    def wrapped_process(url, lat, lon, query):
        if ctx:
            add_script_run_ctx(ctx=ctx)
        return process_site_workflow(url, lat, lon, query)
        
    # LIMITADO A 3 WORKERS PARA EVITAR CONGELAMIENTO DE MEMORIA
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(wrapped_process, url, lat, lon, query): url for url in base_urls}
        
        for future in concurrent.futures.as_completed(futures):
            sites_processed += 1
            casas = future.result()
            if casas:
                casas_encontradas.extend(casas)
                
            # Actualizar gráfico en vivo
            if progress_chart:
                chart_data = pd.DataFrame({"Sitios Procesados": [sites_processed], "Casas Extraídas": [len(casas_encontradas)]})
                progress_chart.add_rows(chart_data)

    return casas_encontradas

def get_route_osrm(lat1, lon1, lat2, lon2):
    """Obtiene la ruta entre dos puntos usando la API pública gratuita de OSRM"""
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full"
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        if data['code'] == 'Ok':
            route = data['routes'][0]['geometry']
            duration = data['routes'][0]['duration'] # Segundos
            distance = data['routes'][0]['distance'] # Metros
            
            # Decodificar polyline usando la librería polyline
            decoded_points = polyline.decode(route)
            
            return {
                "puntos": decoded_points, 
                "duracion_min": int(duration/60), 
                "distancia_km": round((distance/1000), 2)
            }
    except Exception as e:
        st.error(f"Error obteniendo ruta: {e}")
    return None

# ==========================================
# UI Principal
# ==========================================
st.markdown("<h1>🕵️‍♂️ Hunter de Bienes Raíces Masivo</h1>", unsafe_allow_html=True)

if "favoritos" not in st.session_state:
    st.session_state["favoritos"] = load_favoritos()

if "compare_selection" not in st.session_state:
    st.session_state["compare_selection"] = []

tab_buscar, tab_fav, tab_comp = st.tabs(["🔍 Búsqueda y Mapa", "⭐ Guardados", "📊 Comparativa"])

with tab_buscar:
    # Contenedores principales
    col_sidebar, col_map = st.columns([1, 2])
    
    with col_sidebar:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.subheader("🎯 Criterios de Búsqueda")
        st.markdown("**1. Búsqueda y Origen**")
        
        busqueda_web_global = st.text_input("Ingresa tu búsqueda literal (ej. 'casa 150 m2 una planta coyoacan'):", value="casa coyoacan")
        direccion_input = st.text_input("Ubicación Origen (para trazar ruta):", value="Coyoacán, CDMX")

        # Variables de estado para lat y lon persistentes
        if "origen_lat" not in st.session_state:
            st.session_state["origen_lat"] = 19.4326
        if "origen_lon" not in st.session_state:
            st.session_state["origen_lon"] = -99.1332

        if st.button("📌 Ubicar en Mapa"):
            with st.spinner("Buscando coordenadas..."):
                lat, lon = geocode_address(direccion_input)
                if lat and lon:
                    st.session_state["origen_lat"] = lat
                    st.session_state["origen_lon"] = lon
                    st.session_state["casas_encontradas"] = [] # Limpiar resultados anteriores
                    st.session_state.pop("ruta_activa", None)
                    st.success(f"Encontrado: Lat {lat:.4f}, Lon {lon:.4f}")
                else:
                    st.error("No encontramos esa dirección. Intenta con un lugar más general.")
                
        origen_lat = st.session_state["origen_lat"]
        origen_lon = st.session_state["origen_lon"]
        
        st.markdown("**2. Filtros del Inmueble (Aplicados a Resultados)**")
        
        tipo_filtro = st.selectbox("Tipo de Inmueble", ["Todos", "Casa", "Departamento", "Terreno"])
        
        col1, col2 = st.columns(2)
        with col1:
            precio_min = st.number_input("Precio Mínimo", value=500000, step=100000)
            m2_min = st.number_input("M2 Mínimo", value=50, step=10)
        with col2:
            precio_max = st.number_input("Precio Máximo", value=10000000, step=1000000)
            m2_max = st.number_input("M2 Máximo", value=1000, step=50)
            
        termino_busqueda = st.text_input("Limpiar Extracciones por palabra clave (opcional):", value="")
        
        st.markdown("**3. Sitios Base Alternativos (Opcional)**")

        if "custom_sites" not in st.session_state:
            st.session_state["custom_sites"] = []
            
        nuevo_sitio = st.text_input("Añade URLs de páginas (ej. www.century21.com/propiedad1)")
        if st.button("➕ Agregar Sitio"):
            if nuevo_sitio and nuevo_sitio not in st.session_state["custom_sites"]:
                st.session_state["custom_sites"].append(nuevo_sitio)
                st.rerun()
                
        if st.session_state["custom_sites"]:
            st.write("Sitios personalizados a buscar:")
            for idx, site in enumerate(st.session_state["custom_sites"]):
                cols_site = st.columns([4, 1])
                cols_site[0].text(f"- {site}")
                if cols_site[1].button("❌", key=f"del_{idx}"):
                    st.session_state["custom_sites"].remove(site)
                    st.rerun()
        
        if st.button("Buscar en Fuentes 🚀"):
            if not busqueda_web_global:
                st.error("Por favor, ingresa tu búsqueda literal en el Paso 1.")
            else:
                st.write("---")
                st.subheader("📈 Progreso de Extracción Concurrente")
                progreso_container = st.empty()
                
                with st.spinner("Despachando Buscadores web, Multiprocesamiento y Hilos de Tarjetas..."):
                    raw_data = run_real_scraping_engine(
                        query=busqueda_web_global, 
                        custom_sites=st.session_state["custom_sites"],
                        lat=origen_lat, 
                        lon=origen_lon, 
                        max_links=10,
                        progress_chart=progreso_container
                    )
                    
                    filtered = []
                    for c in raw_data:
                        match_tipo = (tipo_filtro == "Todos" or c["tipo"] == tipo_filtro)
                        match_precio = (precio_min <= c["precio"] <= precio_max)
                        match_m2 = (m2_min <= c.get("m2", 0) <= m2_max if c.get("m2") else True)
                        match_termino = (not termino_busqueda or termino_busqueda.lower() in c["zona"].lower() or termino_busqueda.lower() in c.get("url", "").lower())
                        
                        if match_tipo and match_precio and match_m2 and match_termino:
                            filtered.append(c)
                    
                    st.session_state["casas_encontradas"] = filtered
                    st.session_state.pop("map_selection_id", None)
                    
                    progreso_container.empty()
                    st.success(f"¡Extracción paralela completada! Filtramos {len(filtered)} resultados de la web real.")
        st.markdown("</div>", unsafe_allow_html=True)

        if "casas_encontradas" in st.session_state and len(st.session_state["casas_encontradas"]) > 0:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.subheader("📍 Trazar Ruta a Inmueble")
            
            casas_dict = {str(c["id"]): c for c in st.session_state["casas_encontradas"]}
            opciones = [f"ID {c['id']} - {c['tipo']} en {c['zona']} - ${c['precio']:,}" for c in st.session_state["casas_encontradas"]]
            
            current_selection_index = 0
            if "map_selection_id" in st.session_state and str(st.session_state["map_selection_id"]) in casas_dict:
                target_id = str(st.session_state["map_selection_id"])
                for idx, opc in enumerate(st.session_state["casas_encontradas"]):
                    if str(opc["id"]) == target_id:
                        current_selection_index = idx
                        break

            seleccion_str = st.selectbox("Selecciona una Casa (o haz clic en el mapa)", opciones, index=current_selection_index)
            seleccion_id = seleccion_str.split(" - ")[0].replace("ID ", "")
            casa_seleccionada = casas_dict[seleccion_id]
            
            st.write(f"**Fuente:** {casa_seleccionada['fuente']}")
            st.markdown(f"**URL:** [{casa_seleccionada['url']}]({casa_seleccionada['url']})")
            st.write(f"**Precio:** ${casa_seleccionada['precio']:,} {casa_seleccionada['moneda']}")
            st.write(f"**Ubicación:** Lat {casa_seleccionada['lat']:.4f}, Lon {casa_seleccionada['lon']:.4f}")
            
            is_saved = any(f["id"] == casa_seleccionada["id"] for f in st.session_state["favoritos"])
            if not is_saved:
                if st.button("⭐ Guardar en Favoritos"):
                    with st.spinner("Extrayendo página para vista previa..."):
                        html_content_memory, arch_tipo = download_url_offline(casa_seleccionada["url"], casa_seleccionada["id"])
                        casa_copy = dict(casa_seleccionada)
                        casa_copy["local_file"] = html_content_memory
                        casa_copy["local_type"] = arch_tipo
                        
                        st.session_state["favoritos"].append(casa_copy)
                        save_favoritos()
                        
                        st.success("¡Guardado en Favoritos!")
                        time.sleep(1)
                        st.rerun()
            else:
                st.info("⭐ Ya está en Favoritos")
            
            if st.button("Trazar Ruta y Calcular Tiempos 🗺️"):
                with st.spinner("Calculando ruta con OSRM..."):
                    ruta = get_route_osrm(origen_lat, origen_lon, casa_seleccionada['lat'], casa_seleccionada['lon'])
                    if ruta:
                        st.session_state["ruta_activa"] = ruta
                        st.session_state["casa_dest"] = casa_seleccionada
                        st.success(f"⏱️ Tiempo estimado (Ida): **{ruta['duracion_min']} minutos** | Distancia: **{ruta['distancia_km']} km**")
                    else:
                        st.error("No se pudo calcular la ruta.")
            st.markdown("</div>", unsafe_allow_html=True)

    with col_map:
        st.subheader("🌍 Mapa de Resultados")
        
        zoom_start = 12
        m = folium.Map(location=[origen_lat, origen_lon], zoom_start=zoom_start, tiles="CartoDB positron")
        
        folium.Marker(
            [origen_lat, origen_lon],
            popup="Punto Central / Origen",
            tooltip="Origen",
            icon=folium.Icon(color="red", icon="home", prefix='fa')
        ).add_to(m)
        
        if "casas_encontradas" in st.session_state:
            for c in st.session_state["casas_encontradas"]:
                badge = "✅ REAL" if c.get("is_real") else "🛠️ SIMULADO"
                popup_html = f"<b>{c['tipo']} en {c['zona']}</b><br>{badge} | {c['estado']}, {c['pais']}<br>Precio: ${c['precio']:,}<br>Fuente: {c['fuente']}"
                
                if c.get("is_real"):
                    icon_color = "orange"
                else:
                    icon_color = "blue"
                    
                if "ruta_activa" in st.session_state and "casa_dest" in st.session_state:
                    if c["id"] == st.session_state["casa_dest"]["id"]:
                        icon_color = "green"
                        
                folium.Marker(
                    [c['lat'], c['lon']],
                    popup=folium.Popup(popup_html, max_width=250),
                    tooltip=f"ID {c['id']}: ${c['precio']:,} - Click para seleccionar",
                    icon=folium.Icon(color=icon_color, icon="info-sign")
                ).add_to(m)
                
        if "ruta_activa" in st.session_state:
            folium.PolyLine(
                st.session_state["ruta_activa"]["puntos"],
                color="#03a9f4",
                weight=5,
                opacity=0.8
            ).add_to(m)
            
            dest = st.session_state["casa_dest"]
            m.location = [dest['lat'], dest['lon']]
            m.zoom_start = 14

        mapa_output = st_folium(m, width=800, height=600, returned_objects=["last_object_clicked"])
        
        if mapa_output.get("last_object_clicked"):
            click_lat = math.floor(mapa_output["last_object_clicked"]["lat"] * 10000)/10000 
            click_lon = math.floor(mapa_output["last_object_clicked"]["lng"] * 10000)/10000
            
            for c in st.session_state.get("casas_encontradas", []):
                if abs(c["lat"] - click_lat) < 0.001 and abs(c["lon"] - click_lon) < 0.001:
                    if st.session_state.get("map_selection_id") != c["id"]:
                        st.session_state["map_selection_id"] = c["id"]
                        st.rerun()

        st.markdown("---")
        st.markdown("💡 *El scraper web real está habilitado para bypass básico de Search cajas de Google Index.*")

with tab_fav:
    st.subheader("⭐ Propiedades Guardadas (Modo Desconectado)")
    
    with st.expander("Añadir manualmente por URL (YouTube o Portal Web)"):
        url_manual = st.text_input("Ingresa la URL del video o inmueble particular:")
        if st.button("📥 Importar y Guardar"):
            if url_manual:
                with st.spinner("Descargando y extrayendo contenido manual..."):
                    manual_id = random.randint(100000, 999999)
                    base_data = extract_data_from_card_url(url_manual, origen_lat, origen_lon, "")
                    if not base_data:
                        base_data = {
                            "id": manual_id, "tipo": "Desconocido", "precio": 0, "moneda": "MXN", "m2": 0, 
                            "zona": "Importado", "lat": origen_lat, "lon": origen_lon, "url": url_manual, 
                            "fuente": urllib.parse.urlparse(url_manual).netloc, "estado": "Manual", "pais": "Manual", "is_real": True,
                            "recamaras": 0, "banos": 0, "cocina": "N/D", "estudio": "N/D", "estacionamientos": 0,
                            "niveles": 0, "antiguedad": "N/D", "uso_suelo": "N/D", "cuartos_servicio": "N/D",
                            "jaula_tendido": "N/D", "estado_inmueble": "N/D", "cuarto_lavado": "N/D",
                            "medio_bano": "N/D", "ubicacion": "N/D", "tel_contacto": "N/D", "correo": "N/D", "horario_atencion": "N/D"
                        }
                    else:
                        base_data["id"] = manual_id
                        
                    html_content_memory, arch_tipo = download_url_offline(url_manual, manual_id)
                    base_data["local_file"] = html_content_memory
                    base_data["local_type"] = arch_tipo
                    
                    st.session_state["favoritos"].append(base_data)
                    save_favoritos()
                    
                    st.success("Guardado Exitosamente!")
                    time.sleep(1)
                    st.rerun()
                    
    if not st.session_state["favoritos"]:
        st.info("Aún no tienes propiedades guardadas. Búscalas en la pestaña principal y añádelas aquí.")
    else:
        col_list, col_view = st.columns([1, 2])
        
        with col_list:
            if "fav_selected_idx" not in st.session_state:
                st.session_state["fav_selected_idx"] = 0
                
            if st.session_state["fav_selected_idx"] >= len(st.session_state["favoritos"]):
                st.session_state["fav_selected_idx"] = 0
                
            idx_selected = st.session_state["fav_selected_idx"]
            
            for i, f in enumerate(st.session_state["favoritos"]):
                bcolor = "#e1f5fe" if i == idx_selected else "#ffffff"
                st.markdown(f"<div style='background-color: {bcolor}; padding: 10px; border-radius: 5px; border: 1px solid #ccc; margin-bottom: 5px;'>", unsafe_allow_html=True)
                if st.button(f"📌 {f['tipo']} - ${f['precio']:,}", key=f"fav_btn_{i}"):
                    st.session_state["fav_selected_idx"] = i
                    st.rerun()
                st.caption(f"{f['zona']} | {f.get('m2', 0)} m2")
                st.markdown("</div>", unsafe_allow_html=True)
                
        with col_view:
            idx = st.session_state["fav_selected_idx"]
            fav_curr = st.session_state["favoritos"][idx]
            
            st.markdown(f"### {fav_curr['tipo']} en {fav_curr['zona']}")
            
            with st.expander("✏️ Editar Detalles Locales"):
                with st.form(key=f"edit_form_{idx}"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        new_precio = st.number_input("Precio ($)", value=int(fav_curr['precio']) if fav_curr['precio'] else 0)
                        new_recamaras = st.number_input("Recámaras", value=int(fav_curr.get('recamaras', 0)))
                        new_estacionamientos = st.number_input("Estacionamientos", value=int(fav_curr.get('estacionamientos', 0)))
                        new_cocina = st.text_input("Cocina", value=fav_curr.get('cocina', ''))
                        new_cuartos_servicio = st.text_input("Cuartos de servicio", value=fav_curr.get('cuartos_servicio', ''))
                        new_medio_bano = st.text_input("1/2 Baño", value=fav_curr.get('medio_bano', ''))
                    with c2:
                        new_m2 = st.number_input("Metros Cuadrados (m2)", value=int(fav_curr.get('m2', 0)))
                        new_banos = st.number_input("Baños", value=int(fav_curr.get('banos', 0)))
                        new_niveles = st.number_input("Niveles", value=int(fav_curr.get('niveles', 0)))
                        new_estudio = st.text_input("Estudio", value=fav_curr.get('estudio', ''))
                        new_jaula_tendido = st.text_input("Jaula de tendido", value=fav_curr.get('jaula_tendido', ''))
                        new_estado_inm = st.text_input("Estado del inmueble", value=fav_curr.get('estado_inmueble', ''))
                    with c3:
                        new_antiguedad = st.text_input("Antigüedad", value=fav_curr.get('antiguedad', ''))
                        new_uso_suelo = st.text_input("Uso del suelo", value=fav_curr.get('uso_suelo', ''))
                        new_cuarto_lavado = st.text_input("Cuarto de lavado", value=fav_curr.get('cuarto_lavado', ''))
                        new_tel = st.text_input("Teléfono contacto", value=fav_curr.get('tel_contacto', ''))
                        new_correo = st.text_input("Correo", value=fav_curr.get('correo', ''))
                        new_horario = st.text_input("Horario atención", value=fav_curr.get('horario_atencion', ''))
                        
                    st.markdown("---")
                    new_zona = st.text_input("Título Corto", value=fav_curr['zona'])
                    new_ubicacion = st.text_area("Ubicación Completa", value=fav_curr.get('ubicacion', ''))
                    
                    if st.form_submit_button("Guardar Cambios"):
                        st.session_state["favoritos"][idx].update({
                            'precio': new_precio, 'm2': new_m2, 'zona': new_zona, 'recamaras': new_recamaras,
                            'banos': new_banos, 'cocina': new_cocina, 'estudio': new_estudio,
                            'estacionamientos': new_estacionamientos, 'niveles': new_niveles, 
                            'antiguedad': new_antiguedad, 'uso_suelo': new_uso_suelo,
                            'cuartos_servicio': new_cuartos_servicio, 'jaula_tendido': new_jaula_tendido,
                            'estado_inmueble': new_estado_inm, 'cuarto_lavado': new_cuarto_lavado,
                            'medio_bano': new_medio_bano, 'ubicacion': new_ubicacion, 'tel_contacto': new_tel,
                            'correo': new_correo, 'horario_atencion': new_horario
                        })
                        save_favoritos()
                        st.success("¡Datos actualizados localmente!")
                        time.sleep(1)
                        st.rerun()

            st.write(f"**Precio:** ${fav_curr['precio']:,} MXN | **m2:** {fav_curr.get('m2', 0)} | **Recámaras:** {fav_curr.get('recamaras', 0)} | **Baños:** {fav_curr.get('banos', 0)}")
            st.write(f"**Ubicación:** {fav_curr.get('ubicacion', 'N/D')}")
            st.write(f"**Contacto:** {fav_curr.get('tel_contacto', 'N/D')} | **Correo:** {fav_curr.get('correo', 'N/D')}")
            st.write(f"**Fuente:** [{fav_curr['fuente']}]({fav_curr['url']})")
            
            if st.button("🗑️ Eliminar de Favoritos", type="primary"):
                del st.session_state["favoritos"][idx]
                save_favoritos()
                st.rerun()
                
            st.markdown("#### Ubicación y Mapa Individual")
            m_fav = folium.Map(location=[fav_curr['lat'], fav_curr['lon']], zoom_start=15, tiles="CartoDB positron")
            folium.Marker(
                [fav_curr['lat'], fav_curr['lon']],
                popup=fav_curr['zona'], tooltip=f"ID {fav_curr['id']}",
                icon=folium.Icon(color="green", icon="home", prefix='fa')
            ).add_to(m_fav)
            st_folium(m_fav, width=800, height=300, key=f"map_fav_{idx}")
                
            st.markdown("#### Vista de la Página Analizada")
            local_path = fav_curr.get("local_file")
            file_type = fav_curr.get("local_type")
            
            if local_path:
                if file_type == "video":
                    st.video(local_path)
                else:
                    import streamlit.components.v1 as components
                    components.html(local_path, height=800, scrolling=True)
            else:
                st.warning("No se pudo extraer la vista previa de la web original.")

with tab_comp:
    st.subheader("📊 Comparativa de Propiedades")
    
    if not st.session_state["favoritos"]:
        st.info("No hay propiedades guardadas para comparar.")
    else:
        col_comp_list, col_comp_view = st.columns([1, 3])
        
        with col_comp_list:
            st.markdown("#### Seleccionar para comparar")
            for f in st.session_state["favoritos"]:
                checked = f["id"] in st.session_state["compare_selection"]
                if st.checkbox(f"{f['tipo']} - ${f['precio']:,} ({f['zona'][:15]}...)", value=checked, key=f"comp_check_{f['id']}"):
                    if f["id"] not in st.session_state["compare_selection"]:
                        st.session_state["compare_selection"].append(f["id"])
                else:
                    if f["id"] in st.session_state["compare_selection"]:
                        st.session_state["compare_selection"].remove(f["id"])
                        
        with col_comp_view:
            selected_props = [f for f in st.session_state["favoritos"] if f["id"] in st.session_state["compare_selection"]]
            
            if not selected_props:
                st.info("Selecciona al menos una propiedad a la izquierda para ver su comparativa.")
            else:
                comp_cols = st.columns(len(selected_props))
                
                for i, p in enumerate(selected_props):
                    with comp_cols[i]:
                        st.markdown(f"<div style='border: 1px solid #ddd; padding: 15px; border-radius: 8px; margin-bottom: 10px; background-color: #fcfcfc;'>", unsafe_allow_html=True)
                        st.markdown(f"### {p['tipo']}")
                        st.markdown(f"**💰 ${p.get('precio', 0):,} MXN**")
                        st.markdown(f"**📍 Ubicación:** {p.get('zona', '')}")
                        st.markdown("---")
                        
                        st.markdown(f"**📐 M2:** {p.get('m2', 0)}  <br>"
                                    f"**🛏️ Recámaras:** {p.get('recamaras', 0)}  <br>"
                                    f"**🛀 Baños:** {p.get('banos', 0)}  <br>"
                                    f"**🚗 Estac.:** {p.get('estacionamientos', 0)}  <br>"
                                    f"**🍳 Cocina:** {p.get('cocina', '')}  <br>"
                                    f"**📚 Estudio:** {p.get('estudio', '')}  <br>"
                                    f"**🏢 Niveles:** {p.get('niveles', 0)}  <br>"
                                    f"**🕰️ Antigüedad:** {p.get('antiguedad', '')}  <br>"
                                    f"**🏗️ Uso suelo:** {p.get('uso_suelo', '')}  <br>"
                                    f"**🧹 C. Servicio:** {p.get('cuartos_servicio', '')}  <br>"
                                    f"**🧺 Jaula:** {p.get('jaula_tendido', '')}  <br>"
                                    f"**🛠️ Estado:** {p.get('estado_inmueble', '')}  <br>"
                                    f"**👕 C. Lavado:** {p.get('cuarto_lavado', '')}  <br>"
                                    f"**🚽 1/2 Baño:** {p.get('medio_bano', '')}  ", unsafe_allow_html=True)
                        st.markdown("---")
                        
                        st.markdown(f"**📞 Tel:** {p.get('tel_contacto', 'N/D')}  <br>"
                                    f"**📧 Correo:** {p.get('correo', 'N/D')}  <br>"
                                    f"**⏰ Horario:** {p.get('horario_atencion', 'N/D')}  <br>"
                                    f"🔗 **[Enlace Original]({p['url']})**", unsafe_allow_html=True)
                        
                        st.markdown("</div>", unsafe_allow_html=True)
                        
                        m_ind = folium.Map(location=[p['lat'], p['lon']], zoom_start=15, tiles="CartoDB positron")
                        folium.Marker(
                            [p['lat'], p['lon']],
                            popup=p['zona'],
                            icon=folium.Icon(color="purple", icon="star")
                        ).add_to(m_ind)
                        st_folium(m_ind, width=300, height=250, key=f"map_comp_ind_{p['id']}_{len(selected_props)}")