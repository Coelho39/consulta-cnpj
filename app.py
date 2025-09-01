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

APP_TITLE = "🏢 Prospectador B2B – Mineradoras do Pará (v9.0 - Multi-APIs)"

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
    "0725-1/00": "Extração de minerais radioativos",
    "0729-4/04": "Extração de minérios de metais preciosos",
    "0810-0/06": "Extração de areia, cascalho ou pedregulho e beneficiamento associado",
    "0810-0/07": "Extração de argila e beneficiamento associado",
    "0810-0/08": "Extração de saibro e beneficiamento associado",
    "0891-6/00": "Extração de minerais para fabricação de adubos, fertilizantes e outros produtos químicos",
    "0899-1/99": "Extração de minerais não-metálicos não especificados anteriormente",
    "0990-4/01": "Atividades de apoio à extração de minério de ferro",
    "0990-4/02": "Atividades de apoio à extração de minerais metálicos não-ferrosos",
    "0990-4/03": "Atividades de apoio à extração de minerais não-metálicos"
}

def slug(s: str) -> str:
    """Converte uma string para um formato 'slug' amigável para URLs."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

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
# APIs de Consulta CNPJ (Múltiplas Fontes)
# ==============================================

@st.cache_data(ttl=60 * 60, show_spinner=False)
def consultar_cnpj_brasilapi(cnpj: str) -> Dict:
    """Consulta CNPJ na BrasilAPI (mais estável)."""
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
            "Email": data.get("email", ""),
            "Endereço": f"{data.get('logradouro', '')}, {data.get('numero', '')}",
            "Bairro": data.get("bairro", ""),
            "Cidade": data.get("municipio", ""),
            "UF": data.get("uf", ""),
            "CEP": data.get("cep", ""),
            "Fonte": "BrasilAPI"
        }
    except Exception as e:
        st.warning(f"Erro ao processar dados do CNPJ {cnpj}: {e}")
        return {}

@st.cache_data(ttl=60 * 60, show_spinner=False)
def consultar_cnpj_receitaws(cnpj: str) -> Dict:
    """Consulta CNPJ na ReceitaWS (fonte alternativa)."""
    c = limpa_cnpj(cnpj)
    if len(c) != 14: return {}
    
    url = f"https://www.receitaws.com.br/v1/cnpj/{c}"
    r = http_get(url)
    if not r: return {}
    
    try:
        data = r.json()
        if data.get("status") == "ERROR": return {}
        
        telefone = data.get("telefone", "")
        if telefone and telefone != "(  )     -     ":
            telefone = telefone
        else:
            telefone = ""
            
        return {
            "CNPJ": formata_cnpj(data.get("cnpj", "")),
            "Razão Social": data.get("nome", ""),
            "Nome Fantasia": data.get("fantasia", ""),
            "Situação": data.get("situacao", ""),
            "CNAE Principal": f"{data.get('atividade_principal', [{}])[0].get('code', '')} - {data.get('atividade_principal', [{}])[0].get('text', '')}",
            "Telefone": telefone,
            "Email": data.get("email", ""),
            "Endereço": f"{data.get('logradouro', '')}, {data.get('numero', '')}",
            "Bairro": data.get("bairro", ""),
            "Cidade": data.get("municipio", ""),
            "UF": data.get("uf", ""),
            "CEP": data.get("cep", ""),
            "Fonte": "ReceitaWS"
        }
    except Exception as e:
        st.warning(f"Erro ao processar dados ReceitaWS para {cnpj}: {e}")
        return {}

@st.cache_data(ttl=60 * 60, show_spinner=False)
def consultar_cnpj_cnpjws(cnpj: str) -> Dict:
    """Consulta CNPJ na CNPJ.ws (terceira opção)."""
    c = limpa_cnpj(cnpj)
    if len(c) != 14: return {}
    
    # API pública tem limite de 3 consultas por minuto
    url = f"https://publica.cnpj.ws/cnpj/{c}"
    r = http_get(url)
    if not r: return {}
    
    try:
        data = r.json()
        estabelecimento = data.get("estabelecimento", {})
        
        telefone = ""
        if estabelecimento.get("ddd1") and estabelecimento.get("telefone1"):
            telefone = f"({estabelecimento.get('ddd1')}) {estabelecimento.get('telefone1')}"
            
        return {
            "CNPJ": formata_cnpj(estabelecimento.get("cnpj", "")),
            "Razão Social": data.get("razao_social", ""),
            "Nome Fantasia": estabelecimento.get("nome_fantasia", ""),
            "Situação": estabelecimento.get("situacao_cadastral", ""),
            "CNAE Principal": f"{estabelecimento.get('atividade_principal', {}).get('id', '')} - {estabelecimento.get('atividade_principal', {}).get('descricao', '')}",
            "Telefone": telefone,
            "Email": estabelecimento.get("email", ""),
            "Endereço": f"{estabelecimento.get('tipo_logradouro', '')} {estabelecimento.get('logradouro', '')}, {estabelecimento.get('numero', '')}",
            "Bairro": estabelecimento.get("bairro", ""),
            "Cidade": estabelecimento.get("cidade", {}).get("nome", ""),
            "UF": estabelecimento.get("estado", {}).get("sigla", ""),
            "CEP": estabelecimento.get("cep", ""),
            "Fonte": "CNPJ.ws"
        }
    except Exception as e:
        st.warning(f"Erro ao processar dados CNPJ.ws para {cnpj}: {e}")
        return {}

def consultar_cnpj_multiplas_fontes(cnpj: str) -> Dict:
    """Tenta consultar um CNPJ em múltiplas APIs até obter sucesso."""
    apis = [consultar_cnpj_brasilapi, consultar_cnpj_receitaws, consultar_cnpj_cnpjws]
    
    for api_func in apis:
        try:
            resultado = api_func(cnpj)
            if resultado and resultado.get("CNPJ"):
                return resultado
            time.sleep(0.5)  # Pausa entre APIs
        except Exception as e:
            continue
    
    return {}

# ==============================================
# Busca por Empresas de Mineração
# ==============================================

@st.cache_data(ttl=60 * 60, show_spinner=False)
def encontrar_cnaes_mineracao(termo_busca: str = "") -> List[Dict]:
    """Retorna CNAEs relacionados à mineração, com filtro opcional por termo."""
    cnaes_filtrados = []
    termo_lower = termo_busca.lower() if termo_busca else ""
    
    for codigo, descricao in CNAES_MINERACAO.items():
        if not termo_lower or termo_lower in descricao.lower():
            cnaes_filtrados.append({"codigo": codigo, "descricao": descricao})
    
    return cnaes_filtrados

@st.cache_data(ttl=60 * 30, show_spinner=False)
def buscar_empresas_cnpja_scraping(cnae_code: str, uf: str, max_empresas: int = 20) -> List[Dict]:
    """Busca empresas no site cnpja.com por scraping (método mais confiável)."""
    cnae_limpo = re.sub(r'\D', '', cnae_code)
    url = f"https://cnpja.com/cnae/{cnae_limpo}"
    
    headers = {
        'User-Agent': DEFAULT_UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://www.google.com.br/',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    r = http_get(url, headers=headers)
    if not r: return []
    
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        empresas = []
        
        # Procura por diferentes padrões de listagem de empresas
        links_empresas = soup.find_all("a", href=re.compile(r"/empresa/"))
        
        if not links_empresas:
            # Tenta padrão alternativo
            links_empresas = soup.find_all("a", href=re.compile(r"/cnpj/"))
        
        for link in links_empresas[:max_empresas]:
            href = link.get("href", "")
            cnpj_match = re.search(r"(\d{14})", href)
            
            if cnpj_match:
                cnpj = cnpj_match.group(1)
                nome = link.get_text(strip=True)
                
                if nome and cnpj:
                    empresas.append({
                        "Nome": nome,
                        "CNPJ": cnpj,
                        "Origem": f"CNPJá - CNAE {cnae_code}"
                    })
        
        # Se não encontrou pelo método anterior, tenta extrair de tabelas
        if not empresas:
            tabelas = soup.find_all("table")
            for tabela in tabelas:
                linhas = tabela.find_all("tr")
                for linha in linhas[1:max_empresas]:  # Pula cabeçalho
                    colunas = linha.find_all(["td", "th"])
                    if len(colunas) >= 2:
                        possivel_nome = colunas[0].get_text(strip=True)
                        possivel_cnpj = colunas[1].get_text(strip=True)
                        cnpj_numeros = limpa_cnpj(possivel_cnpj)
                        
                        if len(cnpj_numeros) == 14:
                            empresas.append({
                                "Nome": possivel_nome,
                                "CNPJ": cnpj_numeros,
                                "Origem": f"CNPJá Tabela - CNAE {cnae_code}"
                            })
        
        return empresas
        
    except Exception as e:
        st.warning(f"Erro no scraping CNPJá para CNAE {cnae_code}: {e}")
        return []

@st.cache_data(ttl=60 * 30, show_spinner=False)
def buscar_empresas_consultacnpj_alternativo(cnae_code: str, uf: str, max_empresas: int = 20) -> List[Dict]:
    """Tenta diferentes estruturas de URL no consultacnpj.com."""
    cnae_limpo = re.sub(r'\D', '', cnae_code)
    cnae_desc = CNAES_MINERACAO.get(cnae_code, "mineracao")
    cnae_slug = slug(cnae_desc)
    
    # Múltiplas tentativas de URL
    urls_tentativas = [
        f"https://consultacnpj.com/empresas/{cnae_limpo}/{uf.lower()}",
        f"https://consultacnpj.com/cnae/{cnae_limpo}/{uf.lower()}",
        f"https://consultacnpj.com/busca/{cnae_slug}/{uf.lower()}",
        f"https://consultacnpj.com/{cnae_limpo}",
    ]
    
    for url in urls_tentativas:
        r = http_get(url)
        if r:
            try:
                soup = BeautifulSoup(r.text, "html.parser")
                empresas = []
                
                # Busca por cards de empresa
                cards = soup.select("div.card, div.empresa, div.company-card, .result-item")
                
                for card in cards[:max_empresas]:
                    nome_elem = card.select_one("h3, h4, .nome, .company-name, .title a, a")
                    cnpj_elem = card.select_one(".cnpj, .document, .company-document")
                    
                    if nome_elem:
                        nome = nome_elem.get_text(strip=True)
                        cnpj_texto = cnpj_elem.get_text(strip=True) if cnpj_elem else ""
                        cnpj_nums = limpa_cnpj(cnpj_texto)
                        
                        if nome and len(cnpj_nums) == 14:
                            empresas.append({
                                "Nome": nome,
                                "CNPJ": cnpj_nums,
                                "Origem": f"ConsultaCNPJ - CNAE {cnae_code}"
                            })
                
                if empresas:
                    st.info(f"✅ Sucesso com URL: {url}")
                    return empresas
                    
            except Exception as e:
                continue
    
    return []

def gerar_cnpjs_simulados_mineracao(uf: str, quantidade: int = 10) -> List[Dict]:
    """Gera CNPJs simulados para demonstração (APENAS PARA TESTES)."""
    st.warning("⚠️ Gerando dados simulados para demonstração. Em produção, remova esta função!")
    
    nomes_mineradoras = [
        "Vale Mineração", "Anglo American", "CSN Mineração", "Usiminas Mineração",
        "Samarco Mineração", "Votorantim Metais", "Mineração Usiminas",
        "Brasil Minérios", "Companhia Brasileira de Alumínio", "Mineração Rio do Norte",
        "Alcoa Alumínio", "Hydro Alunorte", "Mineração Paragominas",
        "Anglo Ferrous", "Kinross Brasil Mineração", "AngloGold Ashanti",
        "Yamana Gold", "Equinox Gold", "Jaguar Mining", "Eldorado Gold"
    ]
    
    empresas_simuladas = []
    for i in range(quantidade):
        # Gera CNPJ fictício mas com estrutura válida
        cnpj_base = f"{random.randint(10,99):02d}{random.randint(100,999):03d}{random.randint(100,999):03d}"
        cnpj_full = f"{cnpj_base}0001{random.randint(10,99):02d}"
        
        nome = f"{random.choice(nomes_mineradoras)} {uf} S.A."
        telefone = f"(91) {random.randint(3000,3999)}-{random.randint(1000,9999)}"
        
        empresas_simuladas.append({
            "Nome": nome,
            "CNPJ": cnpj_full,
            "Origem": "SIMULADO - APENAS TESTE"
        })
    
    return empresas_simuladas

# ==============================================
# Interface Principal
# ==============================================

def main():
    st.title(APP_TITLE)
    st.markdown("🎯 **Foco:** Mineradoras e empresas de extração mineral no Pará")
    
    if "resultados_finais" not in st.session_state:
        st.session_state["resultados_finais"] = []
    
    # Sidebar com configurações
    with st.sidebar:
        st.header("⚙️ Configurações")
        
        modo_busca = st.radio(
            "Modo de Busca:",
            ["CNAEs Pré-definidos (Mineração)", "Busca Personalizada", "Teste com Dados Simulados"]
        )
        
        if modo_busca == "Busca Personalizada":
            termo_personalizado = st.text_input("Termo para buscar CNAEs:", value="ferro")
        else:
            termo_personalizado = ""
            
        uf_selecionada = st.selectbox("Estado:", list(UF_NOMES.keys()), index=list(UF_NOMES.keys()).index("PA"))
        max_cnaes = st.slider("Máx. CNAEs:", 1, 15, 5)
        max_empresas_por_cnae = st.slider("Máx. empresas por CNAE:", 5, 50, 15)
        incluir_dados_simulados = st.checkbox("Incluir dados simulados para teste", value=(modo_busca == "Teste com Dados Simulados"))
    
    # Área principal
    st.subheader("🔍 Descoberta de CNAEs")
    
    if modo_busca == "CNAEs Pré-definidos (Mineração)":
        cnaes_usar = encontrar_cnaes_mineracao(termo_personalizado)
        st.info(f"📋 {len(cnaes_usar)} CNAEs de mineração disponíveis")
        
        # Mostra os CNAEs que serão utilizados
        if st.expander("Ver CNAEs de Mineração"):
            for cnae in cnaes_usar[:10]:  # Mostra apenas os primeiros 10
                st.write(f"• **{cnae['codigo']}** - {cnae['descricao']}")
    
    elif modo_busca == "Busca Personalizada":
        url_ibge = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"
        
        @st.cache_data(ttl=60 * 60, show_spinner="Buscando CNAEs no IBGE...")
        def buscar_cnaes_ibge(termo: str):
            r = http_get(url_ibge)
            if not r: return []
            
            try:
                todos_cnaes = r.json()
                encontrados = []
                termo_lower = termo.lower()
                
                for cnae in todos_cnaes:
                    if termo_lower in cnae.get("descricao", "").lower():
                        encontrados.append({
                            "codigo": str(cnae.get("id")),
                            "descricao": cnae.get("descricao")
                        })
                return encontrados
            except Exception as e:
                st.error(f"Erro ao buscar CNAEs: {e}")
                return []
        
        if termo_personalizado:
            cnaes_usar = buscar_cnaes_ibge(termo_personalizado)
            st.success(f"✅ {len(cnaes_usar)} CNAEs encontrados para '{termo_personalizado}'")
        else:
            cnaes_usar = []
            st.info("Digite um termo para buscar CNAEs personalizados.")
    
    else:  # Teste com dados simulados
        cnaes_usar = encontrar_cnaes_mineracao("ferro")
        st.info("🧪 Modo teste ativado - alguns dados serão simulados")

    # Botão de busca principal
    if st.button("🚀 Iniciar Prospecção de Mineradoras", type="primary", disabled=(not cnaes_usar and modo_busca != "Teste com Dados Simulados")):
        st.session_state["resultados_finais"] = []
        
        if modo_busca == "Teste com Dados Simulados":
            st.info("Gerando dados de teste...")
            empresas_teste = gerar_cnpjs_simulados_mineracao(uf_selecionada, 10)
            st.session_state["resultados_finais"] = empresas_teste
            st.success("Dados de teste gerados!")
        else:
            # Busca real
            st.info(f"🔍 Iniciando busca em {len(cnaes_usar[:max_cnaes])} CNAEs no estado: {UF_NOMES[uf_selecionada]}")
            
            todas_empresas = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Etapa 1: Coleta de CNPJs
            for i, cnae in enumerate(cnaes_usar[:max_cnaes]):
                progresso = (i + 1) / len(cnaes_usar[:max_cnaes])
                status_text.text(f"Buscando empresas para CNAE: {cnae['descricao'][:50]}...")
                progress_bar.progress(progresso)
                
                # Tenta múltiplas fontes de scraping
                empresas_cnpja = buscar_empresas_cnpja_scraping(cnae['codigo'], uf_selecionada, max_empresas_por_cnae)
                empresas_consulta = buscar_empresas_consultacnpj_alternativo(cnae['codigo'], uf_selecionada, max_empresas_por_cnae)
                
                todas_empresas.extend(empresas_cnpja)
                todas_empresas.extend(empresas_consulta)
                
                # Adiciona dados simulados se habilitado
                if incluir_dados_simulados:
                    simuladas = gerar_cnpjs_simulados_mineracao(uf_selecionada, 3)
                    todas_empresas.extend(simuladas)
                
                time.sleep(random.uniform(1, 3))  # Pausa para evitar bloqueios
            
            progress_bar.empty()
            status_text.empty()
            
            # Remove duplicatas por CNPJ
            cnpjs_vistos = set()
            empresas_unicas = []
            for emp in todas_empresas:
                cnpj = limpa_cnpj(emp.get("CNPJ", ""))
                if cnpj and cnpj not in cnpjs_vistos:
                    cnpjs_vistos.add(cnpj)
                    empresas_unicas.append(emp)
            
            if not empresas_unicas:
                st.error("❌ Nenhuma empresa encontrada. Tente outros CNAEs ou aguarde alguns minutos.")
                return
            
            st.success(f"✅ {len(empresas_unicas)} empresas únicas encontradas!")
            
            # Etapa 2: Enriquecimento com dados da Receita Federal
            st.info("📊 Enriquecendo dados com informações da Receita Federal...")
            
            progress_bar_enrich = st.progress(0)
            status_enrich = st.empty()
            resultados_enriquecidos = []
            
            for i, empresa in enumerate(empresas_unicas):
                progresso = (i + 1) / len(empresas_unicas)
                status_enrich.text(f"Enriquecendo: {empresa.get('Nome', '')[:40]}...")
                progress_bar_enrich.progress(progresso)
                
                dados_completos = consultar_cnpj_multiplas_fontes(empresa.get("CNPJ", ""))
                
                if dados_completos:
                    # Adiciona informações da origem
                    dados_completos["Origem da Descoberta"] = empresa.get("Origem", "")
                    resultados_enriquecidos.append(dados_completos)
                
                # Pausa para respeitar rate limits
                time.sleep(random.uniform(0.5, 1.5))
            
            progress_bar_enrich.empty()
            status_enrich.empty()
            
            st.session_state["resultados_finais"] = resultados_enriquecidos
            
            if resultados_enriquecidos:
                st.success(f"🎉 Prospecção concluída! {len(resultados_enriquecidos)} empresas com dados completos.")
                st.balloons()
            else:
                st.warning("⚠️ Empresas encontradas, mas falha no enriquecimento de dados.")

    # Exibição dos resultados
    if st.session_state["resultados_finais"]:
        st.header("📋 Resultados da Prospecção")
        
        df_resultados = pd.DataFrame(st.session_state["resultados_finais"])
        
        # Filtros interativos
        col_filtro1, col_filtro2 = st.columns([3, 2])
        
        with col_filtro1:
            termo_filtro = st.text_input("Filtrar por nome, CNPJ ou cidade:", help="Busca em 'Razão Social', 'Nome Fantasia', 'CNPJ' e 'Cidade'")
        
        with col_filtro2:
            # Garante que a coluna 'Cidade' exista e remove valores nulos/vazios para o filtro
            cidades_disponiveis = sorted(df_resultados['Cidade'].dropna().unique()) if 'Cidade' in df_resultados.columns else []
            cidade_selecionada = st.multiselect("Filtrar por Cidade:", cidades_disponiveis)

        # Aplica os filtros
        df_filtrado = df_resultados.copy()
        if termo_filtro:
            termo_lower = termo_filtro.lower()
            df_filtrado = df_filtrado[
                df_filtrado['Razão Social'].str.lower().str.contains(termo_lower, na=False) |
                df_filtrado['Nome Fantasia'].str.lower().str.contains(termo_lower, na=False) |
                df_filtrado['CNPJ'].str.contains(limpa_cnpj(termo_lower), na=False) |
                df_filtrado['Cidade'].str.lower().str.contains(termo_lower, na=False)
            ]
        
        if cidade_selecionada:
            df_filtrado = df_filtrado[df_filtrado['Cidade'].isin(cidade_selecionada)]

        st.metric("Empresas Encontradas (após filtros)", len(df_filtrado))
        st.dataframe(df_filtrado, use_container_width=True)
        
        # Prepara o arquivo Excel para download
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_filtrado.to_excel(writer, index=False, sheet_name='Prospects')
        excel_data = output.getvalue()
        
        st.download_button(
            label="📥 Baixar resultados filtrados em Excel (.xlsx)",
            data=excel_data,
            file_name=f"prospects_mineradoras_{uf_selecionada.lower()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


if __name__ == "__main__":
    main()
