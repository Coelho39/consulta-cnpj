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
# Removido streamlit para execução em ambiente de desenvolvimento
# import streamlit as st
from bs4 import BeautifulSoup

# ==============================================
# Utilidades
# ==============================================

APP_TITLE = "🏢 Prospectador B2B – Prospecção Ativa (v8.0 - Estratégia de Scraping Revisada)"

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

# A anotação @st.cache_data foi removida para permitir a execução fora do Streamlit
def http_get(url: str, timeout: int = 45, headers: dict | None = None ) -> requests.Response | None:
    """Realiza uma requisição HTTP GET com tratamento de erros."""
    try:
        h = headers if headers else {"User-Agent": DEFAULT_UA}
        print(f"Acessando URL: {url}") # Log para depuração
        r = requests.get(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.RequestException as e:
        print(f"AVISO: Não foi possível acessar {url}. O site pode estar offline ou bloqueando o acesso. Erro: {e}")
        return None

# ==============================================
# Funções de Enriquecimento
# ==============================================
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
    except (json.JSONDecodeError, Exception) as e:
        print(f"ERRO: Falha ao processar JSON da BrasilAPI para o CNPJ {c}. Erro: {e}")
        return {}
    return {}

# ==============================================
# Funções para a Prospecção Ativa
# ==============================================

def encontrar_cnaes_por_descricao(descricao: str) -> list[dict]:
    """Encontra códigos e descrições de CNAE a partir de uma palavra-chave no IBGE."""
    if not descricao: return []
    url = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"
    r = http_get(url )
    if not r:
        print("ERRO: Não foi possível acessar a lista de CNAEs do IBGE.")
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
        print(f"ERRO: Erro ao processar lista de CNAEs do IBGE: {e}")
        return []

# --- FUNÇÃO CORRIGIDA ---
def raspar_cnpjs_consultacnpj(cnae_code: str, cnae_desc: str, uf: str, max_por_cnae: int) -> list[dict]:
    """
    Faz web scraping no site consultacnpj.com usando a estrutura de URL corrigida.
    A nova URL utiliza um 'slug' da descrição do CNAE.
    Exemplo: 'extracao-de-minerio-de-ferro-cnae-0710301'
    """
    cnae_limpo = re.sub(r'\D', '', cnae_code)
    cnae_slug = slug(cnae_desc) # Cria o slug a partir da descrição completa
    
    # Nova estrutura de URL, mais robusta
    url = f"https://consultacnpj.com/cnae/{cnae_slug}-cnae-{cnae_limpo}/{uf.lower( )}"
    
    headers = {
        'User-Agent': DEFAULT_UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Referer': 'https://www.google.com/' # Simula uma origem de tráfego mais comum
    }
    
    r = http_get(url, headers=headers )
    if not r: return []
        
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        empresas = []
        # Seletor CSS mais específico para os cards de empresa
        cards = soup.select("div.card.company-card")
        
        if not cards:
            print(f"AVISO: Nenhum card de empresa encontrado na página para o CNAE {cnae_code} em {uf}.")
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
        print(f"AVISO: Erro ao raspar dados para o CNAE {cnae_code}: {e}")
        return []

# ==============================================
# Orquestração Principal (Simulação)
# ==============================================

def executar_prospeccao():
    """Função principal que orquestra a prospecção."""
    # Parâmetros da sua busca
    atividade = "extração de minério de ferro"
    uf = "PA"
    max_cnaes = 3
    max_empresas_por_cnae = 10

    print(f"--- Iniciando Prospecção Ativa para '{atividade}' em '{uf}' ---")

    cnaes_encontrados = encontrar_cnaes_por_descricao(atividade)
    if not cnaes_encontrados:
        print(f"Nenhum CNAE encontrado para '{atividade}'. Encerrando.")
        return

    print(f"Sucesso! Encontramos {len(cnaes_encontrados)} CNAEs. Investigando os {max_cnaes} primeiros.")
    todos_registros = []
    
    for i, cnae in enumerate(cnaes_encontrados[:max_cnaes]):
        cnae_cod, cnae_desc = cnae['codigo'], cnae['descricao']
        print(f"\nPasso {i+1}/{max_cnaes}: Buscando empresas para CNAE {cnae_cod} ('{cnae_desc[:50]}...')")
        
        registros_cnae = raspar_cnpjs_consultacnpj(cnae_cod, cnae_desc, uf, max_empresas_por_cnae)
        if registros_cnae:
            print(f"  -> Encontradas {len(registros_cnae)} empresas.")
            todos_registros.extend(registros_cnae)
        else:
            print("  -> Nenhuma empresa encontrada para este CNAE/UF.")
        time.sleep(random.uniform(1.5, 3.0)) # Pausa para não sobrecarregar o servidor

    if not todos_registros:
        print("\nA busca por empresas não retornou resultados. Verifique os parâmetros ou a disponibilidade do site.")
        return
    
    print(f"\n--- Busca inicial concluída. {len(todos_registros)} empresas encontradas. Enriquecendo dados... ---")
    registros_finais = []
    
    for i, reg in enumerate(todos_registros):
        print(f"Enriquecendo {i+1}/{len(todos_registros)}: {reg.get('Nome')} ({reg.get('CNPJ')})")
        dados_ricos = buscar_dados_receita_federal(reg.get("CNPJ"))
        if dados_ricos:
            registros_finais.append(dados_ricos)
        time.sleep(0.5) # Pausa para não exceder limites da API

    print("\n--- Prospecção e enriquecimento concluídos! ---")
    
    if registros_finais:
        df_final = pd.DataFrame(registros_finais)
        # Salvar em Excel
        nome_arquivo = f"prospects_{slug(atividade)}_{uf.lower()}.xlsx"
        df_final.to_excel(nome_arquivo, index=False, engine='xlsxwriter')
        print(f"\nResultados salvos com sucesso no arquivo: {nome_arquivo}")
        print("\nPré-visualização dos dados:")
        print(df_final.head())
    else:
        print("\nNenhum dado de empresa pôde ser enriquecido.")

# Executa a função principal
if __name__ == "__main__":
    executar_prospeccao()

