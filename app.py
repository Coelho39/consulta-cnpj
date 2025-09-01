import os
import io
import re
import time
import json
import random
import unicodedata
from urllib.parse import urljoin

import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

# ==============================================
# Utilidades
# ==============================================

APP_TITLE = "🏢 Prospectador B2B – Extração e Enriquecimento (v4)"

UF_NOMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins"
}

# DDDs do Pará (para sinais adicionais na validação do telefone)
DDD_PA = {"91", "93", "94"}

# Resiliência para user-agent sem dependência externa
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
def http_get(url: str, timeout: int = 15, headers: dict | None = None) -> requests.Response | None:
    try:
        h = {"User-Agent": DEFAULT_UA}
        if headers:
            h.update(headers)
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception:
        return None


# ==============================================
# Enriquecimento (baixo custo): BrasilAPI / publica.cnpj.ws / ReceitaWS
# ==============================================

@st.cache_data(ttl=60 * 60)
def buscar_dados_receita_federal(cnpj: str) -> dict:
    """Consulta em 3 fontes públicas; retorna o primeiro sucesso.
    Mantido simples para manter custo zero.
    """
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

        # Normalização multi-fonte
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
    """Usa SerpAPI (pago/free)."""
    if not api_key:
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


@st.cache_data(ttl=60 * 30)
def cnpj_biz_busca_empresas(termo: str, uf: str | None = None, max_empresas: int = 40) -> list[dict]:
    """Busca de baixo custo no cnpj.biz (raspagem leve) para retornar empresas relacionadas.
    Observação: site de terceiros; se o layout mudar, ajustar o parser.
    """
    if not termo:
        return []

    query = re.sub(r"[^\w\s]", " ", termo).strip()
    query = re.sub(r"\s+", "+", query)
    url = f"https://cnpj.biz/search/{query}"
    r = http_get(url, timeout=20)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    links = [
        urljoin("https://cnpj.biz", a["href"]) for a in soup.find_all("a", href=True) if "/cnpj/" in a["href"]
    ]
    results = []
    for link in links[: max_empresas * 2]:  # leitura conservadora
        rr = http_get(link, timeout=20)
        if not rr:
            continue
        page = BeautifulSoup(rr.text, "html.parser").get_text("\n")
        # Extrações simples
        cnpj_match = re.search(r"(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})", page)
        nome_match = re.search(r"Nome\s*Fantasia\s*\n\s*(.+)\n|\bNome\s*Empresarial\s*\n\s*(.+)\n", page)
        endereco_match = re.search(r"Endere[çc]o\s*\n\s*(.+)\n", page)
        tel_match = re.search(r"Telefone\s*\n\s*([0-9\(\)\-\s]+)\n", page)
        email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", page)

        nome = None
        if nome_match:
            nome = (nome_match.group(1) or nome_match.group(2) or "").strip()

        cnpj = cnpj_match.group(1) if cnpj_match else None
        endereco = endereco_match.group(1).strip() if endereco_match else None
        telefone = normaliza_tel(tel_match.group(1)) if tel_match else None
        email = email_match.group(0).lower() if email_match else None

        # Filtro por UF, se solicitado
        if uf:
            uf_ok = (uf in (endereco or "")) or (UF_NOMES.get(uf, "") in (endereco or ""))
            if not uf_ok:
                continue

        if cnpj or nome:
            results.append(
                {
                    "Nome": nome or "(sem nome)",
                    "CNPJ": cnpj,
                    "Endereço": endereco,
                    "Telefone": telefone,
                    "Email": email,
                    "Website": None,
                    "Origem": "cnpj.biz",
                }
            )
        if len(results) >= max_empresas:
            break
        time.sleep(random.uniform(0.6, 1.2))  # gentileza
    return results


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

        # Email do site
        if buscar_emails and emp.get("Website"):
            emails = buscar_emails_site(emp["Website"]) or []
            row["Emails do Site"] = ", ".join(emails) if emails else None

        # Redes sociais
        if buscar_redes and emp.get("Website"):
            row.update(buscar_redes_sociais(emp["Website"]))

        # Receita/CNAE/Situação
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
    st.caption("Foco em **qualidade de dado** com custo mínimo: SerpAPI (quando necessário) + fontes públicas de CNPJ.")

    with st.expander("ℹ️ Dica de uso rápida", expanded=False):
        st.markdown(
            """
            **Objetivo**: retornar *menos* contatos, porém *mais certos*.

            - Para **mineradoras no Pará**: teste *Rota 2 – CNPJ.biz* com termo "mineradora" e UF **PA**, depois filtrar por CNAE (07/08).
            - Ative **Receita Federal** para validar situação e CNAE e **e-mails do site** para contato.
            - A aba **Filtro & Pós-processamento** ajuda a eliminar telefones fora do DDD do Pará (91/93/94) quando fizer sentido.
            """
        )

    tab_busca, tab_refino, tab_result = st.tabs(["🔎 Busca", "🧹 Filtro & Pós-processamento", "📊 Resultados & Exportação"])

    with tab_busca:
        st.subheader("1) Escolha a Rota de Busca")
        metodo = st.selectbox(
            "Método de aquisição",
            (
                "Rota 1 – SerpAPI Google Maps",
                "Rota 2 – CNPJ.biz (termo + UF)",
                "Rota 3 – Importar CSV (CNPJ/Nome)",
            ),
        )

        col = st.columns(3)
        if metodo == "Rota 1 – SerpAPI Google Maps":
            with col[0]:
                nicho = st.text_input("🎯 Nicho / Query", value="mineradora")
            with col[1]:
                local = st.text_input("📍 Localização", value="Pará, Brasil")
            with col[2]:
                serp_key = st.text_input("🔑 SerpAPI Key", type="password")
            max_r = st.slider("Qtd máx. resultados", 10, 100, 40, 10)

        elif metodo == "Rota 2 – CNPJ.biz (termo + UF)":
            with col[0]:
                termo = st.text_input("🔎 Termo (ex.: mineradora, mineração, brita)", value="mineradora")
            with col[1]:
                uf = st.selectbox("UF", list(UF_NOMES.keys()), index=list(UF_NOMES.keys()).index("PA"))
            with col[2]:
                max_r = st.slider("Qtd máx. empresas", 10, 100, 40, 10)

        else:  # Importar CSV
            up = st.file_uploader("Envie um CSV com colunas CNPJ, Nome, Website (opcional)", type=["csv"]) 
            df_import = None
            if up is not None:
                try:
                    df_import = pd.read_csv(up)
                except Exception:
                    try:
                        df_import = pd.read_csv(up, sep=";")
                    except Exception:
                        st.error("Não foi possível ler o CSV. Verifique o separador.")
            max_r = st.slider("Qtd máx. linhas (para processamento)", 10, 2000, 200, 10)

        st.markdown("---")
        st.subheader("2) Enriquecimento (custo zero)")
        col2 = st.columns(3)
        with col2[0]:
            use_receita = st.checkbox("Validar em Receita (CNPJ/CNAE/Situação)", value=True)
        with col2[1]:
            use_emails = st.checkbox("Buscar e-mails no site", value=True)
        with col2[2]:
            use_social = st.checkbox("Localizar redes sociais", value=False)

        if st.button("🚀 Executar busca e enriquecer", type="primary"):
            registros: list[dict] = []
            with st.spinner("Buscando…"):
                if metodo == "Rota 1 – SerpAPI Google Maps":
                    registros = serpapi_google_maps(nicho, local, serp_key, num_results=max_r)
                elif metodo == "Rota 2 – CNPJ.biz (termo + UF)":
                    registros = cnpj_biz_busca_empresas(termo, uf, max_empresas=max_r)
                else:
                    if df_import is not None and len(df_import) > 0:
                        tmp = df_import.head(max_r).to_dict(orient="records")
                        # Normaliza chaves comuns
                        for r in tmp:
                            r.setdefault("Nome", r.get("nome") or r.get("Razao Social") or r.get("razao_social"))
                            r.setdefault("CNPJ", r.get("cnpj") or r.get("CNPJ (Receita)"))
                            r.setdefault("Website", r.get("website") or r.get("site"))
                            r.setdefault("Origem", "CSV")
                        registros = tmp
                    else:
                        st.warning("Envie um CSV válido para continuar.")

            if registros:
                st.success(f"{len(registros)} registros brutos obtidos. Iniciando enriquecimento…")
                registros = enriquecer_empresas(
                    registros,
                    buscar_cnpj_receita=use_receita,
                    buscar_redes=use_social,
                    buscar_emails=use_emails,
                )
                st.session_state["resultados"] = registros
                st.toast("Pronto! Vá para a aba *Resultados* para exportar e refinar.")
            else:
                st.warning("Nenhum registro encontrado.")

    with tab_refino:
        st.subheader("Refino opcional")
        df = pd.DataFrame(st.session_state.get("resultados", []))
        if df.empty:
            st.info("Sem dados ainda. Execute uma busca na aba anterior.")
        else:
            colf = st.columns(4)
            with colf[0]:
                filtro_uf = st.selectbox("Filtrar por UF no endereço", ["(sem filtro)"] + list(UF_NOMES.keys()), index=1)
            with colf[1]:
                filtra_cnae_ini = st.text_input("CNAE começa com (ex.: 07, 08)")
            with colf[2]:
                somente_ddd_pa = st.checkbox("Telefone começa com DDD 91/93/94", value=False)
            with colf[3]:
                dedup_nome = st.checkbox("Deduplicar por Nome", value=True)

            df2 = df.copy()
            if filtro_uf != "(sem filtro)":
                df2 = df2[df2["Endereço"].fillna("").str.contains(fr"\b{filtro_uf}\b|{UF_NOMES.get(filtro_uf)}", case=False, regex=True)]
            if filtra_cnae_ini:
                df2 = df2[df2["CNAE Principal"].fillna("").astype(str).str.startswith(filtra_cnae_ini)]
            if somente_ddd_pa:
                df2 = df2[df2["Telefone"].fillna("").astype(str).str[:2].isin(DDD_PA)]
            if dedup_nome and "Nome" in df2.columns:
                df2 = df2.drop_duplicates(subset=["Nome"]) 

            st.dataframe(df2, use_container_width=True)
            st.caption(f"Linhas após filtros: **{len(df2)}** (de {len(df)})")
            st.session_state["df_filtrado"] = df2

    with tab_result:
        st.subheader("Exportação")
        df = pd.DataFrame(st.session_state.get("df_filtrado") or st.session_state.get("resultados") or [])
        if df.empty:
            st.info("Sem dados para exportar. Faça uma busca e/ou aplique filtros.")
        else:
            st.dataframe(df, use_container_width=True)

            def _to_excel_bytes(_df: pd.DataFrame) -> bytes:
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as w:
                    _df.to_excel(w, index=False, sheet_name="Empresas")
                return output.getvalue()

            c1, c2 = st.columns(2)
            c1.download_button(
                "📥 Baixar CSV",
                df.to_csv(index=False, encoding="utf-8-sig"),
                file_name=f"prospectos-{slug(str(time.time()))}.csv",
                mime="text/csv",
            )
            c2.download_button(
                "📊 Baixar Excel",
                _to_excel_bytes(df),
                file_name=f"prospectos-{slug(str(time.time()))}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.info(
                "Dica: para este cliente (oficina de freios de caminhão), salve um filtro pré-definido com UF=PA e CNAE começando em **07** ou **08** quando a busca for por mineradoras."
            )


if __name__ == "__main__":
    main()
