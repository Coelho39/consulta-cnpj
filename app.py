# app_enriquecido.py
import requests
import pandas as pd
import streamlit as st
import time, re, random
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from urllib.parse import urljoin

# ==================== FUNÇÕES AUXILIARES ====================

def buscar_emails_site(website, timeout=15):
    """
    Busca e-mails diretamente no site oficial da empresa
    """
    emails = []
    if not website or not website.startswith("http"):
        return []
    try:
        ua = UserAgent()
        headers = {"User-Agent": ua.random}
        response = requests.get(website, headers=headers, timeout=timeout)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text()

        # Procura padrões de e-mail
        found = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        emails.extend(found)

        # Também procura em links <a href="mailto:...">
        for a in soup.find_all("a", href=True):
            if "mailto:" in a["href"]:
                emails.append(a["href"].replace("mailto:", "").strip())

        return list(set(emails))
    except Exception:
        return []

def buscar_dados_cnpj_biz(nome_empresa, timeout=15):
    """
    Faz scraping no site cnpj.biz para tentar achar CNPJ, sócios e email
    """
    try:
        ua = UserAgent()
        headers = {"User-Agent": ua.random}
        query = nome_empresa.replace(" ", "+")
        url = f"https://cnpj.biz/{query}"
        response = requests.get(url, headers=headers, timeout=timeout)
        soup = BeautifulSoup(response.text, "html.parser")

        bloco = soup.find("div", {"class": "list-group"})
        if not bloco:
            return {"CNPJ": None, "Sócios": [], "Email_CNPJ": None}

        link_empresa = bloco.find("a")["href"]
        detalhe = requests.get(link_empresa, headers=headers, timeout=timeout)
        soup_det = BeautifulSoup(detalhe.text, "html.parser")
        page_text = soup_det.get_text()

        # Extrair CNPJ
        cnpj = None
        cnpj_match = re.search(r'(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})', page_text)
        if cnpj_match:
            cnpj = cnpj_match.group(1)

        # Extrair sócios
        socios = []
        for li in soup_det.find_all("li", {"class": "list-group-item"}):
            if "Sócio" in li.text:
                socios.append(li.text.strip())

        # Extrair email
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', page_text)
        email = email_match.group() if email_match else None

        return {"CNPJ": cnpj, "Sócios": socios, "Email_CNPJ": email}
    except Exception:
        return {"CNPJ": None, "Sócios": [], "Email_CNPJ": None}

def buscar_dados_receita(cnpj):
    """
    Busca dados em APIs públicas de CNPJ
    """
    if not cnpj:
        return {}
    cnpj_limpo = re.sub(r"\D", "", cnpj)
    if len(cnpj_limpo) != 14:
        return {}
    apis = [
        f"https://www.receitaws.com.br/v1/cnpj/{cnpj_limpo}",
        f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}",
        f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    ]
    for url in apis:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if "email" in data:
                    return {"Email_Receita": data.get("email")}
        except:
            continue
    return {}

def buscar_redes_sociais(website):
    """
    Busca redes sociais e tenta capturar e-mails nelas
    """
    dados = {"Facebook": None, "Instagram": None, "LinkedIn": None, "Email_Social": None}
    if not website or not website.startswith("http"):
        return dados
    try:
        ua = UserAgent()
        r = requests.get(website, headers={"User-Agent": ua.random}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text()
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        if email_match:
            dados["Email_Social"] = email_match.group()
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if "facebook.com" in href:
                dados["Facebook"] = a["href"]
            elif "instagram.com" in href:
                dados["Instagram"] = a["href"]
            elif "linkedin.com" in href:
                dados["LinkedIn"] = a["href"]
    except:
        pass
    return dados

# ==================== ENRIQUECIMENTO ====================

def enriquecer_empresas(empresas):
    dados_finais = []
    total = len(empresas)
    progress = st.progress(0)
    for i, emp in enumerate(empresas):
        enriched = emp.copy()
        nome = emp.get("Nome", "")
        website = emp.get("Website")

        # Emails do site
        enriched["Email_Site"] = "; ".join(buscar_emails_site(website))

        # CNPJ.biz
        dados_cnpj = buscar_dados_cnpj_biz(nome)
        enriched.update(dados_cnpj)

        # Receita
        if dados_cnpj.get("CNPJ"):
            enriched.update(buscar_dados_receita(dados_cnpj["CNPJ"]))

        # Redes sociais
        enriched.update(buscar_redes_sociais(website))

        dados_finais.append(enriched)
        progress.progress((i+1)/total)
        time.sleep(random.uniform(1, 2))
    return dados_finais

# ==================== INTERFACE STREAMLIT ====================

def main():
    st.set_page_config(page_title="Gerador de Lista Enriquecida", page_icon="📊", layout="wide")
    st.title("📊 Gerador de Lista Enriquecida")
    st.write("Digite nicho + cidade e o app busca empresas e enriquece com e-mails e CNPJ.")

    nicho = st.text_input("🎯 Nicho:", placeholder="ex: clínica odontológica")
    local = st.text_input("📍 Localização:", placeholder="ex: Belo Horizonte, MG")

    if st.button("🚀 Gerar Lista"):
        if not nicho or not local:
            st.warning("Preencha todos os campos.")
            return

        # Aqui você pode trocar por API oficial ou scraping
        st.info("⚡ Simulação de resultados (adicione sua função de busca aqui)")
        empresas = [
            {"Nome": f"{nicho} Exemplo 1", "Endereço": local, "Telefone": "(31) 3333-0001", "Website": "http://exemplo.com"},
            {"Nome": f"{nicho} Exemplo 2", "Endereço": local, "Telefone": "(31) 3333-0002", "Website": "http://exemplo2.com"},
        ]

        enriched = enriquecer_empresas(empresas)
        df = pd.DataFrame(enriched)
        st.dataframe(df)

        # Exportar Excel
        arquivo = "empresas_enriquecidas.xlsx"
        df.to_excel(arquivo, index=False)
        with open(arquivo, "rb") as f:
            st.download_button("📥 Baixar Excel", f, file_name=arquivo)

if __name__ == "__main__":
    main()
