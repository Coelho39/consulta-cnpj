import requests
import pandas as pd
import streamlit as st
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import re

# ==================== MÉTODO 1: Google Places API ====================
def google_places_search(query, location, api_key, radius=5000):
    """
    Busca empresas usando Google Places API (MELHOR OPÇÃO)
    Requer: Google Cloud Platform API Key
    """
    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    
    params = {
        'query': f"{query} {location}",
        'key': api_key,
        'language': 'pt-BR',
        'region': 'br'
    }
    
    results = []
    next_page_token = None
    
    while True:
        if next_page_token:
            params['pagetoken'] = next_page_token
            time.sleep(2)  # Required delay for next page
            
        response = requests.get(base_url, params=params)
        data = response.json()
        
        if data['status'] != 'OK':
            break
            
        for place in data.get('results', []):
            # Get detailed info
            place_details = get_place_details(place['place_id'], api_key)
            
            results.append({
                'Nome': place.get('name'),
                'Endereço': place.get('formatted_address'),
                'Telefone': place_details.get('phone'),
                'Website': place_details.get('website'),
                'Rating': place.get('rating'),
                'Avaliações': place.get('user_ratings_total'),
                'Categoria': ', '.join(place.get('types', [])),
                'Latitude': place['geometry']['location']['lat'],
                'Longitude': place['geometry']['location']['lng']
            })
        
        next_page_token = data.get('next_page_token')
        if not next_page_token:
            break
            
    return results

def get_place_details(place_id, api_key):
    """Obter detalhes adicionais de um local"""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        'place_id': place_id,
        'fields': 'formatted_phone_number,website,opening_hours',
        'key': api_key
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    if data['status'] == 'OK':
        result = data['result']
        return {
            'phone': result.get('formatted_phone_number'),
            'website': result.get('website'),
            'hours': result.get('opening_hours', {}).get('weekday_text', [])
        }
    return {}

# ==================== MÉTODO 2: Web Scraping Google Maps ====================
def scrape_google_maps(query, location, max_results=50):
    """
    Faz scraping do Google Maps (CUIDADO: pode ser bloqueado)
    """
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    results = []
    
    try:
        search_url = f"https://www.google.com/maps/search/{query}+{location}"
        driver.get(search_url)
        time.sleep(3)
        
        # Scroll para carregar mais resultados
        for i in range(5):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        # Extrair informações dos resultados
        places = driver.find_elements(By.CSS_SELECTOR, "[data-result-index]")
        
        for place in places[:max_results]:
            try:
                name = place.find_element(By.CSS_SELECTOR, "h3").text
                address = place.find_element(By.CSS_SELECTOR, "[data-value='Address']").text
                
                # Tentar encontrar telefone
                try:
                    phone = place.find_element(By.CSS_SELECTOR, "[data-value='Phone']").text
                except:
                    phone = None
                
                # Tentar encontrar website
                try:
                    website = place.find_element(By.CSS_SELECTOR, "a[href*='http']").get_attribute('href')
                except:
                    website = None
                
                results.append({
                    'Nome': name,
                    'Endereço': address,
                    'Telefone': phone,
                    'Website': website
                })
                
            except Exception as e:
                continue
                
    finally:
        driver.quit()
        
    return results

# ==================== MÉTODO 3: API SerpAPI (Google Scraping Service) ====================
def serpapi_google_maps(query, location, api_key, num_results=50):
    """
    Usa SerpAPI para fazer scraping do Google Maps
    Mais estável que scraping direto
    """
    url = "https://serpapi.com/search"
    
    params = {
        "engine": "google_maps",
        "q": f"{query} {location}",
        "hl": "pt",
        "gl": "br",
        "api_key": api_key,
        "num": num_results
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    results = []
    
    for place in data.get("local_results", []):
        results.append({
            'Nome': place.get('title'),
            'Endereço': place.get('address'),
            'Telefone': place.get('phone'),
            'Website': place.get('website'),
            'Rating': place.get('rating'),
            'Avaliações': place.get('reviews'),
            'Categoria': place.get('type'),
            'Horário': place.get('hours')
        })
    
    return results

# ==================== MÉTODO 4: Dados Públicos CNPJ ====================
def search_cnpj_data(cnpj_list):
    """
    Busca dados em APIs públicas de CNPJ
    """
    results = []
    
    for cnpj in cnpj_list:
        # Remove formatação do CNPJ
        cnpj_clean = re.sub(r'\D', '', cnpj)
        
        # API pública CNPJ
        url = f"https://www.receitaws.com.br/v1/cnpj/{cnpj_clean}"
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status') == 'OK':
                    results.append({
                        'Nome': data.get('nome'),
                        'CNPJ': cnpj,
                        'Endereço': f"{data.get('logradouro')}, {data.get('numero')} - {data.get('bairro')} - {data.get('municipio')}/{data.get('uf')}",
                        'Telefone': data.get('telefone'),
                        'Email': data.get('email'),
                        'Atividade': data.get('atividade_principal', [{}])[0].get('text'),
                        'Situação': data.get('situacao')
                    })
            
            time.sleep(1)  # Rate limiting
            
        except Exception as e:
            continue
    
    return results

# ==================== MÉTODO 5: Páginas Amarelas / Guia Mais ====================
def scrape_paginas_amarelas(query, location):
    """
    Scraping das Páginas Amarelas ou Guia Mais
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # URL do Guia Mais (exemplo)
    search_url = f"https://www.guiamais.com.br/busca/{query.replace(' ', '-')}/{location.replace(' ', '-')}"
    
    response = requests.get(search_url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    results = []
    
    # Adaptar seletores CSS conforme o site
    businesses = soup.find_all('div', class_='business-card')  # Exemplo genérico
    
    for business in businesses:
        try:
            name = business.find('h3').text.strip()
            address = business.find('address').text.strip()
            phone = business.find('a', href=re.compile('tel:')).text.strip() if business.find('a', href=re.compile('tel:')) else None
            
            results.append({
                'Nome': name,
                'Endereço': address,
                'Telefone': phone
            })
        except:
            continue
    
    return results

# ==================== INTERFACE STREAMLIT ====================
def main():
    st.set_page_config(page_title="Extração de Empresas - Múltiplas Fontes", layout="wide")
    
    st.title("🏢 Extração de Dados de Empresas - Múltiplas Fontes")
    
    # Sidebar com opções
    st.sidebar.header("Escolha o Método")
    
    method = st.sidebar.selectbox(
        "Método de Extração:",
        [
            "Google Places API (Recomendado)",
            "SerpAPI Google Maps",
            "Web Scraping Google Maps",
            "Dados Públicos CNPJ",
            "Páginas Amarelas/Guia Mais"
        ]
    )
    
    # Inputs principais
    nicho = st.text_input("Nicho da empresa:", placeholder="ex: dentista, restaurante, academia")
    local = st.text_input("Localização:", placeholder="ex: Belo Horizonte, MG")
    limite = st.slider("Número máximo de resultados:", 10, 200, 50)
    
    # Inputs específicos por método
    if method == "Google Places API (Recomendado)":
        api_key = st.text_input("Google Places API Key:", type="password")
        st.info("💡 Melhor qualidade de dados. Requer conta Google Cloud Platform")
        
    elif method == "SerpAPI Google Maps":
        api_key = st.text_input("SerpAPI Key:", type="password")
        st.info("💡 Boa qualidade, sem risco de bloqueio. Serviço pago")
        
    elif method == "Web Scraping Google Maps":
        st.warning("⚠️ Pode ser bloqueado pelo Google. Use com moderação")
        
    elif method == "Dados Públicos CNPJ":
        cnpj_list = st.text_area("Lista de CNPJs:", placeholder="Digite CNPJs, um por linha")
        
    if st.button("🚀 Extrair Dados"):
        if method == "Google Places API (Recomendado)" and api_key:
            with st.spinner("Buscando no Google Places API..."):
                results = google_places_search(nicho, local, api_key)
                
        elif method == "SerpAPI Google Maps" and api_key:
            with st.spinner("Buscando via SerpAPI..."):
                results = serpapi_google_maps(nicho, local, api_key, limite)
                
        elif method == "Web Scraping Google Maps":
            with st.spinner("Fazendo scraping do Google Maps..."):
                results = scrape_google_maps(nicho, local, limite)
                
        elif method == "Dados Públicos CNPJ" and cnpj_list:
            cnpjs = [cnpj.strip() for cnpj in cnpj_list.split('\n') if cnpj.strip()]
            with st.spinner("Consultando dados de CNPJ..."):
                results = search_cnpj_data(cnpjs)
                
        elif method == "Páginas Amarelas/Guia Mais":
            with st.spinner("Fazendo scraping de diretórios..."):
                results = scrape_paginas_amarelas(nicho, local)
        
        else:
            st.error("Preencha todos os campos obrigatórios")
            return
        
        if results:
            df = pd.DataFrame(results)
            st.success(f"✅ Encontradas {len(df)} empresas!")
            
            # Mostrar resultados
            st.dataframe(df, use_container_width=True)
            
            # Download
            csv = df.to_csv(index=False)
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"empresas_{nicho.replace(' ', '_')}_{local.replace(' ', '_')}.csv",
                mime="text/csv"
            )
        else:
            st.warning("Nenhum resultado encontrado")

if __name__ == "__main__":
    main()
