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

APP_TITLE = "🏢 Prospectador B2B – Extração e Enriquecimento (v6)"

UF_NOMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins"
}

DDD_PA = {"91", "93", "94"}

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def limpa_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


@st.cache_data(ttl=60 * 30)
def http_get(url: str, timeout: int = 25, headers: dict | None = None) -> requests.Response | None:
    try:
        h = {"User-Agent": DEFAULT_UA}
        if headers:
            h.update(headers)
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.HTTPError as e:
        # Apenas para 404, não mostramos erro, só retornamos None
        if e.response.status_code != 404:
            st.warning(f"Erro de conexão: {e}")
        return None
    except Exception as e:
        st.warning(f"Erro inesperado de conexão: {e}")
        return None


# ==============================================
# Enriquecimento (baixo custo): BrasilAPI
# ==============================================

@st.cache_data(ttl=60 * 60)
def buscar_dados_receita_federal(cnpj: str) -> dict:
    c = limpa_cnpj(cnpj)
    if len(c) != 14:
        return {}

    # Usando apenas a BrasilAPI por ser mais estável
    url = f"https://brasilapi.com.br/api/cnpj/v1/{c}"
    r = http_get(url, timeout=20)
    if not r:
        return {}
    try:
        data = r.json()
        if "cnpj" in data:
            return {
                "Nome": data.get("razao_social"),
                "Nome Fantasia": data.get("nome_fantasia"),
                "CNPJ": data.get("cnpj"),
                "Situação Cadastral": data.get("descricao_situacao_cadastral"),
                "CNAE Principal": str(data.get("cnae_fiscal")),
                "Endereço": f"{data.get('logradouro', '')}, {data.get('numero', '')} - {data.get('bairro', '')}, {data.get('municipio', '')} - {data.get('uf', '')}",
                "Telefone": data.get("ddd_telefone_1"),
            }
    except Exception:
        return {}
    return {}


@st.cache_data(ttl=60 * 60)
def buscar_emails_site(website: str, timeout: int = 12) -> list[str]:
    # (Função mantida como estava, sem alterações)
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


@st.cache_data(ttl=60 * 60)
def buscar_redes_sociais(website: str) -> dict:
    # (Função mantida como estava, sem alterações)
    redes = {"Facebook": None, "Instagram": None, "LinkedIn": None}
    if not website or not website.startswith("http"):
        return redes
    r = http_get(website, timeout=12)
    if not r:
        return redes
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if not redes["Facebook"] and "facebook.com" in href:
                redes["Facebook"] = a["href"]
            elif not redes["Instagram"] and "instagram.com" in href:
                redes["Instagram"] = a["href"]
            elif not redes["LinkedIn"] and "linkedin.com" in href:
                redes["LinkedIn"] = a["href"]
    except Exception:
        pass
    return redes


# ==============================================
# Métodos de EXTRAÇÃO
# ==============================================

@st.cache_data(ttl=60 * 10)
def serpapi_google_maps(query: str, location: str, api_key: str, num_results: int = 50) -> list[dict]:
    # (Função mantida como estava, sem alterações)
    if not api_key:
        st.error("Por favor, insira uma chave de API da SerpAPI.")
        return []
    url = "https://serpapi.com/search"
    params = {
        "engine": "google_maps",
        "q": f"{query} {location}",
        "hl": "pt",
        "gl": "br",
        "api_key": api_key,
        "num": min(int(num_results), 100),
    }
    r = http_get(url, timeout=30)
    if not r: return []
    try:
        data = r.json()
        if "error" in data:
            st.error(f"Erro SerpAPI: {data['error']}")
            return []
        out = []
        for p in data.get("local_results", []) or []:
            out.append(
                {
                    "Nome": p.get("title"), "Endereço": p.get("address"),
                    "Telefone": p.get("phone"), "Website": p.get("website"),
                    "Rating": p.get("rating"), "Avaliações": p.get("reviews"),
                    "Origem": "SerpAPI",
                }
            )
        return out
    except Exception as e:
        st.error(f"Erro ao processar dados da SerpAPI: {e}")
        return []


# NOVA E ROBUSTA VERSÃO DA FUNÇÃO PARA A ROTA 2
@st.cache_data(ttl=60 * 30)
def buscar_cnpjs_google(termo_busca: str, max_empresas: int) -> list[dict]:
    """Busca por um termo no Google, extrai CNPJs dos resultados e enriquece com a BrasilAPI."""
    if not termo_busca:
        return []

    st.info(f"Buscando no Google por: '{termo_busca}'...")
    url_encoded_term = quote(termo_busca)
    url = f"https://www.google.com/search?q={url_encoded_term}&num=20"
    
    r = http_get(url)
    if not r:
        st.error("Falha ao conectar com o Google. O Google pode ter bloqueado a requisição.")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    texto_pagina = soup.get_text()
    
    # Padrão de regex para encontrar CNPJs no texto da página
    cnpj_pattern = re.compile(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}')
    cnpjs_encontrados = set(cnpj_pattern.findall(texto_pagina))

    if not cnpjs_encontrados:
        st.warning("Nenhum CNPJ encontrado nos resultados da busca do Google.")
        return []

    st.info(f"{len(cnpjs_encontrados)} CNPJs únicos encontrados. Buscando dados...")
    
    resultados = []
    for cnpj in list(cnpjs_encontrados)[:max_empresas]:
        dados_empresa = buscar_dados_receita_federal(cnpj)
        if dados_empresa:
            dados_empresa["Origem"] = "Google + BrasilAPI"
            resultados.append(dados_empresa)
        time.sleep(0.5) # Pausa para não sobrecarregar a API

    return resultados


# ==============================================
# Orquestração de ENRIQUECIMENTO (Simplificada)
# ==============================================

def enriquecer_empresas(empresas: list[dict], *, buscar_redes: bool, buscar_emails: bool) -> list[dict]:
    # (Função mantida, porém o enriquecimento principal já acontece na busca da Rota 2)
    # ...
    # (O restante da função continua igual)
    out = []
    total = len(empresas)
    if total == 0: return []
    
    pb = st.progress(0.0, text="Iniciando enriquecimento...")
    msg = st.empty()

    for i, emp in enumerate(empresas, start=1):
        msg.write(f"Enriquecendo: {emp.get('Nome') or emp.get('CNPJ') or 'registro'} ({i}/{total})")
        row = dict(emp)

        if (buscar_emails or buscar_redes) and not row.get("Website"):
            # Tenta buscar o site se não houver
            try:
                from googlesearch import search
                query = f"{row.get('Nome')} {row.get('Endereço')}"
                for j in search(query, num=1, stop=1, pause=2):
                    row["Website"] = j
                    break
            except Exception:
                pass # Ignora se a busca falhar

        if buscar_emails and row.get("Website"):
            emails = buscar_emails_site(row["Website"]) or []
            row["Emails do Site"] = ", ".join(emails) if emails else None

        if buscar_redes and row.get("Website"):
            row.update(buscar_redes_sociais(row["Website"]))

        out.append(row)
        pb.progress(i / total, text=f"Processando {i}/{total}...")
        time.sleep(random.uniform(0.1, 0.25))

    pb.empty(); msg.empty()
    return out


# ==============================================
# Interface Streamlit
# ==============================================

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🏢", layout="wide")
    st.title(APP_TITLE)

    tab_busca, tab_refino, tab_result = st.tabs(["🔎 Busca", "🧹 Filtro", "📊 Resultados"])

    with tab_busca:
        metodo = st.selectbox(
            "Método de aquisição",
            (
                "Rota 1 – SerpAPI Google Maps (Alta Performance)",
                "Rota 2 – Busca Google + CNPJ (Gratuita, Melhor Esforço)",
                "Rota 3 – Importar CSV",
            ),
        )

        col = st.columns(3)
        termo_busca = "prospects"
        
        if metodo.startswith("Rota 1"):
            with col[0]:
                nicho = st.text_input("🎯 Nicho / Palavra-chave", value="mineradora")
                termo_busca = nicho
            with col[1]:
                local = st.text_input("📍 Localização", value="Pará, Brasil")
            with col[2]:
                serp_key = st.text_input("🔑 SerpAPI Key", type="password")
            max_r = st.slider("Qtd máx. resultados", 10, 100, 40, 10)

        elif metodo.startswith("Rota 2"):
            with col[0]:
                termo = st.text_input("🔎 Termo de Busca", value="empresas de extração de minério de ferro em Minas Gerais")
                termo_busca = termo
            with col[1]:
                max_r = st.slider("Qtd máx. de empresas a buscar", 5, 50, 15, 5)
            with col[2]:
                st.write(" ") # Espaçamento
                st.info("Esta rota busca CNPJs no Google e valida os dados. Pode ser instável.")

        else: # Rota 3
            up = st.file_uploader("Envie um CSV com CNPJ, Nome, Website", type=["csv"])
            df_import = None
            if up is not None:
                try: df_import = pd.read_csv(up)
                except Exception:
                    try: df_import = pd.read_csv(up, sep=";")
                    except Exception: st.error("Não foi possível ler o CSV.")
            max_r = st.slider("Qtd máx. linhas", 10, 2000, 200, 10)
            termo_busca = "importado"

        st.markdown("---")
        # Para Rota 2, o enriquecimento principal já foi feito. Estas opções são para dados adicionais.
        st.write("**Opções de Enriquecimento Adicional:**")
        use_emails = st.checkbox("Buscar e-mails no site (Processo Lento)", value=False)
        use_social = st.checkbox("Localizar redes sociais no site (Processo Lento)", value=False)

        if st.button("🚀 Executar Busca", type="primary"):
            registros: list[dict] = []
            with st.spinner("Buscando…"):
                if metodo.startswith("Rota 1"):
                    registros = serpapi_google_maps(nicho, local, serp_key, num_results=max_r)
                elif metodo.startswith("Rota 2"):
                    registros = buscar_cnpjs_google(termo, max_empresas=max_r)
                else: # Rota 3
                    if df_import is not None and len(df_import) > 0:
                        tmp = df_import.head(max_r).to_dict(orient="records")
                        for r in tmp:
                            r.setdefault("Nome", r.get("nome") or r.get("Razao Social"))
                            r.setdefault("CNPJ", r.get("cnpj") or r.get("CNPJ (Receita)"))
                            r.setdefault("Website", r.get("website") or r.get("site"))
                            r.setdefault("Origem", "CSV")
                        registros = tmp
                    else:
                        st.warning("Envie um CSV válido.")

            if registros:
                st.session_state["termo_busca"] = termo_busca
                if use_emails or use_social:
                     with st.spinner("Enriquecendo com dados de sites... (pode demorar)"):
                        registros = enriquecer_empresas(
                            registros,
                            buscar_redes=use_social,
                            buscar_emails=use_emails,
                        )
                st.session_state["resultados"] = registros
                st.success(f"{len(registros)} registros encontrados!")
            else:
                st.warning("Nenhum registro encontrado para os critérios fornecidos.")
                st.session_state["resultados"] = []

    # O restante das abas (Refino e Resultados) continua funcional como antes
    with tab_refino:
        df = pd.DataFrame(st.session_state.get("resultados", []))
        if df.empty:
            st.info("Sem dados ainda. Execute uma busca na primeira aba.")
        else:
            # ... (código de filtro mantido)
            colf = st.columns(3)
            with colf[0]:
                filtro_uf = st.selectbox("Filtrar por UF", ["(sem filtro)"] + list(UF_NOMES.keys()))
            with colf[1]:
                filtra_cnae_ini = st.text_input("CNAE Principal começa com (ex.: 07, 46)")
            with colf[2]:
                somente_ddd_pa = st.checkbox("Apenas DDD do Pará (91/93/94)", value=False)

            df2 = df.copy()
            if filtro_uf != "(sem filtro)":
                df2 = df2[df2["Endereço"].fillna("").str.contains(filtro_uf, case=False, regex=False)]
            if filtra_cnae_ini:
                df2["CNAE Principal"] = df2["CNAE Principal"].astype(str)
                df2 = df2[df2["CNAE Principal"].fillna("").str.startswith(filtra_cnae_ini)]
            if somente_ddd_pa:
                df2 = df2[df2["Telefone"].fillna("").str.replace(r'\D', '', regex=True).str[:2].isin(DDD_PA)]

            st.write(f"Resultados filtrados: {len(df2)}")
            st.dataframe(df2)
            st.session_state["df_filtrado"] = df2

    with tab_result:
        st.header("📥 Download dos Resultados")
        df_final = st.session_state.get("df_filtrado", pd.DataFrame(st.session_state.get("resultados", [])))
        if df_final.empty:
            st.warning("Nenhum resultado para exibir ou baixar.")
        else:
            # ... (código de download mantido)
            st.dataframe(df_final)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_final.to_excel(writer, index=False, sheet_name='Prospects')
            excel_data = output.getvalue()
            file_name_slug = slug(st.session_state.get("termo_busca", "prospects"))
            st.download_button(
                label="📥 Baixar resultados em Excel (.xlsx)",
                data=excel_data,
                file_name=f"prospects_{file_name_slug}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

if __name__ == "__main__":
    main()
