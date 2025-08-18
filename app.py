import streamlit as st
import requests

st.set_page_config(page_title="Consulta de CNPJs", page_icon="📊", layout="wide")

st.title("📊 Consulta de CNPJs")

cnpj = st.text_input("Digite o CNPJ (somente números):")

if st.button("Consultar"):
    if cnpj:
        try:
            url = f"https://receitaws.com.br/v1/cnpj/{cnpj}"
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                st.subheader("📌 Informações da Empresa")
                st.write(f"**Nome:** {data.get('nome')}")
                st.write(f"**Fantasia:** {data.get('fantasia')}")
                st.write(f"**Abertura:** {data.get('abertura')}")
                st.write(f"**Situação:** {data.get('situacao')}")
                st.write(f"**Atividade Principal:** {data['atividade_principal'][0]['text'] if data.get('atividade_principal') else ''}")
                
                st.subheader("👥 Sócios")
                if "qsa" in data:
                    for socio in data["qsa"]:
                        st.write(f"- {socio.get('nome')}")
            else:
                st.error("❌ Erro ao consultar API.")
        except Exception as e:
            st.error(f"Erro: {str(e)}")
    else:
        st.warning("Digite um CNPJ válido.")
