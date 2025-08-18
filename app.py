import requests
import pandas as pd
import time
from bs4 import BeautifulSoup
import streamlit as st

# 🔑 Sua chave da Google Places API
GOOGLE_API_KEY = "SUA_GOOGLE_API_KEY_AQUI"

# ===================== FUNÇÕES =====================

def buscar_empresas(nicho, local, limite=10):
    """
    Busca empresas no Google Places API
    """
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": f"{nicho} em {local}",
        "key": GOOGLE_API_KEY
    }

    response = requests.get(url, params=params)
    results = response.json().get("results", [])

    empresas = []
    for r in results[:limite]:
        place_id = r["place_id"]

        # Detalhes do local
        details_url = "https://maps.googleapis.com/maps/api/place/details/json"
        details_params = {
            "place_id": place_id,
            "fields": "name,formatted_address,formatted_phone_number,website",
            "key": GOOGLE_API_KEY
        }
        details = requests.get(details_url, params=details_params).json().get("result", {})

        empresas.append({
            "Nome": details.get("name"),
            "Endereço": details.get("formatted_address"),
            "Telefone": details.get("formatted_phone_number"),
            "Site": details.get("website")
        })

    return empresas


def buscar_dados_cnpj(nome_empresa):
    """
    Faz scraping no site cnpj.biz para tentar achar o CNPJ, sócios e email
    """
    try:
        query = nome_empresa.replace(" ", "+")
        url = f"https://cnpj.biz/{query}"
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        bloco = soup.find("div", {"class": "list-group"})
        if not bloco:
            return {"CNPJ": None, "Sócios": [], "Email": None}

        link_empresa = bloco.find("a")["href"]
        detalhe = requests.get(link_empresa, timeout=10)
        soup_det = BeautifulSoup(detalhe.text, "html.parser")

        # Extrair CNPJ
        cnpj = None
        cnpj_tag = soup_det.find("p", string=lambda t: t and "CNPJ" in t)
        if cnpj_tag:
            cnpj = cnpj_tag.text.split(":")[-1].strip()

        # Extrair sócios
        socios = []
        socios_tag = soup_det.find_all("li", {"class": "list-group-item"})
        for s in socios_tag:
            if "Sócio" in s.text:
                socios.append(s.text.strip())

        # Extrair email (se existir)
        email = None
        for a in soup_det.find_all("a", href=True):
            if "mailto:" in a["href"]:
                email = a.text.strip()

        return {"CNPJ": cnpj, "Sócios": socios, "Email": email}

    except Exception:
        return {"CNPJ": None, "Sócios": [], "Email": None}


def enriquecer_empresas(empresas):
    """
    Para cada empresa, busca CNPJ e sócios via scraping
    """
    dados_finais = []
    for emp in empresas:
        dados_cnpj = buscar_dados_cnpj(emp["Nome"])
        dados_finais.append({
            **emp,
            "CNPJ": dados_cnpj.get("CNPJ"),
            "Email": dados_cnpj.get("Email"),
            "Sócios": ", ".join(dados_cnpj.get("Sócios", []))
        })
        time.sleep(2)  # evitar bloqueio do site
    return dados_finais

# ===================== INTERFACE STREAMLIT =====================

st.set_page_config(page_title="Gerador de Listas B2B", page_icon="📊", layout="wide")

st.title("📊 Gerador de Lista de Empresas")
st.write("Busque empresas por **nicho + região** e exporte para Excel com CNPJ, sócios e contatos.")

nicho = st.text_input("Digite o nicho (ex: clínica odontológica, restaurante, loja de pisos):")
local = st.text_input("Digite a cidade/região (ex: Belo Horizonte, MG):")
limite = st.slider("Quantas empresas buscar?", 5, 50, 10)

if st.button("Gerar Lista"):
    if nicho and local:
        with st.spinner("Buscando empresas..."):
            empresas = buscar_empresas(nicho, local, limite=limite)
            dados = enriquecer_empresas(empresas)

            df = pd.DataFrame(dados)
            st.success("✅ Busca concluída!")
            st.dataframe(df)

            # Exportar para Excel
            arquivo = "empresas_com_cnpj.xlsx"
            df.to_excel(arquivo, index=False)

            with open(arquivo, "rb") as f:
                st.download_button(
                    label="📥 Baixar Excel",
                    data=f,
                    file_name=arquivo,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    else:
        st.warning("⚠️ Digite um nicho e uma cidade para continuar.")
