import requests
import pandas as pd
import time
from bs4 import BeautifulSoup
import streamlit as st

# ===================== FUNÇÕES =====================

def buscar_empresas_scraping(nicho, local, limite=10):
    """
    Busca empresas no Google Maps via scraping (resultado do Google Search)
    """
    query = f"{nicho} em {local} site:google.com/maps"
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "google.com/maps/place/" in href and href not in links:
            links.append(href)
        if len(links) >= limite:
            break

    empresas = []
    for link in links:
        try:
            page = requests.get(link, headers=headers)
            sp = BeautifulSoup(page.text, "html.parser")

            nome = sp.find("h1")
            nome = nome.text if nome else None

            telefone = None
            endereco = None
            site = None

            for span in sp.find_all("span"):
                txt = span.get_text()
                if txt and ("(" in txt and ")" in txt and "-" in txt):
                    telefone = txt
                elif "R." in txt or "Av." in txt or "Rua" in txt:
                    endereco = txt

            for a in sp.find_all("a", href=True):
                if "http" in a["href"] and "google" not in a["href"]:
                    site = a["href"]
                    break

            empresas.append({
                "Nome": nome,
                "Endereço": endereco,
                "Telefone": telefone,
                "Site": site
            })

            time.sleep(2)  # evitar bloqueio
        except Exception as e:
            print(f"⚠️ Erro extraindo {link}: {e}")

    return empresas

# ===================== INTERFACE STREAMLIT =====================

st.set_page_config(page_title="Gerador de Listas B2B (Scraping)", page_icon="📊", layout="wide")

st.title("📊 Gerador de Lista de Empresas (Scraping Google Maps)")
st.write("Digite **nicho + região** e o app tenta buscar dados direto do Google Maps (sem API).")

nicho = st.text_input("Digite o nicho (ex: clínica odontológica, restaurante, loja de pisos):")
local = st.text_input("Digite a cidade/região (ex: Belo Horizonte, MG):")
limite = st.slider("Quantas empresas buscar?", 5, 20, 5)

if st.button("Gerar Lista"):
    if nicho and local:
        with st.spinner("Buscando empresas..."):
            empresas = buscar_empresas_scraping(nicho, local, limite=limite)

            if not empresas:
                st.error("❌ Nenhum resultado encontrado (Google pode ter bloqueado).")
            else:
                df = pd.DataFrame(empresas)
                st.success("✅ Busca concluída!")
                st.dataframe(df)

                # Exportar para Excel
                arquivo = "empresas_scraping.xlsx"
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
