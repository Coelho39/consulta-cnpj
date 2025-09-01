import os
import io
import re
import time
import json
import random
import unicodedata
from urllib.parse import quote

import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

# ==============================================
# Configurações e Utilidades
# ==============================================

APP_TITLE = "🏢 Prospectador B2B – Prospecção Ativa (v8.1 - UI Integrada)"

# Configuração da página do Streamlit
st.set_page_config(page_title=APP_TITLE, page_icon="🏢", layout="wide")

UF_NOMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins"
}

def slug(s: str) -> str:
    """Converte uma string para um formato 'slug' amigável para URLs."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def limpa_cnpj(cnpj: str) -> str:
    """Remove caracteres não numéricos de um CNPJ."""
    return re.sub(r"\D", "", str(cnpj or ""))

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

# Usando o cache do Streamlit para otimizar requisições repetidas
@st.cache_data(ttl=60 * 30, show_spinner=False) # Cache de 30 minutos
def http_get(url: str, timeout: int = 45, headers: dict | None = None ) -> requests.Response | None:
    """Realiza uma requisição HTTP GET com tratamento de erros e feedback no Streamlit."""
    try:
        h = headers if headers else {"User-Agent": DEFAULT_UA}
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.RequestException as e:
        # Usamos st.warning para notificar o usuário na interface
        st.warning(f"Não foi possível acessar {url}. O site pode estar offline ou bloqueando o acesso. Erro: {e}")
        return None

# ==============================================
# Funções de Enriquecimento e Prospecção
# ==============================================

@st.cache_data(ttl=60 * 60, show_spinner=False) # Cache de 1 hora
def buscar_dados_receita_federal(cnpj: str) -> dict:
    """Busca dados de um CNPJ na BrasilAPI para enriquecimento."""
    c = limpa_cnpj(cnpj)
    if len(c) != 14: return {}
    url = f"https://brasilapi.com.br/api/cnpj/v1/{c}"
    r = http_get(url, timeout=20 )
    if not r: return {}
    try:
        data = r.json()
        if data.get("cnpj"):
            return {
                "Nome": data.get("razao_social"), "Nome Fantasia": data.get("nome_fantasia"),
                "CNPJ": data.get("cnpj"), "Situação Cadastral": data.get("descricao_situacao_cadastral"),
                "CNAE Principal": f"{data.get('cnae_fiscal')} - {data.get('cnae_fiscal_descricao')}",
                "Endereço": f"{data.get('logradouro', '')}, {data.get('numero', '')} - {data.get('bairro', '')}, {data.get('municipio', '')} - {data.get('uf', '')}",
                "Telefone": f"({data.get('ddd_telefone_1')})",
                "Email": data.get("email"),
            }
    except (json.JSONDecodeError, Exception):
        return {}
    return {}

@st.cache_data(ttl=60 * 60, show_spinner="Buscando CNAEs no IBGE...") # Cache de 1 hora
def encontrar_cnaes_por_descricao(descricao: str) -> list[dict]:
    """Encontra códigos e descrições de CNAE a partir de uma palavra-chave no IBGE."""
    if not descricao: return []
    url = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"
    r = http_get(url )
    if not r:
        st.error("Não foi possível acessar a lista de CNAEs do IBGE.")
        return []
    try:
        todos_cnaes = r.json()
        cnaes_encontrados = []
        termo_busca = descricao.lower()
        for cnae in todos_cnaes:
            if termo_busca in cnae.get("descricao", "").lower():
                cnaes_encontrados.append({"codigo": str(cnae.get("id")), "descricao": cnae.get("descricao")})
        return cnaes_encontrados
    except (json.JSONDecodeError, Exception) as e:
        st.error(f"Erro ao processar lista de CNAEs do IBGE: {e}")
        return []

# --- FUNÇÃO DE SCRAPING CORRIGIDA E INTEGRADA AO STREAMLIT ---
@st.cache_data(ttl=60 * 10, show_spinner=False) # Cache de 10 minutos para dados mais recentes
def raspar_cnpjs_consultacnpj(cnae_code: str, cnae_desc: str, uf: str, max_por_cnae: int) -> list[dict]:
    """Faz web scraping no site consultacnpj.com usando a estrutura de URL corrigida."""
    cnae_limpo = re.sub(r'\D', '', cnae_code)
    cnae_slug = slug(cnae_desc)
    
    url = f"https://consultacnpj.com/cnae/{cnae_slug}-cnae-{cnae_limpo}/{uf.lower( )}"
    st.info(f"Acessando: {url}") # Mostra a URL na interface para depuração

    headers = {
        'User-Agent': DEFAULT_UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Referer': 'https://www.google.com/'
    }
    
    r = http_get(url, headers=headers )
    if not r: return []
        
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        empresas = []
        cards = soup.select("div.card.company-card")
        
        if not cards:
            st.warning(f"Nenhum card de empresa encontrado na página para o CNAE {cnae_code} em {uf}.")
            return []

        for card in cards:
            if len(empresas) >= max_por_cnae: break
            
            nome_tag = card.select_one(".card-title a")
            cnpj_tag = card.select_one(".company-document")

            if nome_tag and cnpj_tag:
                empresas.append({
                    "Nome": nome_tag.get_text(strip=True),
                    "CNPJ": cnpj_tag.get_text(strip=True),
                    "Origem": f"Scraping CNAE {cnae_code}"
                })
        return empresas
    except Exception as e:
        st.warning(f"Erro ao raspar dados para o CNAE {cnae_code}: {e}")
        return []

# ==============================================
# Orquestração Principal (Interface Streamlit)
# ==============================================

def main():
    st.title(APP_TITLE)

    # Usamos st.session_state para manter os resultados entre interações
    if "resultados" not in st.session_state:
        st.session_state["resultados"] = []

    st.subheader("🔎 Prospecção por Atividade Empresarial (CNAE)")
    st.markdown("Esta ferramenta busca CNAEs no IBGE e depois raspa dados do site `consultacnpj.com` para encontrar empresas.")
    
    col1, col2 = st.columns(2)
    with col1:
        atividade = st.text_input("Digite a atividade", value="extração de minério de ferro")
    with col2:
        # Encontra o índice do Pará para deixar como padrão
        default_uf_index = list(UF_NOMES.keys()).index("PA")
        uf = st.selectbox("Selecione o Estado (UF)", list(UF_NOMES.keys()), index=default_uf_index)
    
    max_cnaes = st.slider("Máximo de CNAEs a investigar", 1, 10, 3)
    max_empresas_por_cnae = st.slider("Máximo de empresas por CNAE", 5, 50, 10)

    if st.button("🚀 Iniciar Prospecção Ativa", type="primary"):
        # Limpa resultados anteriores antes de uma nova busca
        st.session_state["resultados"] = []
        
        cnaes_encontrados = encontrar_cnaes_por_descricao(atividade)
        if not cnaes_encontrados:
            st.error(f"Nenhum CNAE encontrado para '{atividade}'. Tente um termo diferente.")
            return

        st.success(f"Encontramos {len(cnaes_encontrados)} CNAEs. Investigando os {max_cnaes} primeiros.")
        todos_registros = []
        
        # Barra de progresso para a busca inicial
        pb_busca = st.progress(0, "Passo 1/2: Buscando empresas...")
        
        for i, cnae in enumerate(cnaes_encontrados[:max_cnaes]):
            cnae_cod, cnae_desc = cnae['codigo'], cnae['descricao']
            
            # Atualiza o texto da barra de progresso
            progresso_atual = (i + 1) / max_cnaes
            pb_busca.progress(progresso_atual, f"Buscando em '{cnae_desc[:50]}...' ({i+1}/{max_cnaes})")
            
            registros_cnae = raspar_cnpjs_consultacnpj(cnae_cod, cnae_desc, uf, max_empresas_por_cnae)
            todos_registros.extend(registros_cnae)
            time.sleep(random.uniform(1, 2)) # Pausa para não sobrecarregar o site

        pb_busca.empty() # Remove a barra de progresso
        if not todos_registros:
            st.warning("A busca por empresas não retornou resultados. O site pode estar bloqueando o acesso ou não há empresas listadas para os critérios.")
            return
        
        st.info(f"Busca inicial concluída. {len(todos_registros)} empresas encontradas. Agora, enriquecendo os dados...")
        registros_finais = []
        
        # Barra de progresso para o enriquecimento
        pb_enriquecimento = st.progress(0, "Passo 2/2: Enriquecendo dados...")
        
        for i, reg in enumerate(todos_registros):
            progresso_atual = (i + 1) / len(todos_registros)
            pb_enriquecimento.progress(progresso_atual, f"Enriquecendo {reg.get('Nome')[:40]}... ({i+1}/{len(todos_registros)})")
            
            dados_ricos = buscar_dados_receita_federal(reg.get("CNPJ"))
            if dados_ricos:
                registros_finais.append(dados_ricos)
            time.sleep(0.3) # Pausa leve para não sobrecarregar a API

        pb_enriquecimento.empty()
        st.session_state["resultados"] = registros_finais
        st.success("Prospecção e enriquecimento concluídos!")
        st.balloons() # Comemoração!

    # Exibe os resultados se eles existirem no estado da sessão
    if st.session_state["resultados"]:
        st.header("📊 Resultados da Prospecção")
        df_final = pd.DataFrame(st.session_state["resultados"])
        
        # Mostra o DataFrame na tela
        st.dataframe(df_final, use_container_width=True)
        
        # Prepara o arquivo Excel para download
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_final.to_excel(writer, index=False, sheet_name='Prospects')
        excel_data = output.getvalue()
        
        st.download_button(
            label="📥 Baixar resultados em Excel (.xlsx)",
            data=excel_data,
            file_name=f"prospects_{slug(atividade)}_{uf.lower()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

if __name__ == "__main__":
    main()
