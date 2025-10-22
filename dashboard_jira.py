import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
import streamlit as st
import plotly.express as px

# ==============================
# CONFIGURAÇÕES DO JIRA
# ==============================
JIRA_DOMAIN = st.secrets["jira"]["domain"]
JIRA_EMAIL = st.secrets["jira"]["email"]
JIRA_API_TOKEN = st.secrets["jira"]["api_token"]
FILTER_ID = st.secrets["jira"]["filter_id"]

# ==============================
# FUNÇÃO: buscar JQL do filtro
# ==============================
def obter_jql_do_filtro():
    # Nota: Este endpoint /filter/{ID} geralmente é estável.
    url = f"{JIRA_DOMAIN}/rest/api/3/filter/{FILTER_ID}"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    response = requests.get(url, auth=auth)
    
    if response.status_code != 200:
        st.error(f"Erro ao obter filtro {FILTER_ID}: {response.status_code}")
        return None
    
    data = response.json()
    return data.get("jql", "")

# ==============================
# FUNÇÃO: buscar issues do Jira
# ==============================
import json # Adicione esta importação no início do seu script, se ainda não estiver lá

# ==============================
# FUNÇÃO: buscar issues do Jira (CORREÇÃO FINAL)
# ==============================
def buscar_dados_jira(jql):
    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql"
    headers = {"Accept": "application/json"}
    
    # CORREÇÃO CRUCIAL: Adicionar 'fields' para garantir que os campos de usuário venham completos
    # O valor '*navigable' retorna a maioria dos campos. Adicionamos 'assignee' explicitamente para garantir que venha.
    params = {
        "jql": jql, 
        "maxResults": 1000,
        "fields": "summary,assignee" # Garante que summary e assignee sejam incluídos
    }
    
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)

    response = requests.get(url, headers=headers, params=params, auth=auth)

    # ... (o resto da sua verificação de status_code e tratamento de erro permanece igual)
    if response.status_code != 200:
        st.error(f"Erro ao buscar dados do Jira: {response.status_code}")
        st.code(response.text)
        return pd.DataFrame()

    data = response.json()
    issues = data.get("issues", [])

    registros = []
    for issue in issues:
        key = issue.get("key", "")
        fields = issue.get("fields", {})
        resumo = fields.get("summary", "")
        
        assignee = fields.get("assignee")
        
        # Lógica final de extração: Agora que solicitamos o campo, ele deve vir
        responsavel = "Sem responsável"
        
        if assignee and isinstance(assignee, dict):
            
            # Tenta encontrar a chave 'displayName' (que deve existir agora)
            if "displayName" in assignee:
                responsavel = assignee["displayName"]
            elif "accountId" in assignee:
                # Usa o accountId como fallback, caso o displayName ainda falhe
                responsavel = assignee["accountId"]
        
        registros.append({
            "Chave": key,
            "Resumo": resumo,
            "Responsável": responsavel
        })

    return pd.DataFrame(registros)

    # ==============================================================
    # 1. VERIFICAÇÃO DE DADOS (Imprime o status no TERMINAL)
    # ==============================================================
    print("-" * 50)
    print(f"DEBUG: JQL usado: {jql}")
    print(f"DEBUG: Total de Issues retornadas pela API: {len(issues)}")
    
    if len(issues) == 0:
        print("DEBUG: A API retornou 0 issues. Verifique o JQL ou as permissões.")
        # Se você quiser ver o JSON inteiro retornado, descomente a linha abaixo:
        # print(json.dumps(data, indent=2))
    print("-" * 50)

    registros = []
    for issue in issues:
        key = issue.get("key", "")
        fields = issue.get("fields", {})
        resumo = fields.get("summary", "")
        
        assignee = fields.get("assignee")
        
        # LÓGICA DE EXTRAÇÃO E DEBUG
        responsavel = "Sem responsável"
        
        # 2. VERIFICAÇÃO DE ASSIGNEE (Imprime no TERMINAL apenas se tiver dados)
        if assignee and isinstance(assignee, dict):
            # Imprime o objeto ASSIGNEE no terminal
            print(f"Assignee JSON para issue {key}:")
            print(json.dumps(assignee, indent=2))
            
            # Tenta encontrar a chave correta
            if "displayName" in assignee:
                responsavel = assignee["displayName"]
            elif "name" in assignee:
                responsavel = assignee["name"]
            elif "accountId" in assignee:
                responsavel = assignee["accountId"]
        
        # Se 'assignee' for None (Issue não atribuída), a lógica acima é ignorada e 'responsavel' fica "Sem responsável"
        
        registros.append({
            "Chave": key,
            "Resumo": resumo,
            "Responsável": responsavel
        })

    return pd.DataFrame(registros)

# ==============================
# INTERFACE STREAMLIT
# ==============================
st.set_page_config(page_title="Dashboard Jira - Quantidade por Responsável", layout="wide")
st.title("📊 Dashboard Jira - Quantidade de Atividades por Responsável")

# Certifique-se que JIRA_DOMAIN, JIRA_EMAIL, etc. estão definidos antes de executar esta linha
try:
    jql = obter_jql_do_filtro()
except NameError:
    st.error("Erro: Variáveis JIRA_DOMAIN, JIRA_EMAIL, JIRA_API_TOKEN ou FILTER_ID não definidas.")
    jql = None


if jql:
    st.caption(f"Filtro Jira ID {FILTER_ID}: `{jql}`")
    
    # Adiciona um cache para evitar múltiplas chamadas à API em cada recarregamento
    @st.cache_data(ttl=600) # Cache por 10 minutos
    def load_data(jql_query):
        return buscar_dados_jira(jql_query)

    df = load_data(jql)

    if not df.empty:
        # Contagem de tasks por responsável
        contagem = df["Responsável"].value_counts().reset_index()
        contagem.columns = ["Responsável", "Quantidade"]

        st.subheader("Tabela de Quantidade por Responsável")
        st.dataframe(contagem)

        # Gráfico
        fig = px.bar(contagem, x="Responsável", y="Quantidade", color="Responsável",
                     title="Quantidade de Tasks por Responsável", text="Quantidade")
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        # Top responsável
        # Garante que 'contagem' não está vazia (já verificado pelo 'if not df.empty')
        max_resp = contagem.iloc[0]
        st.success(f"👑 Responsável com mais tasks: **{max_resp['Responsável']}** ({max_resp['Quantidade']} atividades)")
    else:
        st.warning(f"Nenhum dado encontrado para o filtro especificado (JQL: `{jql}`).")