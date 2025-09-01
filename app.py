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

APP_TITLE = "🏢 Prospectador B2B – Extração e Enriquecimento (v5)"

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
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def limpa_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def normaliza_tel(t: str) -> str:
    if not t:
        return ""
    t = re.sub(r"[^0-9]", "", t)
    if t.startswith("55") and len(t) >= 12:
        t = t[2:]
    return t


@st.cache_data(ttl=60 * 30)
def http_get(url: str, timeout: int = 25, headers: dict | None = None) -> requests.Response | None:
    try:
        h = {"User-Agent": DEFAULT_UA}
        if headers:
            h.update(headers)
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return None


# ==============================================
# Enriquecimento (baixo custo): BrasilAPI / publica.cnpj.ws / ReceitaWS
# ==============================================

@st.cache_data(ttl=60 * 60)
def buscar_dados_receita_federal(cnpj: str) -> dict:
    c = limpa_cnpj(cnpj)
    if len(c) != 14:
        return {}

    fontes = [
        f"https://brasilapi.com.br/api/cnpj/v1/{c}",
        f"https://publica.cnpj.ws/cnpj/{c}",
        f"https://www.receitaws.com.br/v1/cnpj/{c}",
    ]
    for url in fontes:
        r = http_get(url, timeout=20)
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        if "razao_social" in data or "nome_fantasia" in data:
            return {
                "Razao Social (Receita)": data.get("razao_social") or data.get("nome"),
                "Nome Fantasia": data.get("nome_fantasia") or data.get("fantasia"),
                "CNPJ (Receita)": data.get("cnpj"),
                "Situação Cadastral": data.get("descricao_situacao_cadastral") or data.get("situacao"),
                "CNAE Principal": (data.get("cnae_fiscal") or data.get("cnae_principal", {})).get("codigo")
                if isinstance(data.get("cnae_principal"), dict)
                else data.get("cnae_fiscal"),
            }
        if data.get("status") == "OK":
            return {
                "Razao Social (Receita)": data.get("nome"),
                "Nome Fantasia": data.get("fantasia"),
                "CNPJ (Receita)": data.get("cnpj"),
                "Situação Cadastral": data.get("situacao"),
                "CNAE Principal": data.get("atividade_principal", [{}])[0].get("code"),
            }
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


@st.cache_data(ttl=60 * 60)
def buscar_redes_sociais(website: str) -> dict:
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
    try:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if "error" in data:
            st.error(f"Erro SerpAPI: {data['error']}")
            return []
        out = []
        for p in data.get("local_results", []) or []:
            out.append(
                {
                    "Nome": p.get("title"),
                    "Endereço": p.get("address"),
                    "Telefone": p.get("phone"),
                    "Website": p.get("website"),
                    "Rating": p.get("rating"),
                    "Avaliações": p.get("reviews"),
                    "Origem": "SerpAPI",
                }
            )
        return out
    except Exception as e:
        st.error(f"Erro de conexão com SerpAPI: {e}")
        return []


# NOVA VERSÃO DA FUNÇÃO PARA A ROTA 2
@st.cache_data(ttl=60 * 30)
def buscar_empresas_por_cnae(query_cnae: str, uf: str, max_empresas: int) -> list[dict]:
    """Busca empresas reais por código ou descrição de CNAE."""
    if not query_cnae:
        return []

    cnae_code = None
    # Verifica se a query parece um código CNAE
    if re.search(r'\d', query_cnae):
        cnae_code = re.sub(r'\D', '', query_cnae) # Limpa para usar na API
    else:
        # Se não for um código, busca a descrição na lista de CNAEs
        r_cnaes = http_get("https://publica.cnpj.ws/cnaes")
        if r_cnaes:
            try:
                lista_cnaes = r_cnaes.json()
                for cnae_item in lista_cnaes:
                    if query_cnae.lower() in (cnae_item.get("descricao") or "").lower():
                        cnae_code = str(cnae_item.get("codigo"))
                        break
            except Exception:
                st.error("Não foi possível encontrar um código CNAE para a descrição fornecida.")
                return []

    if not cnae_code:
        st.warning(f"Nenhum código CNAE encontrado para '{query_cnae}'.")
        return []

    # Busca real de empresas usando o código CNAE na API publica.cnpj.ws
    st.info(f"Buscando empresas com CNAE: {cnae_code}...")
    url = f"https://publica.cnpj.ws/v2/empresas?cnae={cnae_code}&uf={uf}&page=1"
    r_empresas = http_get(url)
    if not r_empresas:
        st.error("Falha ao buscar empresas na API.")
        return []

    try:
        data = r_empresas.json()
        results = []
        empresas_encontradas = data.get("empresas", [])
        for emp in empresas_encontradas[:max_empresas]:
            endereco = f"{emp.get('logradouro', '')}, {emp.get('numero', '')} - {emp.get('bairro', '')}, {emp.get('cidade', '')} - {emp.get('estado', '')}"
            results.append({
                "Nome": emp.get("razao_social"),
                "CNPJ": emp.get("cnpj"),
                "Endereço": endereco,
                "Telefone": emp.get("telefone1"),
                "Email": emp.get("email"),
                "Website": None, # Esta API não fornece website
                "Origem": f"Busca CNAE ({cnae_code})",
            })
        return results
    except Exception as e:
        st.error(f"Erro ao processar dados das empresas: {e}")
        return []


# ==============================================
# Orquestração de ENRIQUECIMENTO
# ==============================================

def enriquecer_empresas(empresas: list[dict], *, buscar_cnpj_receita: bool, buscar_redes: bool, buscar_emails: bool) -> list[dict]:
    out = []
    total = len(empresas)
    pb = st.progress(0.0)
    msg = st.empty()

    for i, emp in enumerate(empresas, start=1):
        msg.write(f"Enriquecendo: {emp.get('Nome') or emp.get('CNPJ') or 'registro'} ({i}/{total})")
        row = dict(emp)

        if buscar_emails and row.get("Website"):
            emails = buscar_emails_site(row["Website"]) or []
            row["Emails do Site"] = ", ".join(emails) if emails else None

        if buscar_redes and row.get("Website"):
            row.update(buscar_redes_sociais(row["Website"]))

        base_cnpj = emp.get("CNPJ") or emp.get("CNPJ (Receita)")
        if buscar_cnpj_receita and base_cnpj:
            dados = buscar_dados_receita_federal(base_cnpj)
            for k, v in dados.items():
                if v and not row.get(k):
                    row[k] = v

        out.append(row)
        pb.progress(i / total)
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
                "Rota 1 – SerpAPI Google Maps (Busca Real)",
                "Rota 2 – Busca por CNAE (Busca Real Gratuita)",
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
                cnae_query = st.text_input("🔎 CNAE (código ou descrição)", value="extração de minério de ferro")
                termo_busca = cnae_query
            with col[1]:
                uf = st.selectbox("Estado (UF)", list(UF_NOMES.keys()), index=list(UF_NOMES.keys()).index("MG"))
            with col[2]:
                max_r = st.slider("Qtd máx. empresas", 10, 50, 20, 5) # APIs gratuitas tem limite menor

        else:
            up = st.file_uploader("Envie um CSV com CNPJ, Nome, Website", type=["csv"])
            df_import = None
            if up is not None:
                try:
                    df_import = pd.read_csv(up)
                except Exception:
                    try:
                        df_import = pd.read_csv(up, sep=";")
                    except Exception:
                        st.error("Não foi possível ler o CSV.")
            max_r = st.slider("Qtd máx. linhas", 10, 2000, 200, 10)
            termo_busca = "importado"

        st.markdown("---")
        use_receita = st.checkbox("Enriquecer com dados da Receita (CNPJ/CNAE)", value=True)
        use_emails = st.checkbox("Buscar e-mails no site (Lento)", value=True)
        use_social = st.checkbox("Localizar redes sociais no site (Lento)", value=False)

        if st.button("🚀 Executar busca e enriquecer", type="primary"):
            registros: list[dict] = []
            with st.spinner("Buscando…"):
                if metodo.startswith("Rota 1"):
                    registros = serpapi_google_maps(nicho, local, serp_key, num_results=max_r)
                elif metodo.startswith("Rota 2"):
                    registros = buscar_empresas_por_cnae(cnae_query, uf, max_empresas=max_r)
                else:
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
                with st.spinner("Enriquecendo dados..."):
                    registros = enriquecer_empresas(
                        registros,
                        buscar_cnpj_receita=use_receita,
                        buscar_redes=use_social,
                        buscar_emails=use_emails,
                    )
                st.session_state["resultados"] = registros
                st.success(f"{len(registros)} registros encontrados e enriquecidos!")
            else:
                st.warning("Nenhum registro encontrado para os critérios fornecidos.")
                st.session_state["resultados"] = []


    with tab_refino:
        df = pd.DataFrame(st.session_state.get("resultados", []))
        if df.empty:
            st.info("Sem dados ainda. Execute uma busca na primeira aba.")
        else:
            colf = st.columns(3)
            with colf[0]:
                filtro_uf = st.selectbox("Filtrar por UF", ["(sem filtro)"] + list(UF_NOMES.keys()))
            with colf[1]:
                filtra_cnae_ini = st.text_input("CNAE Principal começa com (ex.: 07, 08)")
            with colf[2]:
                somente_ddd_pa = st.checkbox("DDD 91/93/94", value=False)

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
            st.warning("Nenhum resultado para exibir ou baixar. Realize uma busca primeiro.")
        else:
            st.write(f"Total de registros prontos para exportação: {len(df_final)}")
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
