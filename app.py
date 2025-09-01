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
import io

# ==================== FUNÇÕES DE ENRIQUECIMENTO ====================

# [NOVO] Função aprimorada para buscar e-mails, vinda do appv2.py
def buscar_emails_site(website, timeout=10):
    """
    Busca e-mails diretamente no site oficial da empresa, de forma mais assertiva.
    """
    if not website or not isinstance(website, str) or not website.startswith("http"):
        return []
    
    emails_encontrados = set()
    try:
        ua = UserAgent()
        headers = {"User-Agent": ua.random}
        response = requests.get(website, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        # Procura padrões de e-mail no corpo HTML
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        found_emails = re.findall(email_pattern, response.text)
        for email in found_emails:
            # Filtra e-mails comuns de imagens ou exemplos
            if not email.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
                emails_encontrados.add(email.lower())

        # Procura em links "mailto:"
        soup = BeautifulSoup(response.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                email = a["href"].replace("mailto:", "").strip().lower()
                if email:
                    emails_encontrados.add(email)

    except (requests.RequestException, ConnectionError, TimeoutError):
        # Ignora erros de conexão ou de leitura do site
        return []
        
    return list(emails_encontrados)


def buscar_dados_cnpj_biz(nome_empresa, timeout=15):
    """
    Faz scraping no site cnpj.biz para tentar achar o CNPJ, sócios e email. (Versão robusta do app.py)
    """
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
        if not empresa_links:
            return {"CNPJ": None, "Sócios": [], "Email_CNPJ": None}

        detalhe_response = requests.get(empresa_links[0], headers=headers, timeout=timeout)
        detalhe_response.raise_for_status()
        page_text = BeautifulSoup(detalhe_response.text, "html.parser").get_text()

        cnpj = next(iter(re.findall(r'(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})', page_text)), None)
        socios = list(set(m.strip() for p in [r'Sócio[:\s]*([^\n\r]+)', r'Administrador[:\s]*([^\n\r]+)'] for m in re.findall(p, page_text, re.IGNORECASE) if m.strip() and len(m.strip()) > 3))
        email = next(iter(re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', page_text)), None)
        
        return {"CNPJ": cnpj, "Sócios": socios, "Email_CNPJ": email}
    except Exception:
        return {"CNPJ": None, "Sócios": [], "Email_CNPJ": None}


def buscar_dados_receita_federal(cnpj):
    """
    Busca dados em APIs públicas da Receita Federal. (Versão completa do app.py)
    """
    if not cnpj: return {}
    cnpj_limpo = re.sub(r'\D', '', cnpj)
    if len(cnpj_limpo) != 14: return {}
    
    apis = [f"https://www.receitaws.com.br/v1/cnpj/{cnpj_limpo}", f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}", f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"]
    for api_url in apis:
        try:
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'status' in data and data.get('status') == 'OK':
                    return {'Nome_Receita': data.get('nome'), 'Fantasia': data.get('fantasia'), 'CNPJ_Receita': data.get('cnpj'), 'Situacao_Receita': data.get('situacao')}
                elif 'razao_social' in data:
                    return {'Nome_Receita': data.get('razao_social'), 'Fantasia': data.get('nome_fantasia'), 'CNPJ_Receita': data.get('cnpj'), 'Situacao_Receita': data.get('descricao_situacao_cadastral')}
            time.sleep(1)
        except Exception:
            continue
    return {}


def buscar_redes_sociais(website):
    """
    Tenta encontrar redes sociais no website da empresa. (Versão do app.py)
    """
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
    except Exception:
        pass
    return redes


def enriquecer_empresas(empresas, incluir_cnpj, incluir_redes_sociais, incluir_emails_site):
    """
    [V3] Orquestra o enriquecimento, combinando as melhores funções dos dois apps.
    """
    dados_finais = []
    total = len(empresas)
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, emp in enumerate(empresas):
        nome_empresa = emp.get('Nome', '')
        website = emp.get('Website')
        status_text.text(f"Enriquecendo: {nome_empresa} ({i+1}/{total})")
        dados_empresa = {**emp}
        
        if incluir_emails_site and website:
            emails_site = buscar_emails_site(website)
            dados_empresa["Emails_do_Site"] = ", ".join(emails_site) if emails_site else "N/A"
        
        if incluir_cnpj and nome_empresa:
            dados_cnpj_biz = buscar_dados_cnpj_biz(nome_empresa)
            dados_empresa.update({
                "CNPJ_Scraped": dados_cnpj_biz.get("CNPJ"), 
                "Email_CNPJ": dados_cnpj_biz.get("Email_CNPJ"),
                "Sócios": ", ".join(dados_cnpj_biz.get("Sócios", [])),
            })
            if dados_cnpj_biz.get("CNPJ"):
                dados_receita = buscar_dados_receita_federal(dados_cnpj_biz["CNPJ"])
                dados_empresa.update(dados_receita)
        
        if incluir_redes_sociais and website:
            dados_empresa.update(buscar_redes_sociais(website))
        
        dados_finais.append(dados_empresa)
        progress_bar.progress((i + 1) / total)
        time.sleep(random.uniform(1, 2))
    
    progress_bar.empty(); status_text.empty()
    return dados_finais


# ==================== MÉTODOS DE EXTRAÇÃO (do app.py) ====================
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
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com Google API: {e}")
    return results

def serpapi_google_maps(query, location, api_key, num_results=50):
    url = "https://serpapi.com/search"
    params = {"engine": "google_maps", "q": f"{query} {location}", "hl": "pt", "gl": "br", "api_key": api_key, "num": min(num_results, 100)}
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if 'error' in data:
            st.error(f"Erro SerpAPI: {data['error']}"); return []
        return [{'Nome': p.get('title'), 'Endereço': p.get('address'), 'Telefone': p.get('phone'), 'Website': p.get('website'), 'Rating': p.get('rating'), 'Avaliações': p.get('reviews')} for p in data.get("local_results", [])]
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com SerpAPI: {e}"); return []

def search_cnpj_data(cnpj_list):
    results = []
    progress_bar = st.progress(0)
    for i, cnpj in enumerate(cnpj_list):
        dados = buscar_dados_receita_federal(cnpj)
        if dados:
            results.append({'Nome': dados.get('Nome_Receita'), 'CNPJ': dados.get('CNPJ_Receita'), 'Situação': dados.get('Situacao_Receita')})
        progress_bar.progress((i + 1) / len(cnpj_list))
    return results

def simple_web_search(query, location):
    st.info("O método 'Busca Web Simples' é apenas demonstrativo e não extrairá dados.")
    return []

# ==================== INTERFACE STREAMLIT (do app.py, com novas opções) ====================
def main():
    st.set_page_config(page_title="Extração de Empresas", page_icon="🏢", layout="wide")
    st.title("🏢 Extração e Enriquecimento de Dados de Empresas (V3)")
    
    st.sidebar.header("⚙️ Configurações de Extração")
    method = st.sidebar.selectbox("Método:", ["Google Places API", "SerpAPI Google Maps", "Dados Públicos CNPJ", "Busca Web Simples"])
    
    st.sidebar.header("🚀 Opções de Enriquecimento")
    st.sidebar.caption("Aplicável a 'Google Places' e 'SerpAPI'")
    # [NOVO] Checkbox para a busca de e-mails no site
    incluir_emails_site = st.sidebar.checkbox("Buscar E-mails no site oficial", value=True)
    incluir_cnpj = st.sidebar.checkbox("Buscar CNPJ e Sócios", value=True)
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

        if results and is_enrichable and (incluir_cnpj or incluir_redes_sociais or incluir_emails_site):
            st.info(f"Extração inicial concluída com {len(results)} resultados. Iniciando enriquecimento...")
            # [NOVO] Passando o novo parâmetro para a função de enriquecimento
            results = enriquecer_empresas(results, incluir_cnpj, incluir_redes_sociais, incluir_emails_site)
        
        if results:
            df = pd.DataFrame(results).drop_duplicates(subset=['Nome'], keep='first').fillna('N/A')
            st.success(f"✅ **{len(df)} empresas encontradas!**")
            st.dataframe(df)

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
