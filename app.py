# app_v4_polished.py
import requests
import pandas as pd
import streamlit as st
import json
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urljoin
import random
from fake_useragent import UserAgent
import io

# ==================== ESTILO CSS CUSTOMIZADO (Refinado) ====================
def load_custom_css():
    """Injeta CSS customizado para modernizar a aparência do app."""
    st.markdown("""
        <style>
            /* Cor de fundo principal */
            .main { background-color: #0E1117; }
            
            /* Estilo da sidebar */
            [data-testid="stSidebar"] {
                background-color: #161A21;
                border-right: 1px solid #2D3039;
            }
            
            /* Títulos */
            h1, h2, h3 { color: #FAFAFA; }

            /* Estilo para abas (tabs) */
            [data-testid="stTabs"] button {
                color: #A1A1AA;
                border-radius: 8px;
            }
            [data-testid="stTabs"] button[aria-selected="true"] {
                background-color: #27272A;
                color: #FFFFFF;
            }
            
            /* Oculta o menu e footer do Streamlit */
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

# ==================== FUNÇÕES CORE (Sem alterações) ====================
# (Todas as suas funções de busca e enriquecimento permanecem aqui, sem mudanças)
def buscar_emails_site(website, timeout=10):
    if not website or not isinstance(website, str) or not website.startswith("http"): return []
    emails_encontrados = set()
    try:
        ua = UserAgent()
        headers = {"User-Agent": ua.random}
        response = requests.get(website, headers=headers, timeout=timeout)
        response.raise_for_status()
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        found_emails = re.findall(email_pattern, response.text)
        for email in found_emails:
            if not email.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')): emails_encontrados.add(email.lower())
        soup = BeautifulSoup(response.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                email = a["href"].replace("mailto:", "").strip().lower()
                if email: emails_encontrados.add(email)
    except (requests.RequestException, ConnectionError, TimeoutError): return []
    return list(emails_encontrados)

def buscar_dados_cnpj_biz(nome_empresa, timeout=15):
    try:
        ua = UserAgent()
        headers = {'User-Agent': ua.random}
        query = re.sub(r'[^\w\s]', ' ', nome_empresa).strip()
        query = re.sub(r'\s+', '+', query)
        url = f"https://cnpj.biz/search/{query}"
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        empresa_links = [urljoin("https://cnpj.biz", link["href"]) for link in soup.find_all("a", href=True) if "/cnpj/" in link["href"]]
        if not empresa_links: return {"CNPJ": None, "Sócios": [], "Email_CNPJ": None}
        detalhe_response = requests.get(empresa_links[0], headers=headers, timeout=timeout)
        detalhe_response.raise_for_status()
        page_text = BeautifulSoup(detalhe_response.text, "html.parser").get_text()
        cnpj = next(iter(re.findall(r'(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})', page_text)), None)
        socios = list(set(m.strip() for p in [r'Sócio[:\s]*([^\n\r]+)', r'Administrador[:\s]*([^\n\r]+)'] for m in re.findall(p, page_text, re.IGNORECASE) if m.strip() and len(m.strip()) > 3))
        email = next(iter(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', page_text)), None)
        return {"CNPJ": cnpj, "Sócios": socios, "Email_CNPJ": email}
    except Exception: return {"CNPJ": None, "Sócios": [], "Email_CNPJ": None}

def buscar_dados_receita_federal(cnpj):
    if not cnpj: return {}
    cnpj_limpo = re.sub(r'\D', '', cnpj)
    if len(cnpj_limpo) != 14: return {}
    apis = [f"https://www.receitaws.com.br/v1/cnpj/{cnpj_limpo}", f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}", f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"]
    for api_url in apis:
        try:
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'status' in data and data.get('status') == 'OK': return {'Nome_Receita': data.get('nome'), 'Fantasia': data.get('fantasia'), 'CNPJ_Receita': data.get('cnpj'), 'Situacao_Receita': data.get('situacao')}
                elif 'razao_social' in data: return {'Nome_Receita': data.get('razao_social'), 'Fantasia': data.get('nome_fantasia'), 'CNPJ_Receita': data.get('cnpj'), 'Situacao_Receita': data.get('descricao_situacao_cadastral')}
            time.sleep(1)
        except Exception: continue
    return {}

def buscar_redes_sociais(website):
    redes = {'Facebook': None, 'Instagram': None, 'LinkedIn': None}
    if not website or not isinstance(website, str) or not website.startswith('http'): return redes
    try:
        ua = UserAgent()
        response = requests.get(website, headers={'User-Agent': ua.random}, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if not redes['Facebook'] and 'facebook.com' in href: redes['Facebook'] = a['href']
            elif not redes['Instagram'] and 'instagram.com' in href: redes['Instagram'] = a['href']
            elif not redes['LinkedIn'] and 'linkedin.com' in href: redes['LinkedIn'] = a['href']
    except Exception: pass
    return redes

def enriquecer_empresas(empresas, incluir_cnpj, incluir_redes_sociais, incluir_emails_site):
    dados_finais = []
    total = len(empresas)
    progress_bar = st.progress(0, text="Enriquecendo dados...")
    for i, emp in enumerate(empresas):
        nome_empresa = emp.get('Nome', '')
        website = emp.get('Website')
        dados_empresa = {**emp}
        if incluir_emails_site and website:
            emails_site = buscar_emails_site(website)
            dados_empresa["Emails_do_Site"] = ", ".join(emails_site) if emails_site else "N/A"
        if incluir_cnpj and nome_empresa:
            dados_cnpj_biz = buscar_dados_cnpj_biz(nome_empresa)
            dados_empresa.update({"CNPJ_Scraped": dados_cnpj_biz.get("CNPJ"), "Email_CNPJ": dados_cnpj_biz.get("Email_CNPJ"), "Sócios": ", ".join(dados_cnpj_biz.get("Sócios", [])),})
            if dados_cnpj_biz.get("CNPJ"):
                dados_receita = buscar_dados_receita_federal(dados_cnpj_biz["CNPJ"])
                dados_empresa.update(dados_receita)
        if incluir_redes_sociais and website: dados_empresa.update(buscar_redes_sociais(website))
        dados_finais.append(dados_empresa)
        progress_bar.progress((i + 1) / total, text=f"Enriquecendo: {nome_empresa} ({i+1}/{total})")
        time.sleep(random.uniform(1, 2))
    progress_bar.empty()
    return dados_finais

def google_places_search(query, location, api_key):
    base_url = "https://places.googleapis.com/v1/places:searchText"
    data = {"textQuery": f"{query} em {location}", "languageCode": "pt-BR", "maxResultCount": 20}
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.websiteUri,places.nationalPhoneNumber"}
    results = []
    try:
        response = requests.post(base_url, json=data, headers=headers, timeout=30)
        if response.status_code != 200:
            st.error(f"Erro na API do Google: {response.status_code} - {response.text}")
            return []
        for place in response.json().get('places', []):
            results.append({'Nome': place.get('displayName', {}).get('text'), 'Endereço': place.get('formattedAddress'), 'Telefone': place.get('nationalPhoneNumber'), 'Website': place.get('websiteUri'), 'Rating': place.get('rating'), 'Avaliações': place.get('userRatingCount')})
    except requests.exceptions.RequestException as e: st.error(f"Erro de conexão com Google API: {e}")
    return results

def serpapi_google_maps(query, location, api_key, num_results=50):
    url = "https://serpapi.com/search"
    params = {"engine": "google_maps", "q": f"{query} {location}", "hl": "pt", "gl": "br", "api_key": api_key, "num": min(num_results, 100)}
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if 'error' in data: st.error(f"Erro SerpAPI: {data['error']}"); return []
        return [{'Nome': p.get('title'), 'Endereço': p.get('address'), 'Telefone': p.get('phone'), 'Website': p.get('website'), 'Rating': p.get('rating'), 'Avaliações': p.get('reviews')} for p in data.get("local_results", [])]
    except requests.exceptions.RequestException as e: st.error(f"Erro de conexão com SerpAPI: {e}"); return []

def search_cnpj_data(cnpj_list):
    results = []
    progress_bar = st.progress(0)
    for i, cnpj in enumerate(cnpj_list):
        dados = buscar_dados_receita_federal(cnpj)
        if dados: results.append({'Nome': dados.get('Nome_Receita'), 'CNPJ': dados.get('CNPJ_Receita'), 'Situação': dados.get('Situacao_Receita')})
        progress_bar.progress((i + 1) / len(cnpj_list))
    return results

def simple_web_search(query, location):
    st.info("O método 'Busca Web Simples' é apenas demonstrativo e não extrairá dados.")
    return []

# ==================== INTERFACE STREAMLIT V4 (Com Abas) ====================
def main():
    st.set_page_config(page_title="Prospector Pro", page_icon="✨", layout="wide")
    load_custom_css()

    with st.sidebar:
        st.markdown("## ✨ Prospector Pro")
        st.markdown("---")
        st.markdown("### 🚀 Opções de Enriquecimento")
        st.caption("Aplicável a buscas por Nicho/Local")
        incluir_emails_site = st.checkbox("Buscar E-mails no site", value=True)
        incluir_cnpj = st.checkbox("Buscar CNPJ e Sócios", value=True)
        incluir_redes_sociais = st.checkbox("Buscar Redes Sociais", value=False)
        st.markdown("---")

    st.title("🏢 Painel de Prospecção")
    st.markdown("Selecione o método de extração e preencha os campos para iniciar.")

    # --- NOVO: USO DE ABAS PARA ORGANIZAR OS MÉTODOS ---
    tab1, tab2, tab3 = st.tabs(["🔎 Por Nicho e Local", "📋 Por Lista de CNPJs", "🌐 Busca Web Simples"])

    results = []
    
    with tab1:
        st.subheader("Extrair usando Google Places ou SerpAPI")
        method_nicho = st.selectbox("Selecione a API:", ["Google Places API", "SerpAPI Google Maps"])
        
        with st.container(border=True):
            nicho = st.text_input("🎯 Nicho da empresa:", placeholder="ex: dentista, restaurante")
            local = st.text_input("📍 Localização:", placeholder="ex: Belo Horizonte, MG")
            api_key = st.text_input(f"🔑 Chave da API ({method_nicho}):", type="password")
        
        if st.button("🚀 Extrair por Nicho", type="primary", use_container_width=True):
            is_enrichable = True
            with st.spinner("Iniciando extração por nicho..."):
                if method_nicho == "Google Places API":
                    if api_key and nicho and local: results = google_places_search(nicho, local, api_key)
                    else: st.error("Preencha Nicho, Localização e Chave da API.")
                elif method_nicho == "SerpAPI Google Maps":
                    if api_key and nicho and local: results = serpapi_google_maps(nicho, local, api_key)
                    else: st.error("Preencha Nicho, Localização e Chave da API.")
    
    with tab2:
        st.subheader("Enriquecer uma lista de CNPJs")
        with st.container(border=True):
            cnpj_text = st.text_area("📋 Cole os CNPJs aqui (um por linha):", height=200)
            cnpj_list = [cnpj.strip() for cnpj in cnpj_text.split('\n') if cnpj.strip()] if cnpj_text else []
        
        if st.button("🚀 Buscar por CNPJ", type="primary", use_container_width=True):
            is_enrichable = False # Enriquecimento já é o próprio processo
            if cnpj_list:
                with st.spinner("Buscando dados dos CNPJs..."):
                    results = search_cnpj_data(cnpj_list)
            else:
                st.error("Insira pelo menos um CNPJ na lista.")

    with tab3:
        st.subheader("Busca Web (Demonstração)")
        st.info("Este método é apenas uma demonstração e não extrairá dados reais.")
        is_enrichable = False
        # A função simple_web_search já exibe um st.info e retorna lista vazia.

    # --- PROCESSAMENTO E EXIBIÇÃO DE RESULTADOS (Lógica Unificada) ---
    if results:
        if is_enrichable and (incluir_cnpj or incluir_redes_sociais or incluir_emails_site):
            st.info(f"Extração inicial concluída com {len(results)} resultados. Iniciando enriquecimento...")
            results = enriquecer_empresas(results, incluir_cnpj, incluir_redes_sociais, incluir_emails_site)
        
        df = pd.DataFrame(results).drop_duplicates(subset=['Nome'], keep='first').fillna('N/A')
        st.success(f"✅ **{len(df)} empresas encontradas!**")
        st.dataframe(df)

        @st.cache_data
        def to_excel(df_to_convert):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_to_convert.to_excel(writer, index=False, sheet_name='Empresas')
            return output.getvalue()
        
        dl_col1, dl_col2 = st.columns(2)
        dl_col1.download_button("📥 Download CSV", df.to_csv(index=False, encoding='utf-8-sig'), f"empresas.csv", "text/csv", use_container_width=True)
        dl_col2.download_button("📊 Download Excel", to_excel(df), f"empresas.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    
    # Exibe aviso se um botão foi clicado mas nenhum resultado foi encontrado
    elif "button" in st.session_state and st.session_state.button:
        st.warning("⚠️ Nenhum resultado encontrado para os critérios fornecidos.")


if __name__ == "__main__":
    main()
