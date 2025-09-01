import os
import io
import re
import time
import json
import random
import unicodedata
from urllib.parse import quote
from typing import List, Dict, Optional

import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

# ==============================================
# Configurações e Utilidades
# ==============================================

APP_TITLE = "🏢 Prospectador B2B – Mineradoras do Pará (v9.1 - Multi-APIs & Anti-Bloqueio)"

st.set_page_config(page_title=APP_TITLE, page_icon="⛏️", layout="wide")

UF_NOMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins"
}

# CNAEs específicos para mineração
CNAES_MINERACAO = {
    "0710-3/01": "Extração de minério de ferro",
    "0721-9/01": "Extração de minério de alumínio",
    "0724-3/01": "Extração de minério de metais preciosos",
    "0729-4/04": "Extração de outros minerais metálicos não-ferrosos",
    "0810-0/00": "Extração de pedra, areia e argila",
    "0891-6/00": "Extração de minerais para fabricação de adubos e fertilizantes",
    "0893-2/00": "Extração de gemas (pedras preciosas e semipreciosas)",
    "0500-3/01": "Extração de carvão mineral",
    "0990-4/01": "Atividades de apoio à extração de minério de ferro",
    "0990-4/02": "Atividades de apoio à extração de minerais metálicos não-ferrosos",
    "0990-4/03": "Atividades de apoio à extração de minerais não-metálicos"
}


def limpa_cnpj(cnpj: str) -> str:
    """Remove caracteres não numéricos de um CNPJ."""
    return re.sub(r"\D", "", str(cnpj or ""))

def formata_cnpj(cnpj: str) -> str:
    """Formata CNPJ com pontuação."""
    c = limpa_cnpj(cnpj)
    if len(c) == 14:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"
    return cnpj

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

@st.cache_data(ttl=60 * 30, show_spinner=False)
def http_get(url: str, timeout: int = 30, headers: dict = None) -> requests.Response | None:
    """Realiza uma requisição HTTP GET com tratamento robusto de erros."""
    try:
        h = headers if headers else {"User-Agent": DEFAULT_UA}
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Erro ao acessar {url}: {str(e)}")
        return None

# ==============================================
# APIs de Consulta CNPJ (Múltiplas Fontes Confiáveis)
# ==============================================

@st.cache_data(ttl=60 * 60, show_spinner=False)
def consultar_cnpj_brasilapi(cnpj: str) -> Dict:
    """Consulta CNPJ na BrasilAPI (fonte principal e mais estável)."""
    c = limpa_cnpj(cnpj)
    if len(c) != 14: return {}
    
    url = f"https://brasilapi.com.br/api/cnpj/v1/{c}"
    r = http_get(url)
    if not r: return {}
    
    try:
        data = r.json()
        telefone = ""
        if data.get("ddd_telefone_1"):
            telefone = f"({data.get('ddd_telefone_1')}) {data.get('telefone_1', '')}"
        
        return {
            "CNPJ": formata_cnpj(data.get("cnpj", "")),
            "Razão Social": data.get("razao_social", ""),
            "Nome Fantasia": data.get("nome_fantasia", ""),
            "Situação": data.get("descricao_situacao_cadastral", ""),
            "CNAE Principal": f"{data.get('cnae_fiscal', '')} - {data.get('cnae_fiscal_descricao', '')}",
            "Telefone": telefone.strip(),
            "Email": data.get("email", "").lower(),
            "Endereço": f"{data.get('logradouro', '')}, {data.get('numero', '')}",
            "Bairro": data.get("bairro", ""),
            "Cidade": data.get("municipio", ""),
            "UF": data.get("uf", ""),
            "CEP": data.get("cep", ""),
            "Fonte dos Dados": "BrasilAPI"
        }
    except Exception as e:
        return {}

@st.cache_data(ttl=60 * 60, show_spinner=False)
def consultar_cnpj_receitaws(cnpj: str) -> Dict:
    """Consulta CNPJ na ReceitaWS (fonte alternativa)."""
    c = limpa_cnpj(cnpj)
    if len(c) != 14: return {}
    
    url = f"https://www.receitaws.com.br/v1/cnpj/{c}"
    r = http_get(url)
    # A API da ReceitaWS tem um limite de requisições, então pode falhar
    if not r or r.status_code != 200: return {}
    
    try:
        data = r.json()
        if data.get("status") == "ERROR": return {}
        
        cnae_principal = data.get('atividade_principal', [{}])[0]

        return {
            "CNPJ": formata_cnpj(data.get("cnpj", "")),
            "Razão Social": data.get("nome", ""),
            "Nome Fantasia": data.get("fantasia", ""),
            "Situação": data.get("situacao", ""),
            "CNAE Principal": f"{cnae_principal.get('code', '')} - {cnae_principal.get('text', '')}",
            "Telefone": data.get("telefone", ""),
            "Email": data.get("email", "").lower(),
            "Endereço": f"{data.get('logradouro', '')}, {data.get('numero', '')}",
            "Bairro": data.get("bairro", ""),
            "Cidade": data.get("municipio", ""),
            "UF": data.get("uf", ""),
            "CEP": data.get("cep", ""),
            "Fonte dos Dados": "ReceitaWS"
        }
    except Exception as e:
        return {}

def consultar_cnpj_multiplas_fontes(cnpj: str) -> Dict:
    """Tenta consultar um CNPJ em múltiplas APIs até obter sucesso."""
    apis = [consultar_cnpj_brasilapi, consultar_cnpj_receitaws]
    
    for api_func in apis:
        try:
            resultado = api_func(cnpj)
            if resultado and resultado.get("CNPJ"):
                return resultado
            time.sleep(1)  # Pausa de 1 segundo entre tentativas de API
        except Exception:
            continue
    
    return {} # Retorna vazio se todas as fontes falharem

# ==============================================
# Descoberta de Empresas (Scraping)
# ==============================================

@st.cache_data(ttl=60 * 30, show_spinner=False)
def buscar_empresas_cnpja_scraping(cnae_code: str, uf: str, max_empresas: int) -> List[Dict]:
    """Busca empresas no site cnpja.com por scraping (única fonte de descoberta)."""
    cnae_limpo = re.sub(r'\D', '', cnae_code)
    # A estrutura correta da URL parece ser por UF primeiro, depois CNAE
    url = f"https://cnpja.com/empresas/{uf.upper()}/?cnae={cnae_limpo}"
    
    headers = {
        'User-Agent': DEFAULT_UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Referer': 'https://www.google.com/',
    }
    
    r = http_get(url, headers=headers)
    if not r: return []
    
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        empresas = []
        
        # A estrutura do site usa listas <ul> com a classe "row-list"
        list_items = soup.select("ul.row-list > li")
        
        for item in list_items[:max_empresas]:
            link_tag = item.find("a")
            if link_tag:
                nome = link_tag.get_text(strip=True)
                # O CNPJ está no próprio texto do item, após "CNPJ: "
                cnpj_text = item.get_text()
                cnpj_match = re.search(r"CNPJ:\s*([\d\.\-/]+)", cnpj_text)
                if nome and cnpj_match:
                    empresas.append({
                        "Nome": nome,
                        "CNPJ": limpa_cnpj(cnpj_match.group(1)),
                        "Origem da Descoberta": f"CNPJá - CNAE {cnae_code}"
                    })
        return empresas
        
    except Exception as e:
        st.warning(f"Erro no scraping do CNPJá para CNAE {cnae_code}: {e}")
        return []


# ==============================================
# Interface Principal do Streamlit
# ==============================================

def main():
    st.title(APP_TITLE)
    st.markdown("🎯 **Foco:** Encontrar e enriquecer dados de empresas de mineração no Pará.")
    
    if "resultados_finais" not in st.session_state:
        st.session_state["resultados_finais"] = []
    
    # Sidebar com configurações
    with st.sidebar:
        st.header("⚙️ Configurações da Busca")
        
        # Seleção de CNAEs
        cnaes_selecionados = st.multiselect(
            "Selecione os CNAEs de Mineração:",
            options=list(CNAES_MINERACAO.keys()),
            format_func=lambda x: f"{x} - {CNAES_MINERACAO[x]}",
            default=list(CNAES_MINERACAO.keys())[:3] # Seleciona os 3 primeiros por padrão
        )
        
        uf_selecionada = st.selectbox("Estado:", list(UF_NOMES.keys()), index=list(UF_NOMES.keys()).index("PA"))
        max_empresas_por_cnae = st.slider("Máx. de empresas a buscar por CNAE:", 5, 50, 10)

    # Botão de busca principal
    if st.button("🚀 Iniciar Prospecção", type="primary", disabled=(not cnaes_selecionados)):
        st.session_state["resultados_finais"] = []
        
        st.info(f"🔍 Iniciando busca em {len(cnaes_selecionados)} CNAEs no estado: {UF_NOMES[uf_selecionada]}")
        
        todas_empresas_descobertas = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Etapa 1: Descoberta de CNPJs via Scraping
        for i, cnae_code in enumerate(cnaes_selecionados):
            progresso = (i + 1) / len(cnaes_selecionados)
            cnae_desc = CNAES_MINERACAO[cnae_code]
            status_text.text(f"Buscando empresas para: {cnae_desc[:50]}...")
            progress_bar.progress(progresso)
            
            empresas_encontradas = buscar_empresas_cnpja_scraping(cnae_code, uf_selecionada, max_empresas_por_cnae)
            todas_empresas_descobertas.extend(empresas_encontradas)
            
            # PAUSA ESTRATÉGICA para evitar erro 429
            time.sleep(random.uniform(2, 5))
        
        progress_bar.empty()
        status_text.empty()
        
        # Remove duplicatas por CNPJ antes de enriquecer
        cnpjs_vistos = set()
        empresas_unicas = []
        for emp in todas_empresas_descobertas:
            cnpj = limpa_cnpj(emp.get("CNPJ", ""))
            if cnpj and cnpj not in cnpjs_vistos:
                cnpjs_vistos.add(cnpj)
                empresas_unicas.append(emp)
        
        if not empresas_unicas:
            st.error("❌ Nenhuma empresa encontrada. O site pode estar bloqueando o acesso ou não há empresas listadas para os critérios. Tente novamente mais tarde.")
            return
        
        st.success(f"✅ Descoberta concluída! {len(empresas_unicas)} empresas únicas encontradas.")
        
        # Etapa 2: Enriquecimento com dados via APIs
        st.info("📊 Enriquecendo dados com informações da Receita Federal via APIs...")
        
        progress_bar_enrich = st.progress(0)
        status_enrich = st.empty()
        resultados_enriquecidos = []
        
        for i, empresa in enumerate(empresas_unicas):
            progresso = (i + 1) / len(empresas_unicas)
            status_enrich.text(f"Enriquecendo: {empresa.get('Nome', '')[:40]}...")
            progress_bar_enrich.progress(progresso)
            
            dados_completos = consultar_cnpj_multiplas_fontes(empresa.get("CNPJ", ""))
            
            if dados_completos:
                # Adiciona a origem da descoberta para referência
                dados_completos["Origem da Descoberta"] = empresa.get("Origem da Descoberta", "")
                resultados_enriquecidos.append(dados_completos)
            
            # Pausa para respeitar os limites das APIs
            time.sleep(random.uniform(0.5, 1.5))
        
        progress_bar_enrich.empty()
        status_enrich.empty()
        
        st.session_state["resultados_finais"] = resultados_enriquecidos
        
        if resultados_enriquecidos:
            st.success(f"🎉 Prospecção concluída! {len(resultados_enriquecidos)} empresas com dados completos.")
            st.balloons()
        else:
            st.warning("⚠️ Empresas foram encontradas, mas falha no enriquecimento dos dados. Verifique a conexão ou os limites das APIs.")

    # Exibição dos resultados
    if st.session_state["resultados_finais"]:
        st.header("📋 Resultados da Prospecção")
        
        df_resultados = pd.DataFrame(st.session_state["resultados_finais"])
        
        # Garante a ordem das colunas
        colunas_ordem = [
            "Razão Social", "Nome Fantasia", "CNPJ", "Telefone", "Email",
            "Situação", "Cidade", "UF", "Endereço", "Bairro", "CEP",
            "CNAE Principal", "Fonte dos Dados", "Origem da Descoberta"
        ]
        colunas_existentes = [col for col in colunas_ordem if col in df_resultados.columns]
        df_display = df_resultados[colunas_existentes]

        st.dataframe(df_display, use_container_width=True)
        
        # Download em Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_display.to_excel(writer, index=False, sheet_name='Prospects')
        excel_data = output.getvalue()
        
        st.download_button(
            label="📥 Baixar Resultados em Excel (.xlsx)",
            data=excel_data,
            file_name=f"prospects_mineradoras_{uf_selecionada.lower()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


if __name__ == "__main__":
    main()
