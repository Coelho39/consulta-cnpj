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

# ==================== FUNÇÕES DE ENRIQUECIMENTO ====================

def buscar_dados_cnpj_biz(nome_empresa, timeout=15):
    """
    Faz scraping no site cnpj.biz para tentar achar o CNPJ, sócios e email
    """
    try:
        # Headers para evitar bloqueio, usando fake_useragent
        ua = UserAgent()
        headers = {
            'User-Agent': ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Limpar nome da empresa para busca
        query = re.sub(r'[^\w\s]', ' ', nome_empresa).strip()
        query = re.sub(r'\s+', '+', query)
        
        # Buscar na página inicial
        url = f"https://cnpj.biz/search/{query}"
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Procurar links de empresas
        empresa_links = []
        for link in soup.find_all("a", href=True):
            if "/cnpj/" in link["href"]:
                empresa_links.append(urljoin("https://cnpj.biz", link["href"]))
        
        if not empresa_links:
            return {"CNPJ": None, "Sócios": [], "Email": None, "Situação": None}
        
        # Pegar o primeiro link encontrado
        empresa_url = empresa_links[0]
        time.sleep(random.uniform(1, 2)) # Delay para evitar bloqueio
        
        # Buscar detalhes da empresa
        detalhe_response = requests.get(empresa_url, headers=headers, timeout=timeout)
        detalhe_response.raise_for_status()
        
        soup_det = BeautifulSoup(detalhe_response.text, "html.parser")
        
        page_text = soup_det.get_text()

        # Extrair CNPJ
        cnpj = None
        cnpj_patterns = [
            r'CNPJ[:\s]*(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})',
            r'(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})'
        ]
        for pattern in cnpj_patterns:
            match = re.search(pattern, page_text)
            if match:
                cnpj = match.group(1)
                break
        
        # Extrair sócios
        socios = []
        socio_patterns = [
            r'Sócio[:\s]*([^\n\r]+)',
            r'Administrador[:\s]*([^\n\r]+)',
            r'Responsável[:\s]*([^\n\r]+)'
        ]
        for pattern in socio_patterns:
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            socios.extend([match.strip() for match in matches if match.strip() and len(match.strip()) > 3])
        socios = list(set(socios))
        
        # Extrair email
        email = None
        email_links = soup_det.find_all("a", href=re.compile(r"mailto:"))
        if email_links:
            email = email_links[0]["href"].replace("mailto:", "").strip()
        
        if not email:
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            email_match = re.search(email_pattern, page_text)
            if email_match:
                email = email_match.group()
        
        # Buscar situação da empresa
        situacao = None
        situacao_patterns = [
            r'Situação[:\s]*([^\n\r]+)',
            r'Status[:\s]*([^\n\r]+)',
            r'Ativa|Inativa|Suspensa|Baixada'
        ]
        for pattern in situacao_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                situacao = match.group(1) if len(match.groups()) > 0 else match.group()
                break
        
        return {
            "CNPJ": cnpj,
            "Sócios": socios,
            "Email": email,
            "Situação": situacao
        }
        
    except Exception as e:
        # st.warning(f"Erro ao buscar dados CNPJ para {nome_empresa}: {str(e)}")
        return {"CNPJ": None, "Sócios": [], "Email": None, "Situação": None}

def buscar_dados_receita_federal(cnpj):
    """
    Busca dados em APIs públicas da Receita Federal
    """
    if not cnpj:
        return {}
    
    cnpj_limpo = re.sub(r'\D', '', cnpj)
    if len(cnpj_limpo) != 14:
        return {}
    
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
                
                # Formato ReceitaWS
                if 'status' in data and data.get('status') == 'OK':
                    return {
                        'Nome_Receita': data.get('nome'),
                        'Fantasia': data.get('fantasia'),
                        'CNPJ_Receita': data.get('cnpj'),
                        'Situacao_Receita': data.get('situacao'),
                        'Atividade_Principal': data.get('atividade_principal', [{}])[0].get('text') if data.get('atividade_principal') else None,
                        'Telefone_Receita': data.get('telefone'),
                        'Email_Receita': data.get('email'),
                        'Capital_Social': data.get('capital_social'),
                        'Porte': data.get('porte'),
                        'Natureza_Juridica': data.get('natureza_juridica')
                    }
                
                # Formato CNPJ.ws
                elif 'razao_social' in data and 'estabelecimento' in data:
                    estabelecimento = data.get('estabelecimento', {})
                    return {
                        'Nome_Receita': data.get('razao_social'),
                        'Fantasia': estabelecimento.get('nome_fantasia'),
                        'CNPJ_Receita': estabelecimento.get('cnpj'),
                        'Situacao_Receita': data.get('situacao_cadastral'),
                        'Atividade_Principal': data.get('atividade_principal', {}).get('descricao'),
                        'Telefone_Receita': f"{estabelecimento.get('ddd1', '')}{estabelecimento.get('telefone1', '')}" if estabelecimento.get('telefone1') else None,
                        'Email_Receita': estabelecimento.get('email'),
                        'Capital_Social': data.get('capital_social'),
                        'Porte': data.get('porte', {}).get('descricao'),
                        'Natureza_Juridica': data.get('natureza_juridica', {}).get('descricao')
                    }
                
                # Formato BrasilAPI
                elif 'razao_social' in data:
                    return {
                        'Nome_Receita': data.get('razao_social'),
                        'Fantasia': data.get('nome_fantasia'),
                        'CNPJ_Receita': data.get('cnpj'),
                        'Situacao_Receita': data.get('descricao_situacao_cadastral'),
                        'Atividade_Principal': data.get('cnae_fiscal_descricao'),
                        'Capital_Social': data.get('capital_social'),
                        'Porte': data.get('porte'),
                        'Natureza_Juridica': data.get('natureza_juridica')
                    }
            
            time.sleep(1) # Rate limiting
            
        except Exception:
            continue
    
    return {}

def buscar_redes_sociais(website):
    """
    Tenta encontrar redes sociais no website da empresa
    """
    redes_sociais = {
        'Facebook': None,
        'Instagram': None,
        'LinkedIn': None,
        'Twitter': None
    }
    
    if not website or website == 'N/A' or not website.startswith('http'):
        return redes_sociais

    try:
        ua = UserAgent()
        headers = {'User-Agent': ua.random}
        response = requests.get(website, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if not redes_sociais['Facebook'] and 'facebook.com' in href:
                redes_sociais['Facebook'] = a['href']
            elif not redes_sociais['Instagram'] and 'instagram.com' in href:
                redes_sociais['Instagram'] = a['href']
            elif not redes_sociais['LinkedIn'] and 'linkedin.com' in href:
                redes_sociais['LinkedIn'] = a['href']
            elif not redes_sociais['Twitter'] and ('twitter.com' in href or 'x.com' in href):
                redes_sociais['Twitter'] = a['href']
                
    except Exception:
        pass # Ignora erros de conexão ou parsing
        
    return redes_sociais

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
        website = emp.get('Website')
        
        status_text.text(f"Enriquecendo: {nome_empresa} ({i+1}/{total})")
        
        dados_empresa = {**emp}
        
        if incluir_cnpj and nome_empresa:
            dados_cnpj_biz = buscar_dados_cnpj_biz(nome_empresa)
            
            dados_empresa.update({
                "CNPJ_Scraped": dados_cnpj_biz.get("CNPJ"),
                "Email_Scraped": dados_cnpj_biz.get("Email"),
                "Sócios": ", ".join(dados_cnpj_biz.get("Sócios", [])),
                "Situação_Scraped": dados_cnpj_biz.get("Situação")
            })
            
            if dados_cnpj_biz.get("CNPJ"):
                dados_receita = buscar_dados_receita_federal(dados_cnpj_biz["CNPJ"])
                dados_empresa.update(dados_receita)
        
        if incluir_redes_sociais:
            redes = buscar_redes_sociais(website)
            dados_empresa.update(redes)
        
        dados_finais.append(dados_empresa)
        progress_bar.progress((i + 1) / total)
        time.sleep(random.uniform(1, 3)) # Delay para evitar bloqueios
    
    progress_bar.empty()
    status_text.empty()
    
    return dados_finais

# ==================== MÉTODO 1: Google Places API ====================
def google_places_search(query, location, api_key):
    """
    Busca empresas usando Google Places API
    """
    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {'query': f"{query} {location}", 'key': api_key, 'language': 'pt-BR', 'region': 'br'}
    results = []
    page_count = 0
    
    while page_count < 3:  # Máximo 3 páginas (aprox. 60 resultados)
        try:
            response = requests.get(base_url, params=params, timeout=30)
            data = response.json()
            
            if data['status'] not in ['OK', 'ZERO_RESULTS']:
                st.error(f"Erro na API Google: {data.get('error_message', data['status'])}")
                break
            
            for place in data.get('results', []):
                place_details = get_place_details(place.get('place_id'), api_key)
                results.append({
                    'Nome': place.get('name'),
                    'Endereço': place.get('formatted_address'),
                    'Telefone': place_details.get('phone'),
                    'Website': place_details.get('website'),
                    'Rating': place.get('rating'),
                    'Avaliações': place.get('user_ratings_total'),
                    'Categoria': ', '.join(place.get('types', [])),
                })
            
            next_page_token = data.get('next_page_token')
            if not next_page_token:
                break
            
            params['pagetoken'] = next_page_token
            page_count += 1
            time.sleep(3) # Delay obrigatório para a próxima página
            
        except requests.exceptions.RequestException as e:
            st.error(f"Erro de conexão com Google API: {e}")
            break
            
    return results

def get_place_details(place_id, api_key):
    """Obter detalhes adicionais de um local (telefone, site)"""
    if not place_id: return {}
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {'place_id': place_id, 'fields': 'formatted_phone_number,website', 'key': api_key, 'language': 'pt-BR'}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if data['status'] == 'OK':
            result = data.get('result', {})
            return {'phone': result.get('formatted_phone_number'), 'website': result.get('website')}
    except requests.exceptions.RequestException:
        pass
    return {}

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
            st.error(f"Erro SerpAPI: {data['error']}")
            return []
        
        return [{
            'Nome': place.get('title'),
            'Endereço': place.get('address'),
            'Telefone': place.get('phone'),
            'Website': place.get('website'),
            'Rating': place.get('rating'),
            'Avaliações': place.get('reviews'),
            'Categoria': place.get('type'),
        } for place in data.get("local_results", [])]
        
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com SerpAPI: {e}")
        return []

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
            results.append({
                'Nome': dados.get('Nome_Receita'),
                'CNPJ': dados.get('CNPJ_Receita'),
                'Endereço': 'N/A', # APIs de CNPJ nem sempre trazem endereço formatado
                'Telefone': dados.get('Telefone_Receita'),
                'Email': dados.get('Email_Receita'),
                'Atividade': dados.get('Atividade_Principal'),
                'Situação': dados.get('Situacao_Receita')
            })
        progress_bar.progress((i + 1) / len(cnpj_list))
    return results

# ==================== MÉTODO 4: Scraping Simples (Demonstrativo) ====================
def simple_web_search(query, location):
    """
    Busca simples usando requests + BeautifulSoup (limitado)
    """
    st.info("O método 'Busca Web Simples' é apenas demonstrativo e não extrairá dados.")
    return []

# ==================== INTERFACE STREAMLIT ====================
def main():
    st.set_page_config(page_title="Extração de Empresas", page_icon="🏢", layout="wide")
    
    st.title("🏢 Extração e Enriquecimento de Dados de Empresas")
    st.markdown("### Prospecção comercial com múltiplas fontes de dados e enriquecimento avançado")
    
    st.sidebar.header("⚙️ Configurações de Extração")
    method = st.sidebar.selectbox(
        "Método de Extração:",
        ["Google Places API", "SerpAPI Google Maps", "Dados Públicos CNPJ", "Busca Web Simples"]
    )
    
    st.sidebar.header("🚀 Opções de Enriquecimento")
    st.sidebar.caption("Aplicável a 'Google Places' e 'SerpAPI'")
    incluir_cnpj = st.sidebar.checkbox("Buscar CNPJ, Sócios e E-mail", value=True)
    incluir_redes_sociais = st.sidebar.checkbox("Buscar Redes Sociais", value=False)
    
    col1, col2 = st.columns(2)
    with col1:
        nicho = st.text_input("🎯 Nicho da empresa:", placeholder="ex: dentista, restaurante, academia")
    with col2:
        local = st.text_input("📍 Localização:", placeholder="ex: Belo Horizonte, MG")
    
    limite = st.slider("📊 Número máximo de resultados:", 10, 100, 20, help="Apenas para SerpAPI")
    
    api_key, cnpj_list = None, []
    
    if method == "Google Places API":
        api_key = st.text_input("🔑 Google Places API Key:", type="password")
        st.info("💡 **Melhor qualidade de dados.** Requer conta Google Cloud Platform.")
    elif method == "SerpAPI Google Maps":
        api_key = st.text_input("🔑 SerpAPI Key:", type="password")
        st.info("💡 **Boa qualidade, sem risco de bloqueio.** Serviço pago.")
    elif method == "Dados Públicos CNPJ":
        cnpj_text = st.text_area("📋 Lista de CNPJs (um por linha):", height=150)
        if cnpj_text:
            cnpj_list = [cnpj.strip() for cnpj in cnpj_text.split('\n') if cnpj.strip()]
        st.info("💡 **Dados oficiais da Receita Federal.** Gratuito.")
    elif method == "Busca Web Simples":
        st.info("💡 **Solução básica e limitada.**")

    if st.button("🚀 Extrair e Enriquecer Dados", type="primary"):
        results = []
        is_enrichable = method in ["Google Places API", "SerpAPI Google Maps"]

        with st.spinner("Iniciando extração..."):
            if method == "Google Places API":
                if api_key and nicho and local:
                    results = google_places_search(nicho, local, api_key)
                else: st.error("Preencha Nicho, Localização e API Key.")
            
            elif method == "SerpAPI Google Maps":
                if api_key and nicho and local:
                    results = serpapi_google_maps(nicho, local, api_key, limite)
                else: st.error("Preencha Nicho, Localização e API Key.")
            
            elif method == "Dados Públicos CNPJ":
                if cnpj_list:
                    results = search_cnpj_data(cnpj_list)
                else: st.error("Insira pelo menos um CNPJ.")
            
            elif method == "Busca Web Simples":
                results = simple_web_search(nicho, local)

        if results and is_enrichable and (incluir_cnpj or incluir_redes_sociais):
            st.info(f"Extração inicial concluída com {len(results)} resultados. Iniciando enriquecimento...")
            results = enriquecer_empresas(results, incluir_cnpj, incluir_redes_sociais)
        
        if results:
            df = pd.DataFrame(results).drop_duplicates(subset=['Nome'], keep='first').fillna('N/A')
            st.success(f"✅ **{len(df)} empresas encontradas e processadas!**")
            st.dataframe(df)

            # Downloads
            col1, col2 = st.columns(2)
            csv = df.to_csv(index=False, encoding='utf-8-sig')
            col1.download_button("📥 Download CSV", csv, f"empresas_{nicho}_{local}.csv", "text/csv")
            
            excel_buffer = pd.ExcelWriter('empresas.xlsx', engine='openpyxl')
            df.to_excel(excel_buffer, index=False)
            excel_buffer.close()
            with open('empresas.xlsx', 'rb') as f:
                col2.download_button("📊 Download Excel", f, f"empresas_{nicho}_{local}.xlsx")
        else:
            st.warning("⚠️ Nenhum resultado encontrado.")

if __name__ == "__main__":
    main()
