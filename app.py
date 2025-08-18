import requests
import pandas as pd
import streamlit as st
import json
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import quote_plus, urljoin
import random
from fake_useragent import UserAgent
import io # Necessário para o download do Excel

# ==================== FUNÇÕES DE ENRIQUECIMENTO ====================

def buscar_dados_cnpj_biz(nome_empresa, timeout=15):
    """
    Faz scraping no site cnpj.biz para tentar achar o CNPJ, sócios e email
    """
    try:
        ua = UserAgent()
        headers = {
            'User-Agent': ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        query = re.sub(r'[^\w\s]', ' ', nome_empresa).strip()
        query = re.sub(r'\s+', '+', query)
        
        url = f"https://cnpj.biz/search/{query}"
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        empresa_links = []
        for link in soup.find_all("a", href=True):
            if "/cnpj/" in link["href"]:
                empresa_links.append(urljoin("https://cnpj.biz", link["href"]))
        
        if not empresa_links:
            return {"CNPJ": None, "Sócios": [], "Email": None, "Situação": None}
        
        empresa_url = empresa_links[0]
        time.sleep(random.uniform(1, 2))
        
        detalhe_response = requests.get(empresa_url, headers=headers, timeout=timeout)
        detalhe_response.raise_for_status()
        
        soup_det = BeautifulSoup(detalhe_response.text, "html.parser")
        page_text = soup_det.get_text()

        cnpj = None
        cnpj_match = re.search(r'(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})', page_text)
        if cnpj_match:
            cnpj = cnpj_match.group(1)
        
        socios = []
        socio_patterns = [r'Sócio[:\s]*([^\n\r]+)', r'Administrador[:\s]*([^\n\r]+)']
        for pattern in socio_patterns:
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            socios.extend([match.strip() for match in matches if match.strip() and len(match.strip()) > 3])
        socios = list(set(socios))
        
        email = None
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', page_text)
        if email_match:
            email = email_match.group()
        
        situacao = None
        situacao_match = re.search(r'Situação[:\s]*([^\n\r]+)', page_text, re.IGNORECASE)
        if situacao_match:
            situacao = situacao_match.group(1).strip()
        
        return {"CNPJ": cnpj, "Sócios": socios, "Email": email, "Situação": situacao}
        
    except Exception:
        return {"CNPJ": None, "Sócios": [], "Email": None, "Situação": None}

def buscar_dados_receita_federal(cnpj):
    """
    Busca dados em APIs públicas da Receita Federal
    """
    if not cnpj: return {}
    
    cnpj_limpo = re.sub(r'\D', '', cnpj)
    if len(cnpj_limpo) != 14: return {}
    
    apis = [
        f"https://www.receitaws.com.br/v1/cnpj/{cnpj_limpo}",
        f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}",
        f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    ]
    
    for api_url in apis:
        try:
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'status' in data and data.get('status') == 'OK': # ReceitaWS
                    return {'Nome_Receita': data.get('nome'), 'Fantasia': data.get('fantasia'), 'CNPJ_Receita': data.get('cnpj'), 'Situacao_Receita': data.get('situacao')}
                elif 'razao_social' in data: # CNPJ.ws ou BrasilAPI
                    return {'Nome_Receita': data.get('razao_social'), 'Fantasia': data.get('nome_fantasia'), 'CNPJ_Receita': data.get('cnpj'), 'Situacao_Receita': data.get('descricao_situacao_cadastral')}
            time.sleep(1)
        except Exception:
            continue
    return {}

def buscar_redes_sociais(website):
    """
    Tenta encontrar redes sociais no website da empresa
    """
    redes = {'Facebook': None, 'Instagram': None, 'LinkedIn': None}
    if not website or not website.startswith('http'): return redes
    try:
        ua = UserAgent()
        response = requests.get(website, headers={'User-Agent': ua.random}, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if not redes['Facebook'] and 'facebook.com' in href: redes['Facebook'] = a['href']
            elif not redes['Instagram'] and 'instagram.com' in href: redes['Instagram'] = a['href']
            elif not redes['LinkedIn'] and 'linkedin.com' in href: redes['LinkedIn'] = a['href']
    except Exception:
        pass
    return redes

def enriquecer_empresas(empresas, incluir_cnpj=True, incluir_redes_sociais=False):
    """
    Enriquece a lista de empresas com dados adicionais
    """
    dados_finais = []
    total = len(empresas)
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, emp in enumerate(empresas):
        nome_empresa = emp.get('Nome', '')
        status_text.text(f"Enriquecendo: {nome_empresa} ({i+1}/{total})")
        dados_empresa = {**emp}
        
        if incluir_cnpj and nome_empresa:
            dados_cnpj_biz = buscar_dados_cnpj_biz(nome_empresa)
            dados_empresa.update({
                "CNPJ_Scraped": dados_cnpj_biz.get("CNPJ"), "Email_Scraped": dados_cnpj_biz.get("Email"),
                "Sócios": ", ".join(dados_cnpj_biz.get("Sócios", [])), "Situação_Scraped": dados_cnpj_biz.get("Situação")
            })
            if dados_cnpj_biz.get("CNPJ"):
                dados_receita = buscar_dados_receita_federal(dados_cnpj_biz["CNPJ"])
                dados_empresa.update(dados_receita)
        
        if incluir_redes_sociais:
            dados_empresa.update(buscar_redes_sociais(emp.get('Website')))
        
        dados_finais.append(dados_empresa)
        progress_bar.progress((i + 1) / total)
        time.sleep(random.uniform(1, 2))
    
    progress_bar.empty(); status_text.empty()
    return dados_finais

# ==================== MÉTODO 1: Google Places API (VERSÃO NOVA CORRIGIDA) ====================
def google_places_search(query, location, api_key):
    """
    Busca empresas usando a nova Google Places API (v1).
    """
    base_url = "https://places.googleapis.com/v1/places:searchText"
    data = {"textQuery": f"{query} em {location}", "languageCode": "pt-BR", "maxResultCount": 20}
    headers = {
        "Content-Type": "application/json", "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.websiteUri,places.nationalPhoneNumber"
    }
    results = []
    try:
        response = requests.post(base_url, json=data, headers=headers, timeout=30)
        if response.status_code != 200:
            st.error(f"Erro na API do Google: {response.status_code} - {response.text}")
            return []
        for place in response.json().get('places', []):
            results.append({
                'Nome': place.get('displayName', {}).get('text'), 'Endereço': place.get('formattedAddress'),
                'Telefone': place.get('nationalPhoneNumber'), 'Website': place.get('websiteUri'),
                'Rating': place.get('rating'), 'Avaliações': place.get('userRatingCount'),
            })
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com Google API: {e}")
    return results

# ==================== MÉTODO 2: API SerpAPI ====================
def serpapi_google_maps(query, location, api_key, num_results=50):
    """
    Usa SerpAPI para fazer scraping do Google Maps
    """
    url = "https://serpapi.com/search"
    params = {"engine": "google_maps", "q": f"{query} {location}", "hl": "pt", "gl": "br", "api_key": api_key, "num": min(num_results, 100)}
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if 'error' in data:
            st.error(f"Erro SerpAPI: {data['error']}"); return []
        return [{'Nome': p.get('title'), 'Endereço': p.get('address'), 'Telefone': p.get('phone'), 'Website': p.get('website'),
                 'Rating': p.get('rating'), 'Avaliações': p.get('reviews')} for p in data.get("local_results", [])]
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com SerpAPI: {e}"); return []

# ==================== MÉTODO 3: Dados Públicos CNPJ ====================
def search_cnpj_data(cnpj_list):
    """
    Busca dados em APIs públicas de CNPJ a partir de uma lista
    """
    results = []
    progress_bar = st.progress(0)
    for i, cnpj in enumerate(cnpj_list):
        dados = buscar_dados_receita_federal(cnpj)
        if dados:
            results.append({'Nome': dados.get('Nome_Receita'), 'CNPJ': dados.get('CNPJ_Receita'), 'Situação': dados.get('Situacao_Receita')})
        progress_bar.progress((i + 1) / len(cnpj_list))
    return results

# ==================== MÉTODO 4: Scraping Simples (Demonstrativo) ====================
def simple_web_search(query, location):
    st.info("O método 'Busca Web Simples' é apenas demonstrativo e não extrairá dados.")
    return []

# ==================== INTERFACE STREAMLIT ====================
def main():
    st.set_page_config(page_title="Extração de Empresas", page_icon="🏢", layout="wide")
    st.title("🏢 Extração e Enriquecimento de Dados de Empresas")
    
    st.sidebar.header("⚙️ Configurações de Extração")
    method = st.sidebar.selectbox("Método:", ["Google Places API", "SerpAPI Google Maps", "Dados Públicos CNPJ", "Busca Web Simples"])
    
    st.sidebar.header("🚀 Opções de Enriquecimento")
    st.sidebar.caption("Aplicável a 'Google Places' e 'SerpAPI'")
    incluir_cnpj = st.sidebar.checkbox("Buscar CNPJ, Sócios e E-mail", value=True)
    incluir_redes_sociais = st.sidebar.checkbox("Buscar Redes Sociais", value=False)
    
    col1, col2 = st.columns(2)
    with col1: nicho = st.text_input("🎯 Nicho da empresa:", placeholder="ex: dentista, restaurante")
    with col2: local = st.text_input("📍 Localização:", placeholder="ex: Belo Horizonte, MG")
    
    api_key, cnpj_list = None, []
    if method == "Google Places API":
        api_key = st.text_input("🔑 Google Places API Key:", type="password")
    elif method == "SerpAPI Google Maps":
        api_key = st.text_input("🔑 SerpAPI Key:", type="password")
    elif method == "Dados Públicos CNPJ":
        cnpj_text = st.text_area("📋 Lista de CNPJs (um por linha):", height=150)
        if cnpj_text: cnpj_list = [cnpj.strip() for cnpj in cnpj_text.split('\n') if cnpj.strip()]

    if st.button("🚀 Extrair Dados", type="primary"):
        results = []
        is_enrichable = method in ["Google Places API", "SerpAPI Google Maps"]
        with st.spinner("Iniciando extração..."):
            if method == "Google Places API":
                if api_key and nicho and local: results = google_places_search(nicho, local, api_key)
                else: st.error("Preencha Nicho, Localização e API Key.")
            elif method == "SerpAPI Google Maps":
                if api_key and nicho and local: results = serpapi_google_maps(nicho, local, api_key)
                else: st.error("Preencha Nicho, Localização e API Key.")
            elif method == "Dados Públicos CNPJ":
                if cnpj_list: results = search_cnpj_data(cnpj_list)
                else: st.error("Insira pelo menos um CNPJ.")
            elif method == "Busca Web Simples":
                results = simple_web_search(nicho, local)

        if results and is_enrichable and (incluir_cnpj or incluir_redes_sociais):
            st.info(f"Extração inicial concluída com {len(results)} resultados. Iniciando enriquecimento...")
            results = enriquecer_empresas(results, incluir_cnpj, incluir_redes_sociais)
        
        if results:
            df = pd.DataFrame(results).drop_duplicates(subset=['Nome'], keep='first').fillna('N/A')
            st.success(f"✅ **{len(df)} empresas encontradas!**")
            st.dataframe(df)

            # --- Downloads ---
            @st.cache_data
            def to_excel(df_to_convert):
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_to_convert.to_excel(writer, index=False, sheet_name='Empresas')
                return output.getvalue()
            
            col1, col2 = st.columns(2)
            col1.download_button("📥 Download CSV", df.to_csv(index=False, encoding='utf-8-sig'), f"empresas.csv", "text/csv")
            col2.download_button("📊 Download Excel", to_excel(df), f"empresas.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("⚠️ Nenhum resultado encontrado.")

if __name__ == "__main__":
    main()
