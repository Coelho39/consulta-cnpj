import requests
import pandas as pd
import streamlit as st
import json
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import quote_plus

# ==================== MÉTODO 1: Google Places API ====================
def google_places_search(query, location, api_key, radius=5000):
    """
    Busca empresas usando Google Places API (MELHOR OPÇÃO)
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
    page_count = 0
    
    while page_count < 3:  # Máximo 3 páginas (60 resultados)
        if next_page_token:
            params['pagetoken'] = next_page_token
            time.sleep(3)  # Required delay for next page
            
        try:
            response = requests.get(base_url, params=params, timeout=30)
            data = response.json()
            
            if data['status'] != 'OK':
                if data['status'] == 'ZERO_RESULTS':
                    break
                else:
                    st.error(f"Erro na API: {data.get('error_message', data['status'])}")
                    break
                
            for place in data.get('results', []):
                # Get detailed info
                place_details = get_place_details(place['place_id'], api_key)
                
                results.append({
                    'Nome': place.get('name', 'N/A'),
                    'Endereço': place.get('formatted_address', 'N/A'),
                    'Telefone': place_details.get('phone', 'N/A'),
                    'Website': place_details.get('website', 'N/A'),
                    'Rating': place.get('rating', 'N/A'),
                    'Avaliações': place.get('user_ratings_total', 'N/A'),
                    'Categoria': ', '.join(place.get('types', [])),
                    'Latitude': place['geometry']['location']['lat'],
                    'Longitude': place['geometry']['location']['lng']
                })
            
            next_page_token = data.get('next_page_token')
            if not next_page_token:
                break
                
            page_count += 1
            
        except requests.exceptions.RequestException as e:
            st.error(f"Erro na requisição: {e}")
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
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data['status'] == 'OK':
            result = data['result']
            return {
                'phone': result.get('formatted_phone_number'),
                'website': result.get('website'),
                'hours': result.get('opening_hours', {}).get('weekday_text', [])
            }
    except:
        pass
        
    return {'phone': None, 'website': None, 'hours': []}

# ==================== MÉTODO 2: API SerpAPI ====================
def serpapi_google_maps(query, location, api_key, num_results=50):
    """
    Usa SerpAPI para fazer scraping do Google Maps
    """
    url = "https://serpapi.com/search"
    
    params = {
        "engine": "google_maps",
        "q": f"{query} {location}",
        "hl": "pt",
        "gl": "br",
        "api_key": api_key,
        "num": min(num_results, 100)
    }
    
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        
        if 'error' in data:
            st.error(f"Erro SerpAPI: {data['error']}")
            return []
        
        results = []
        
        for place in data.get("local_results", []):
            results.append({
                'Nome': place.get('title', 'N/A'),
                'Endereço': place.get('address', 'N/A'),
                'Telefone': place.get('phone', 'N/A'),
                'Website': place.get('website', 'N/A'),
                'Rating': place.get('rating', 'N/A'),
                'Avaliações': place.get('reviews', 'N/A'),
                'Categoria': place.get('type', 'N/A'),
                'Horário': place.get('hours', 'N/A')
            })
        
        return results
        
    except requests.exceptions.RequestException as e:
        st.error(f"Erro na requisição SerpAPI: {e}")
        return []

# ==================== MÉTODO 3: Dados Públicos CNPJ ====================
def search_cnpj_data(cnpj_list):
    """
    Busca dados em APIs públicas de CNPJ
    """
    results = []
    progress_bar = st.progress(0)
    
    for i, cnpj in enumerate(cnpj_list):
        # Remove formatação do CNPJ
        cnpj_clean = re.sub(r'\D', '', cnpj)
        
        if len(cnpj_clean) != 14:
            continue
        
        # API pública CNPJ (alternativas)
        apis = [
            f"https://www.receitaws.com.br/v1/cnpj/{cnpj_clean}",
            f"https://publica.cnpj.ws/cnpj/{cnpj_clean}",
        ]
        
        for api_url in apis:
            try:
                response = requests.get(api_url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    
                    # ReceitaWS format
                    if 'status' in data and data.get('status') == 'OK':
                        results.append({
                            'Nome': data.get('nome', 'N/A'),
                            'CNPJ': cnpj,
                            'Endereço': f"{data.get('logradouro', '')}, {data.get('numero', '')} - {data.get('bairro', '')} - {data.get('municipio', '')}/{data.get('uf', '')}".strip(' ,-'),
                            'Telefone': data.get('telefone', 'N/A'),
                            'Email': data.get('email', 'N/A'),
                            'Atividade': data.get('atividade_principal', [{}])[0].get('text', 'N/A') if data.get('atividade_principal') else 'N/A',
                            'Situação': data.get('situacao', 'N/A')
                        })
                        break
                    
                    # CNPJ.ws format
                    elif 'razao_social' in data:
                        endereco = data.get('estabelecimento', {})
                        results.append({
                            'Nome': data.get('razao_social', 'N/A'),
                            'CNPJ': cnpj,
                            'Endereço': f"{endereco.get('tipo_logradouro', '')} {endereco.get('logradouro', '')}, {endereco.get('numero', '')} - {endereco.get('bairro', '')} - {endereco.get('cidade', {}).get('nome', '')}/{endereco.get('estado', {}).get('sigla', '')}".strip(' ,-'),
                            'Telefone': endereco.get('ddd1', '') + endereco.get('telefone1', '') if endereco.get('telefone1') else 'N/A',
                            'Email': endereco.get('email', 'N/A'),
                            'Atividade': data.get('natureza_juridica', {}).get('descricao', 'N/A'),
                            'Situação': data.get('situacao_cadastral', 'N/A')
                        })
                        break
                
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                continue
        
        # Update progress
        progress_bar.progress((i + 1) / len(cnpj_list))
    
    return results

# ==================== MÉTODO 4: Scraping Simples ====================
def simple_web_search(query, location):
    """
    Busca simples usando requests + BeautifulSoup
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    results = []
    
    # Tentar diferentes fontes
    search_terms = f"{query} {location}"
    
    # Exemplo: Busca no Google (muito básico)
    try:
        search_url = f"https://www.google.com/search?q={quote_plus(search_terms)}"
        response = requests.get(search_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            # Parse muito básico - apenas para demonstração
            # Em produção, seria necessário um parser mais sofisticado
            st.info("Scraping básico implementado - resultados limitados")
            
    except Exception as e:
        st.warning(f"Scraping não disponível: {e}")
    
    return results

# ==================== INTERFACE STREAMLIT ====================
def main():
    st.set_page_config(
        page_title="Extração de Empresas",
        page_icon="🏢",
        layout="wide"
    )
    
    st.title("🏢 Extração de Dados de Empresas")
    st.markdown("### Múltiplas fontes de dados para prospecção comercial")
    
    # Sidebar com opções
    st.sidebar.header("⚙️ Configurações")
    
    method = st.sidebar.selectbox(
        "Método de Extração:",
        [
            "Google Places API",
            "SerpAPI Google Maps", 
            "Dados Públicos CNPJ",
            "Busca Web Simples"
        ]
    )
    
    # Inputs principais
    col1, col2 = st.columns(2)
    
    with col1:
        nicho = st.text_input("🎯 Nicho da empresa:", placeholder="ex: dentista, restaurante, academia")
        
    with col2:
        local = st.text_input("📍 Localização:", placeholder="ex: Belo Horizonte, MG")
    
    limite = st.slider("📊 Número máximo de resultados:", 10, 200, 50)
    
    # Inputs específicos por método
    api_key = None
    cnpj_list = []
    
    if method == "Google Places API":
        api_key = st.text_input("🔑 Google Places API Key:", type="password", help="Obtenha em: https://console.cloud.google.com/")
        st.info("💡 **Melhor qualidade de dados.** Requer conta Google Cloud Platform (~$17 por 1.000 consultas)")
        
    elif method == "SerpAPI Google Maps":
        api_key = st.text_input("🔑 SerpAPI Key:", type="password", help="Obtenha em: https://serpapi.com/")
        st.info("💡 **Boa qualidade, sem risco de bloqueio.** Serviço pago (~$50/mês)")
        
    elif method == "Dados Públicos CNPJ":
        cnpj_text = st.text_area("📋 Lista de CNPJs:", placeholder="Digite CNPJs, um por linha\n12.345.678/0001-90\n98.765.432/0001-10")
        if cnpj_text:
            cnpj_list = [cnpj.strip() for cnpj in cnpj_text.split('\n') if cnpj.strip()]
        st.info("💡 **Dados oficiais da Receita Federal.** Gratuito")
        
    elif method == "Busca Web Simples":
        st.info("💡 **Solução básica gratuita.** Resultados limitados")
    
    # Botão principal
    if st.button("🚀 Extrair Dados", type="primary"):
        
        results = []
        
        if method == "Google Places API":
            if not api_key:
                st.error("❌ Insira sua Google Places API Key")
                return
            if not (nicho and local):
                st.error("❌ Preencha o nicho e localização")
                return
                
            with st.spinner("🔍 Buscando no Google Places API..."):
                results = google_places_search(nicho, local, api_key)
                
        elif method == "SerpAPI Google Maps":
            if not api_key:
                st.error("❌ Insira sua SerpAPI Key")
                return
            if not (nicho and local):
                st.error("❌ Preencha o nicho e localização")
                return
                
            with st.spinner("🔍 Buscando via SerpAPI..."):
                results = serpapi_google_maps(nicho, local, api_key, limite)
                
        elif method == "Dados Públicos CNPJ":
            if not cnpj_list:
                st.error("❌ Insira pelo menos um CNPJ")
                return
                
            with st.spinner(f"🔍 Consultando {len(cnpj_list)} CNPJs..."):
                results = search_cnpj_data(cnpj_list)
                
        elif method == "Busca Web Simples":
            if not (nicho and local):
                st.error("❌ Preencha o nicho e localização")
                return
                
            with st.spinner("🔍 Fazendo busca web básica..."):
                results = simple_web_search(nicho, local)
        
        # Mostrar resultados
        if results:
            df = pd.DataFrame(results)
            
            # Remover duplicatas se existirem
            if 'Nome' in df.columns:
                df = df.drop_duplicates(subset=['Nome'], keep='first')
            
            st.success(f"✅ **{len(df)} empresas encontradas!**")
            
            # Estatísticas rápidas
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total", len(df))
            with col2:
                if 'Telefone' in df.columns:
                    with_phone = sum(1 for x in df['Telefone'] if x and x != 'N/A')
                    st.metric("Com Telefone", with_phone)
            with col3:
                if 'Website' in df.columns:
                    with_website = sum(1 for x in df['Website'] if x and x != 'N/A')
                    st.metric("Com Website", with_website)
            with col4:
                if 'Rating' in df.columns:
                    avg_rating = df[df['Rating'] != 'N/A']['Rating'].mean() if 'Rating' in df.columns else 0
                    st.metric("Rating Médio", f"{avg_rating:.1f}" if avg_rating > 0 else "N/A")
            
            # Mostrar tabela
            st.dataframe(df, use_container_width=True)
            
            # Downloads
            col1, col2 = st.columns(2)
            
            with col1:
                csv = df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 Download CSV",
                    data=csv,
                    file_name=f"empresas_{nicho.replace(' ', '_')}_{local.replace(' ', '_')}.csv",
                    mime="text/csv"
                )
            
            with col2:
                # Excel download
                excel_buffer = df.to_excel(index=False, engine='openpyxl')
                st.download_button(
                    label="📊 Download Excel", 
                    data=excel_buffer,
                    file_name=f"empresas_{nicho.replace(' ', '_')}_{local.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
        else:
            st.warning("⚠️ Nenhum resultado encontrado. Tente:")
            st.markdown("- Verificar a API Key")
            st.markdown("- Usar termos mais genéricos")
            st.markdown("- Tentar uma localização diferente")

    # Footer
    st.markdown("---")
    with st.expander("ℹ️ Informações sobre os métodos"):
        st.markdown("""
        **Google Places API**: Melhor qualidade, dados completos, requer conta Google Cloud
        
        **SerpAPI**: Boa qualidade, sem bloqueios, serviço pago especializado
        
        **CNPJ Público**: Dados oficiais da Receita Federal, gratuito, requer lista de CNPJs
        
        **Busca Web**: Solução básica gratuita, resultados limitados
        """)

if __name__ == "__main__":
    main()
