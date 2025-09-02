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

# ==================== FUNÇÕES DE NORMALIZAÇÃO E PRIORIZAÇÃO ====================

def normalizar_telefone(telefone_str):
    """
    Remove caracteres não numéricos de uma string de telefone.
    """
    if not telefone_str or not isinstance(telefone_str, str):
        return "N/A"
    # Remove todos os caracteres que não são dígitos
    return re.sub(r'\D', '', telefone_str)

def definir_prioridade(row):
    """
    Define a prioridade do lead com base nos dados disponíveis.
    """
    # Verifica se os campos existem e não são 'N/A'
    tem_email = row.get('Emails_do_Site') and row.get('Emails_do_Site') != 'N/A'
    tem_website = row.get('Website') and row.get('Website') != 'N/A'
    tem_telefone = row.get('Telefone') and row.get('Telefone') != 'N/A'
    
    if tem_email and tem_website:
        return "Alta"
    elif tem_telefone and tem_website:
        return "Média"
    elif tem_telefone:
        return "Baixa"
    else:
        return "Muito Baixa"

# ==================== FUNÇÕES DE ENRIQUECIMENTO ====================

def buscar_emails_site(website, timeout=10):
    """
    Busca e-mails diretamente no site oficial da empresa.
    """
    if not website or not isinstance(website, str) or not website.startswith("http"):
        return []
    
    emails_encontrados = set()
    try:
        ua = UserAgent()
        headers = {"User-Agent": ua.random}
        response = requests.get(website, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        found_emails = re.findall(email_pattern, response.text)
        for email in found_emails:
            if not email.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
                emails_encontrados.add(email.lower())

        soup = BeautifulSoup(response.text, "html.parser")
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                email = a["href"].replace("mailto:", "").strip().lower()
                if email:
                    emails_encontrados.add(email)

    except (requests.RequestException, ConnectionError, TimeoutError):
        return []
        
    return list(emails_encontrados)

def buscar_dados_cnpj_biz(nome_empresa, timeout=15):
    """
    Faz scraping no site cnpj.biz para tentar achar o CNPJ, sócios e email.
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

def buscar_redes_sociais(website):
    """
    Tenta encontrar redes sociais no website da empresa.
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
    Orquestra o enriquecimento dos dados extraídos.
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
            dados_empresa["Emails_do_Site"] = ", ".join(emails_site) if emails_site else None
        
        if incluir_cnpj and nome_empresa:
            dados_cnpj_biz = buscar_dados_cnpj_biz(nome_empresa)
            dados_empresa.update({
                "CNPJ_Scraped": dados_cnpj_biz.get("CNPJ"), 
                "Email_CNPJ": dados_cnpj_biz.get("Email_CNPJ"),
                "Sócios": ", ".join(dados_cnpj_biz.get("Sócios", [])),
            })
        
        if incluir_redes_sociais and website:
            dados_empresa.update(buscar_redes_sociais(website))
        
        dados_finais.append(dados_empresa)
        progress_bar.progress((i + 1) / total)
        time.sleep(random.uniform(0.5, 1.5)) # Pequeno delay para não sobrecarregar
    
    progress_bar.empty(); status_text.empty()
    return dados_finais

# ==================== MÉTODO DE EXTRAÇÃO ====================

def serpapi_google_maps(query, api_key, num_results=40):
    """
    Extrai dados do Google Maps usando a API da SerpApi.
    """
    url = "https://serpapi.com/search"
    params = {
        "engine": "google_maps",
        "q": query,
        "hl": "pt",
        "gl": "br",
        "api_key": api_key,
        "num": num_results
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if 'error' in data:
            st.error(f"Erro na SerpAPI para a busca '{query}': {data['error']}")
            return []
        
        # Mapeia os campos para manter a consistência
        results = []
        for p in data.get("local_results", []):
            results.append({
                'Nome': p.get('title'),
                'Endereço': p.get('address'),
                'Telefone': p.get('phone'),
                'Website': p.get('website'),
                'Rating': p.get('rating'),
                'Avaliações': p.get('reviews')
            })
        return results
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com a SerpAPI: {e}")
        return []

# ==================== INTERFACE STREAMLIT ====================
def main():
    st.set_page_config(page_title="Extração de Empresas", page_icon="🏢", layout="wide")
    st.title("🏢 Extração e Enriquecimento de Empresas (V4 - Bulk Search)")
    
    st.sidebar.header("⚙️ Configurações de Extração")
    st.sidebar.info("Este app utiliza exclusivamente a **SerpAPI** para extração de dados.")
    api_key = st.sidebar.text_input("🔑 SerpAPI Key:", type="password")

    st.sidebar.header("🚀 Opções de Enriquecimento")
    incluir_emails_site = st.sidebar.checkbox("Buscar E-mails no site oficial", value=True)
    incluir_cnpj = st.sidebar.checkbox("Buscar CNPJ e Sócios", value=True)
    incluir_redes_sociais = st.sidebar.checkbox("Buscar Redes Sociais", value=False)
    
    st.header("📋 Insira as Buscas (uma por linha)")
    search_text = st.text_area(
        "Cole aqui suas buscas. Cada linha será uma nova consulta no Google Maps.",
        height=200,
        placeholder="Exemplo:\ndentistas em Belo Horizonte, MG\nrestaurantes na Savassi, Belo Horizonte\nadvogados em Contagem, MG"
    )
    search_queries = [query.strip() for query in search_text.split('\n') if query.strip()]

    if st.button("🚀 Extrair e Enriquecer Dados", type="primary"):
        if not api_key:
            st.error("Por favor, insira sua chave da SerpAPI na barra lateral.")
        elif not search_queries:
            st.error("Por favor, insira pelo menos uma busca na área de texto.")
        else:
            all_results = []
            total_queries = len(search_queries)
            st.info(f"Iniciando extração para {total_queries} buscas...")
            
            progress_bar_extraction = st.progress(0)
            status_text_extraction = st.empty()

            for i, query in enumerate(search_queries):
                status_text_extraction.text(f"Buscando: '{query}' ({i+1}/{total_queries})")
                results = serpapi_google_maps(query, api_key)
                all_results.extend(results)
                progress_bar_extraction.progress((i + 1) / total_queries)
                time.sleep(1) # Delay para respeitar a API

            status_text_extraction.empty(); progress_bar_extraction.empty()
            
            if not all_results:
                st.warning("⚠️ Nenhuma empresa encontrada em todas as buscas realizadas.")
                return

            st.success(f"Extração inicial concluída com {len(all_results)} resultados. Iniciando enriquecimento...")
            
            # Etapa de Enriquecimento
            enriched_results = enriquecer_empresas(all_results, incluir_cnpj, incluir_redes_sociais, incluir_emails_site)
            
            # Etapa de Processamento Final e Exibição
            if enriched_results:
                df = pd.DataFrame(enriched_results)
                
                # 1. Desduplicação Aprimorada
                df.drop_duplicates(subset=['Nome', 'Endereço'], keep='first', inplace=True)
                
                # 2. Normalização de Telefone
                if 'Telefone' in df.columns:
                    df['Telefone_Normalizado'] = df['Telefone'].apply(normalizar_telefone)
                
                # 3. Priorização de Leads
                df['Prioridade'] = df.apply(definir_prioridade, axis=1)

                df.fillna("N/A", inplace=True)
                
                st.success(f"✅ **Processo finalizado! {len(df)} empresas únicas encontradas.**")
                st.dataframe(df)

                # --- Botões de Download ---
                @st.cache_data
                def to_excel(df_to_convert):
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_to_convert.to_excel(writer, index=False, sheet_name='Empresas')
                    return output.getvalue()
                
                csv_data = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8')
                excel_data = to_excel(df)
                
                col1, col2 = st.columns(2)
                col1.download_button("📥 Download CSV", csv_data, "empresas.csv", "text/csv")
                col2.download_button("📊 Download Excel", excel_data, "empresas.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning("⚠️ Nenhum resultado após o enriquecimento.")

if __name__ == "__main__":
    main()
