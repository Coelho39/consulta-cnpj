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

APP_TITLE = "🏢 Prospectador B2B – Prospecção Ativa (v7.3 - IBGE)"

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

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

@st.cache_data(ttl=60 * 30)
def http_get(url: str, timeout: int = 30, headers: dict | None = None) -> requests.Response | None:
    try:
        h = {"User-Agent": DEFAULT_UA}
        if headers:
            h.update(headers)
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.RequestException as e:
        st.warning(f"Não foi possível acessar {url}. O site pode estar offline ou bloqueando o acesso. Erro: {e}")
        return None

# ==============================================
# Funções de Enriquecimento
# ==============================================

@st.cache_data(ttl=60 * 60)
def buscar_dados_receita_federal(cnpj: str) -> dict:
    c = limpa_cnpj(cnpj)
    if len(c) != 14:
        return {}

    url = f"https://brasilapi.com.br/api/cnpj/v1/{c}"
    r = http_get(url, timeout=20)
    if not r:
        return {}
    try:
        data = r.json()
        if data.get("cnpj"):
            return {
                "Nome": data.get("razao_social"),
                "Nome Fantasia": data.get("nome_fantasia"),
                "CNPJ": data.get("cnpj"),
                "Situação Cadastral": data.get("descricao_situacao_cadastral"),
                "CNAE Principal": data.get("cnae_fiscal"),
                "Endereço": f"{data.get('logradouro', '')}, {data.get('numero', '')} - {data.get('bairro', '')}, {data.get('municipio', '')} - {data.get('uf', '')}",
                "Telefone": data.get("ddd_telefone_1"),
            }
    except Exception:
        return {}
    return {}

@st.cache_data(ttl=60 * 60)
def buscar_emails_site(website: str, timeout: int = 12) -> list[str]:
    if not website or not isinstance(website, str) or not website.startswith("http"):
        return []
    r = http_get(website, timeout=timeout)
    if not r:
        return []

    emails = set()
    email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    emails.update(e.lower() for e in email_pattern.findall(r.text))

    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("mailto:"):
                emails.add(href.replace("mailto:", "").lower())
    except Exception:
        pass

    return sorted({e for e in emails if not re.search(r"\.(png|jpg|jpeg|gif|svg)$", e)})

# ==============================================
# Funções para a Prospecção Ativa (Rota 2)
# ==============================================

@st.cache_data(ttl=60 * 60)
def encontrar_cnaes_por_descricao(descricao: str) -> list[dict]:
    """Encontra todos os CNAEs que correspondem a uma descrição de atividade usando a API do IBGE."""
    if not descricao:
        return []
    
    # MUDANÇA: Usando a API oficial e estável do IBGE
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
                # Adapta a saída para o formato que o resto do programa espera
                cnaes_encontrados.append({
                    "codigo": str(cnae.get("id")),
                    "descricao": cnae.get("descricao")
                })
        return cnaes_encontrados
    except Exception as e:
        st.error(f"Erro ao processar lista de CNAEs do IBGE: {e}")
        return []

@st.cache_data(ttl=60 * 10)
def raspar_cnpjs_por_cnae(cnae_code: str, uf: str, max_por_cnae: int) -> list[dict]:
    """Faz web scraping no site cnpj.biz para encontrar empresas por CNAE e UF."""
    cnae_limpo = re.sub(r'\D', '', cnae_code)
    url = f"https://cnpj.biz/cnae/{cnae_limpo}/uf/{uf.lower()}"
    
    r = http_get(url)
    if not r:
        return []
        
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        empresas = []
        cards = soup.select("div.row > div[style*='padding: 20px']")
        
        for card in cards:
            if len(empresas) >= max_por_cnae:
                break
            
            nome_tag = card.select_one("a")
            cnpj_tag = card.find('b', text=re.compile(r'^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$'))

            if nome_tag and cnpj_tag:
                nome = nome_tag.get_text(strip=True)
                cnpj = cnpj_tag.get_text(strip=True)
                empresas.append({
                    "Nome": nome,
                    "CNPJ": cnpj,
                    "Origem": f"Scraping CNAE {cnae_code}"
                })
        
        return empresas
    except Exception as e:
        st.warning(f"Erro ao raspar dados para o CNAE {cnae_code}: {e}")
        return []

# ==============================================
# Orquestração Principal
# ==============================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🏢", layout="wide")
    st.title(APP_TITLE)
    st.markdown("Uma ferramenta para descobrir e enriquecer contatos de empresas (B2B).")

    metodo = st.selectbox(
        "Selecione o modo de operação",
        (
            "---",
            "Rota 1 – Descobrir (Busca Google/SerpAPI)",
            "Rota 2 – Prospecção Ativa por Atividade (CNAE)",
            "Rota 3 – Enriquecer Lista de CNPJs",
            "Rota 4 – Enriquecer Arquivo CSV",
        ),
    )

    if metodo == "Rota 2 – Prospecção Ativa por Atividade (CNAE)":
        st.subheader("🔎 Prospecção por Atividade Empresarial")
        col1, col2 = st.columns(2)
        with col1:
            atividade = st.text_input("Digite a atividade (ex: extração de minério de ferro, fabricação de calçados)", value="extração de minério de ferro")
        with col2:
            uf = st.selectbox("Selecione o Estado (UF)", list(UF_NOMES.keys()), index=list(UF_NOMES.keys()).index("PA"))
        
        max_cnaes = st.slider("Máximo de CNAEs a serem investigados", 1, 10, 3)
        max_empresas_por_cnae = st.slider("Máximo de empresas a buscar por CNAE", 5, 50, 10)

        if st.button("🚀 Iniciar Prospecção Ativa", type="primary"):
            with st.spinner("Passo 1: Encontrando CNAEs relacionados na base do IBGE..."):
                cnaes_encontrados = encontrar_cnaes_por_descricao(atividade)
            
            if not cnaes_encontrados:
                st.error(f"Nenhum CNAE encontrado para a atividade '{atividade}'. Tente um termo diferente.")
                return

            st.success(f"Encontramos {len(cnaes_encontrados)} CNAEs. Vamos investigar os {max_cnaes} primeiros.")
            st.expander("Ver CNAEs encontrados").write(cnaes_encontrados)

            todos_registros = []
            pb = st.progress(0, "Passo 2: Buscando empresas para cada CNAE...")
            
            for i, cnae in enumerate(cnaes_encontrados[:max_cnaes]):
                cnae_cod = cnae['codigo']
                cnae_desc = cnae['descricao']
                pb.progress((i + 1) / max_cnaes, f"Buscando em '{cnae_desc[:50]}...'")
                
                with st.spinner(f"Buscando empresas para o CNAE {cnae_cod}..."):
                    registros_cnae = raspar_cnpjs_por_cnae(cnae_cod, uf, max_empresas_por_cnae)
                    todos_registros.extend(registros_cnae)
                    time.sleep(random.uniform(1, 2)) # Pausa para não sobrecarregar o site

            pb.empty()

            if not todos_registros:
                st.warning("A busca por empresas não retornou resultados. O site de consulta pode estar bloqueando o acesso ou não há empresas listadas para os critérios.")
                return
            
            st.info(f"Busca inicial concluída. {len(todos_registros)} empresas encontradas. Iniciando enriquecimento...")

            registros_finais = []
            pb_enriquecimento = st.progress(0, "Passo 3: Enriquecendo dados...")
            for i, reg in enumerate(todos_registros):
                pb_enriquecimento.progress((i + 1) / len(todos_registros), f"Enriquecendo {reg.get('Nome')[:40]}...")
                dados_ricos = buscar_dados_receita_federal(reg.get("CNPJ"))
                if dados_ricos:
                    website_slug = slug(dados_ricos.get('Nome Fantasia') or dados_ricos.get('Nome'))
                    emails = buscar_emails_site(f"http://www.{website_slug}.com.br")
                    dados_ricos["Emails do Site"] = ", ".join(emails) if emails else None
                    registros_finais.append(dados_ricos)

            pb_enriquecimento.empty()
            st.session_state["resultados"] = registros_finais
            st.success("Prospecção e enriquecimento concluídos!")
            st.dataframe(pd.DataFrame(registros_finais))

    if "resultados" in st.session_state and st.session_state["resultados"]:
        st.header("📊 Resultados")
        df_final = pd.DataFrame(st.session_state.get("resultados", []))
        st.dataframe(df_final)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_final.to_excel(writer, index=False, sheet_name='Prospects')
        excel_data = output.getvalue()
        
        st.download_button(
            label="📥 Baixar resultados em Excel (.xlsx)",
            data=excel_data,
            file_name=f"prospects_{slug(metodo if metodo != '---' else 'resultados')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# O ponto de entrada do script
if __name__ == "__main__":
    main()
