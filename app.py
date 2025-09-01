import os
import io
import re
import time
import json
import random
import unicodedata
from urllib.parse import urljoin, quote

import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

# ==============================================
# Utilidades
# ==============================================

APP_TITLE = "🏢 Prospectador B2B – Prospecção Ativa (v7.4 - Anti-Bloqueio)"

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
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def limpa_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", str(cnpj or ""))

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"

# ATUALIZAÇÃO: Função http_get agora aceita proxies
@st.cache_data(ttl=60 * 30)
def http_get(url: str, timeout: int = 30, headers: dict | None = None, proxy: str | None = None) -> requests.Response | None:
    try:
        proxies = None
        if proxy:
            proxies = {"http": proxy, "https": proxy}
        
        h = headers if headers else {"User-Agent": DEFAULT_UA}
        
        r = requests.get(url, headers=h, timeout=timeout, proxies=proxies)
        r.raise_for_status()
        return r
    except requests.exceptions.RequestException as e:
        st.warning(f"Não foi possível acessar {url}. O site pode estar offline ou bloqueando o acesso. Erro: {e}")
        return None

# ==============================================
# Funções de Enriquecimento (buscar_dados_receita_federal, etc.)
# ==============================================
# (Estas funções não precisam de mudança, mas são incluídas para o código completo)
@st.cache_data(ttl=60 * 60)
def buscar_dados_receita_federal(cnpj: str) -> dict:
    c = limpa_cnpj(cnpj)
    if len(c) != 14: return {}
    url = f"https://brasilapi.com.br/api/cnpj/v1/{c}"
    r = http_get(url, timeout=20)
    if not r: return {}
    try:
        data = r.json()
        if data.get("cnpj"):
            return {
                "Nome": data.get("razao_social"), "Nome Fantasia": data.get("nome_fantasia"),
                "CNPJ": data.get("cnpj"), "Situação Cadastral": data.get("descricao_situacao_cadastral"),
                "CNAE Principal": data.get("cnae_fiscal"),
                "Endereço": f"{data.get('logradouro', '')}, {data.get('numero', '')} - {data.get('bairro', '')}, {data.get('municipio', '')} - {data.get('uf', '')}",
                "Telefone": data.get("ddd_telefone_1"),
            }
    except Exception: return {}
    return {}

# ==============================================
# Funções para a Prospecção Ativa (Rota 2)
# ==============================================

@st.cache_data(ttl=60 * 60)
def encontrar_cnaes_por_descricao(descricao: str) -> list[dict]:
    if not descricao: return []
    url = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"
    r = http_get(url)
    if not r:
        st.error("Não foi possível acessar a lista de CNAEs do IBGE.")
        return []
    try:
        todos_cnaes = r.json()
        cnaes_encontrados = []
        for cnae in todos_cnaes:
            if descricao.lower() in cnae.get("descricao", "").lower():
                cnaes_encontrados.append({"codigo": str(cnae.get("id")), "descricao": cnae.get("descricao")})
        return cnaes_encontrados
    except Exception as e:
        st.error(f"Erro ao processar lista de CNAEs do IBGE: {e}")
        return []

# ATUALIZAÇÃO: Função de scraping agora usa mais headers e aceita proxy
@st.cache_data(ttl=60 * 10)
def raspar_cnpjs_por_cnae(cnae_code: str, uf: str, max_por_cnae: int, proxy: str | None) -> list[dict]:
    cnae_limpo = re.sub(r'\D', '', cnae_code)
    url = f"https://cnpj.biz/cnae/{cnae_limpo}/uf/{uf.lower()}"
    
    # Headers mais realistas para simular um navegador
    headers = {
        'User-Agent': DEFAULT_UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.google.com/'
    }
    
    r = http_get(url, headers=headers, proxy=proxy) # Passa o proxy para a função http_get
    if not r: return []
        
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        empresas = []
        cards = soup.select("div.row > div[style*='padding: 20px']")
        
        for card in cards:
            if len(empresas) >= max_por_cnae: break
            nome_tag = card.select_one("a")
            cnpj_tag = card.find('b', text=re.compile(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$'))
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
# Orquestração Principal (Interface)
# ==============================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🏢", layout="wide")
    st.title(APP_TITLE)

    metodo = st.selectbox(
        "Selecione o modo de operação",
        ("---", "Rota 2 – Prospecção Ativa por Atividade (CNAE)",) # Simplificado para focar na rota principal
    )

    if metodo == "Rota 2 – Prospecção Ativa por Atividade (CNAE)":
        st.subheader("🔎 Prospecção por Atividade Empresarial")
        st.markdown("Esta ferramenta busca CNAEs no IBGE e depois raspa dados do site `cnpj.biz` para encontrar empresas.")
        
        col1, col2 = st.columns(2)
        with col1:
            atividade = st.text_input("Digite a atividade", value="extração de minério de ferro")
            uf = st.selectbox("Selecione o Estado (UF)", list(UF_NOMES.keys()), index=list(UF_NOMES.keys()).index("PA"))
        with col2:
            max_cnaes = st.slider("Máximo de CNAEs a investigar", 1, 10, 3)
            max_empresas_por_cnae = st.slider("Máximo de empresas por CNAE", 5, 50, 10)

        with st.expander("⚙️ Configurações Avançadas (Anti-Bloqueio)"):
            proxy = st.text_input("Endereço do Proxy (opcional)", placeholder="http://usuario:senha@host:porta")
            st.caption("Use se o acesso estiver sendo bloqueado (erro 403). Requer um serviço de proxy pago.")

        if st.button("🚀 Iniciar Prospecção Ativa", type="primary"):
            # ... (Lógica da prospecção permanece a mesma, apenas passando o proxy)
            cnaes_encontrados = encontrar_cnaes_por_descricao(atividade)
            if not cnaes_encontrados:
                st.error(f"Nenhum CNAE encontrado para '{atividade}'.")
                return

            st.success(f"Encontramos {len(cnaes_encontrados)} CNAEs. Investigando os {max_cnaes} primeiros.")
            todos_registros = []
            pb = st.progress(0, "Passo 2: Buscando empresas...")
            
            for i, cnae in enumerate(cnaes_encontrados[:max_cnaes]):
                cnae_cod, cnae_desc = cnae['codigo'], cnae['descricao']
                pb.progress((i + 1) / max_cnaes, f"Buscando em '{cnae_desc[:50]}...'")
                # Passando o proxy para a função de scraping
                registros_cnae = raspar_cnpjs_por_cnae(cnae_cod, uf, max_empresas_por_cnae, proxy)
                todos_registros.extend(registros_cnae)
                time.sleep(random.uniform(1.5, 3)) # Aumentar a pausa

            pb.empty()
            if not todos_registros:
                st.warning("A busca por empresas não retornou resultados.")
                return
            
            st.info(f"Busca inicial concluída. {len(todos_registros)} empresas encontradas. Enriquecendo...")
            registros_finais = []
            pb_enriquecimento = st.progress(0, "Passo 3: Enriquecendo dados...")
            
            for i, reg in enumerate(todos_registros):
                pb_enriquecimento.progress((i + 1) / len(todos_registros), f"Enriquecendo {reg.get('Nome')[:40]}...")
                dados_ricos = buscar_dados_receita_federal(reg.get("CNPJ"))
                if dados_ricos: registros_finais.append(dados_ricos)

            pb_enriquecimento.empty()
            st.session_state["resultados"] = registros_finais
            st.success("Prospecção e enriquecimento concluídos!")

    if "resultados" in st.session_state and st.session_state["resultados"]:
        st.header("📊 Resultados")
        df_final = pd.DataFrame(st.session_state.get("resultados", []))
        st.dataframe(df_final)
        # ... (Lógica de download permanece a mesma)

if __name__ == "__main__":
    main()
