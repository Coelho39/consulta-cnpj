
import os
import time
import json
import requests
import pandas as pd
import streamlit as st

# -------------------- Helpers --------------------

HEADERS = {
    "User-Agent": os.getenv("USER_AGENT", "Streamlit-OSM-Overpass-Client/1.0 (+contact: example@example.com)")
}

def geocode_city(city_query: str):
    \"\"\"Geocode a city/region name using Nominatim (OpenStreetMap) to get a bounding box.\"\"\"
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": city_query,
        "format": "json",
        "addressdetails": 1,
        "limit": 1,
        "countrycodes": "br"  # prioritize Brazil; remove if you want global
    }
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    item = data[0]
    # bbox from Nominatim is [south, north, west, east] as strings
    bbox = item.get("boundingbox", None)
    if not bbox or len(bbox) != 4:
        return None
    south, north, west, east = map(float, bbox)
    return {
        "display_name": item.get("display_name"),
        "lat": float(item.get("lat")),
        "lon": float(item.get("lon")),
        "bbox": (south, north, west, east)
    }

def build_overpass_query(niche_words, bbox, limit=50, tags_filter=None):
    \"\"\"
    Build an Overpass QL query.
    - niche_words: list of lowercase words to search in the 'name' tag (regex OR).
    - bbox: (south, north, west, east)
    - tags_filter: dict with keys like 'amenity', 'shop', 'office', 'craft', 'healthcare' mapping to lists of values.
    \"\"\"
    south, north, west, east = bbox
    name_regex = "|".join([requests.utils.requote_uri(w) for w in niche_words if w])
    # Base selectors: match by name
    selectors = [
        f'node["name"~"{name_regex}", i]({south},{west},{north},{east});',
        f'way["name"~"{name_regex}", i]({south},{west},{north},{east});',
        f'relation["name"~"{name_regex}", i]({south},{west},{north},{east});'
    ]
    # Optional: add category/tag filters
    if tags_filter:
        for k, vals in tags_filter.items():
            for v in vals:
                selectors += [
                    f'node["{k}"="{v}"]({south},{west},{north},{east});',
                    f'way["{k}"="{v}"]({south},{west},{north},{east});',
                    f'relation["{k}"="{v}"]({south},{west},{north},{east});',
                ]

    query = f'''
    [out:json][timeout:60];
    (
      {"".join(selectors)}
    );
    out center {limit};
    '''
    return query

def query_overpass(query: str):
    url = "https://overpass-api.de/api/interpreter"
    r = requests.post(url, data=query.encode("utf-8"), headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()

def extract_pois(overpass_json):
    \"\"\"Extract POIs from Overpass result into a structured list.\"\"\"
    elements = overpass_json.get("elements", [])
    rows = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        name = tags.get("name")
        if not name:
            continue

        # Address fields
        street = tags.get("addr:street")
        housenumber = tags.get("addr:housenumber")
        city = tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:suburb")
        state = tags.get("addr:state")
        postcode = tags.get("addr:postcode")

        # Contacts
        phone = tags.get("contact:phone") or tags.get("phone")
        website = tags.get("contact:website") or tags.get("website")
        email = tags.get("contact:email") or tags.get("email")

        # Compose address
        addr_parts = []
        if street: addr_parts.append(street)
        if housenumber: addr_parts.append(housenumber)
        if city: addr_parts.append(city)
        if state: addr_parts.append(state)
        if postcode: addr_parts.append(postcode)
        address = ", ".join(addr_parts) if addr_parts else None

        # Coordinates
        lat = el.get("lat") or (el.get("center", {}) or {}).get("lat")
        lon = el.get("lon") or (el.get("center", {}) or {}).get("lon")

        rows.append({
            "Nome": name,
            "Endereço": address,
            "Telefone": phone,
            "Email": email,
            "Site": website,
            "Latitude": lat,
            "Longitude": lon
        })
    return rows

def map_niche_to_tags(niche: str):
    \"\"\"Map common Portuguese niche terms to OSM categories (best effort).\"\"\"
    n = niche.lower()
    mapping = {
        "clínica odontológica": {"amenity": ["dentist"], "healthcare": ["dentist"]},
        "dentista": {"amenity": ["dentist"], "healthcare": ["dentist"]},
        "restaurante": {"amenity": ["restaurant"]},
        "pizzaria": {"amenity": ["restaurant"], "cuisine": ["pizza"]},
        "lanchonete": {"amenity": ["fast_food"]},
        "academia": {"leisure": ["fitness_centre"], "sport": ["fitness"]},
        "hotel": {"tourism": ["hotel"]},
        "pousada": {"tourism": ["guest_house"]},
        "mercado": {"shop": ["supermarket"]},
        "supermercado": {"shop": ["supermarket"]},
        "materiais de construção": {"shop": ["doityourself", "hardware"]},
        "loja de pisos": {"shop": ["doityourself", "hardware", "flooring"]},
        "pet shop": {"shop": ["pet"]},
        "clínica": {"amenity": ["clinic"], "healthcare": ["clinic"]},
        "farmácia": {"amenity": ["pharmacy"], "shop": ["chemist"]},
        "escritório de contabilidade": {"office": ["accountant"]},
        "advogado": {"office": ["lawyer"]},
        "autoescola": {"amenity": ["driving_school"]},
        "oficina mecânica": {"craft": ["car_repair"], "shop": ["car_repair"]},
    }
    for key, val in mapping.items():
        if key in n:
            return val
    return None

def dedupe_rows(rows):
    \"\"\"Deduplicate by (Nome, Endereço) best-effort.\"\"\"
    seen = set()
    out = []
    for r in rows:
        k = ((r.get("Nome") or "").strip().lower(), (r.get("Endereço") or "").strip().lower())
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out

# -------------------- Streamlit UI --------------------

st.set_page_config(page_title="Gerador de Lista (OSM/Overpass)", page_icon="📊", layout="wide")

st.title("📊 Gerador de Lista de Empresas – Fonte: OpenStreetMap (gratuito)")
st.write("Busque empresas por **nicho + região** usando a base pública do OpenStreetMap (Overpass API).")

nicho = st.text_input("Digite o nicho (ex: clínica odontológica, restaurante, loja de pisos):")
local = st.text_input("Digite a cidade/região (ex: Belo Horizonte, MG):")
limite = st.slider("Quantas empresas retornar (máx.)?", 5, 200, 50)

enriquecer_cnpj = st.checkbox("Tentar enriquecer depois com CNPJ/sócios (scraping separado)", value=False)
if enriquecer_cnpj:
    st.info("Nesta versão de teste, o enriquecimento por CNPJ não está habilitado por padrão para manter o uso leve do Overpass. Podemos adicionar em seguida.")

if st.button("Gerar Lista (OSM)"):
    if not (nicho and local):
        st.warning("⚠️ Digite um nicho e uma cidade/região para continuar.")
        st.stop()

    with st.spinner("Geocodificando a região..."):
        geo = geocode_city(local)
        if not geo:
            st.error("Não foi possível localizar essa região no Nominatim/OSM.")
            st.stop()

    st.caption(f"📍 Área encontrada: {geo['display_name']}")
    bbox = geo["bbox"]

    # Prepare Overpass query
    niche_words = [w.strip() for w in niche.lower().replace("/", " ").split() if w.strip()]
    tags_filter = map_niche_to_tags(nicho)

    query = build_overpass_query(niche_words=niche_words, bbox=bbox, limit=int(limite), tags_filter=tags_filter)

    with st.expander("Ver consulta Overpass (debug)"):
        st.code(query, language="sql")

    with st.spinner("Consultando pontos de interesse no OpenStreetMap..."):
        try:
            data = query_overpass(query)
        except requests.HTTPError as e:
            st.error(f"Erro na API Overpass: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Falha ao consultar Overpass: {e}")
            st.stop()

    rows = extract_pois(data)
    rows = dedupe_rows(rows)

    if not rows:
        st.warning("Nenhum resultado encontrado para esse nicho nessa região. Tente variar as palavras-chave (ex.: 'dentista' em vez de 'clínica odontológica').")
        st.stop()

    df = pd.DataFrame(rows)

    st.success(f"✅ Encontradas {len(df)} empresas (fonte OSM).")
    st.dataframe(df, use_container_width=True)

    # Download buttons
    excel_file = "empresas_osm.xlsx"
    csv_file = "empresas_osm.csv"
    df.to_excel(excel_file, index=False)
    df.to_csv(csv_file, index=False, encoding="utf-8-sig")

    with open(excel_file, "rb") as f:
        st.download_button(
            label="📥 Baixar Excel",
            data=f,
            file_name=excel_file,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    with open(csv_file, "rb") as f:
        st.download_button(
            label="📥 Baixar CSV",
            data=f,
            file_name=csv_file,
            mime="text/csv"
        )

st.markdown("---")
st.caption("Dica: O OpenStreetMap é uma base colaborativa. Nem todas as empresas terão telefone/email/website, mas é um ótimo ponto de partida gratuito. Para resultados mais completos e estáveis, recomendo Google Places API ou serviços como SerpAPI.")

