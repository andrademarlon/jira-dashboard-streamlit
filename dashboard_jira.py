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

# JQL FORNECIDO PELO USUÁRIO (AGORA USADO DIRETAMENTE)
JQL_DIRETO = 'project = ATT AND issuetype IN ("BUG - SPRINT", "BUG - SPRINT", "Débito Técnico", "Débito Técnico", História, Melhoria, Bug, Tarefa) AND status IN (Done, "IN ASSISTED OPERATION", "IN CODING", "PENDING APPROVAL", "Pending Estimate", "READY TO DEPLOY (SDXOK)", "To Do", "EM HOMOLOGAÇÃO (SdBx)", "EM HOMOLOGAÇÃO (STG)", "Evidência DEV (STG)", "PRONTO PARA SANDBOX", "TESTE DEV (STG)") AND assignee IN (5e1c688dbf70110ca24c7c73, 712020:1547646a-3907-450f-ad34-f6da0c756b82, 712020:7a7bab5f-220a-4380-9987-741f797b6ca0, 5e3c700e3f647d0c99d80da0, 62c2df061bb561c33794dfd0, 5d2339a2831d7b0bcfbe1858, empty, currentUser()) AND sprint = 1916 ORDER BY updated DESC'


# ====================================================
# FUNÇÃO: buscar issues do Jira (CORRIGIDA COM NOVO ENDPOINT)
# ====================================================
def buscar_dados_jira(jql):
    # CORREÇÃO: Usando o endpoint /rest/api/3/search/jql conforme o Jira solicitou
    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql" 
    
    # Headers necessários para o método POST
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json" 
    }
    
    # Corpo da requisição no formato JSON
    payload = {
        "jql": jql,
        "maxResults": 1000,
        # CAMPOS: 'parent', 'issuelinks', e 'issuetype' são essenciais para o dashboard de Bugsprint
        "fields": ["summary", "assignee", "parent", "issuelinks", "issuetype", "status", "key"]
    }
    
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)

    # Mantemos o requests.post para garantir que o JQL longo funcione
    response = requests.post(url, headers=headers, json=payload, auth=auth)

    if response.status_code != 200:
        st.error(f"Erro ao buscar dados do Jira: {response.status_code}.")
        st.caption("Detalhes do erro da API (Verifique o JQL ou permissões):")
        try:
             # Tenta exibir a mensagem de erro da API
            st.code(response.json()) 
        except:
             # Exibe o texto puro se não for JSON
            st.code(response.text)
        return pd.DataFrame()

    data = response.json()
    issues = data.get("issues", [])
    
    # O restante da lógica de processamento dos dados permanece a mesma...
    registros = []
    for issue in issues:
        key = issue.get("key", "")
        fields = issue.get("fields", {})
        resumo = fields.get("summary", "")
        issuetype = fields.get("issuetype", {}).get("name", "N/A")
        status = fields.get("status", {}).get("name", "N/A")
        
        # --- Lógica de Responsável ---
        assignee = fields.get("assignee")
        responsavel = "Sem responsável"
        if assignee and isinstance(assignee, dict):
            responsavel = assignee.get("displayName", assignee.get("accountId", "Desconhecido"))
            
        # --- Lógica de História Relacionada ---
        historia_relacionada_key = "Nenhuma"
        historia_relacionada_resumo = "Nenhuma"

        # 1. Tentar Parent (se for Sub-tarefa)
        parent = fields.get("parent")
        if parent and parent.get("fields", {}).get("issuetype", {}).get("name") == "História":
            historia_relacionada_key = parent.get("key", "")
            historia_relacionada_resumo = parent.get("fields", {}).get("summary", "")
        
        # 2. Tentar Issuelinks (para vínculo)
        elif fields.get("issuelinks"):
            for link in fields["issuelinks"]:
                issue_link = link.get("inwardIssue") or link.get("outwardIssue")
                if issue_link and issue_link.get("fields", {}).get("issuetype", {}).get("name") == "História":
                    historia_relacionada_key = issue_link.get("key", "")
                    historia_relacionada_resumo = issue_link.get("fields", {}).get("summary", "")
                    break
        
        registros.append({
            "Chave": key,
            "Resumo": resumo,
            "Tipo": issuetype,
            "Status": status,
            "Responsável": responsavel,
            "História Relacionada (Key)": historia_relacionada_key,
            "História Relacionada (Resumo)": historia_relacionada_resumo,
        })

    return pd.DataFrame(registros)


# ==============================
# INTERFACE STREAMLIT
# ==============================
st.set_page_config(page_title="Dashboard Jira - Bugsprints e Detalhes", layout="wide")
st.title("📊 Painel de Indicadores - Dashboard Jira - ATTRACT")

jql = JQL_DIRETO

if jql:
    st.caption(f"JQL Usado (POST): `{jql}`")
    
    # OBTENÇÃO DE DADOS PRINCIPAL
    @st.cache_data(ttl=600)
    def load_data(jql_query):
        return buscar_dados_jira(jql_query)

    df = load_data(jql)

    # ... (código anterior)

    if df.empty:
        st.warning(f"Nenhum dado encontrado ou erro de API. Verifique as configurações e o JQL.")
    else:
               
        # --- DASHBOARD ORIGINAL (Visão Geral de Todas as Issues do Filtro) ---
        # ... (O restante do código de "Visão Geral" permanece o mesmo)

        
        # --- DASHBOARD ORIGINAL (Visão Geral de Todas as Issues do Filtro) ---
        st.markdown("---")
        st.header("📋 Quantidade de Atividades por Responsável (Visão Geral)")
        
        contagem = df["Responsável"].value_counts().reset_index()
        contagem.columns = ["Responsável", "Quantidade"]

        st.subheader("Tabela de Quantidade por Responsável (Todas as Issues)")
        st.dataframe(contagem)

        fig = px.bar(contagem, x="Responsável", y="Quantidade", color="Responsável",
                     title="Quantidade de Tasks por Responsável (Todas as Issues)", text="Quantidade")
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        max_resp = contagem.iloc[0]
        st.success(f"👑 Responsável com mais tasks: **{max_resp['Responsável']}** ({max_resp['Quantidade']} atividades)")
        
        # --- DASHBOARD DE BUGS/DEBT (BUGSprints Detalhados) ---
        st.markdown("---")
        st.header("🐞 Detalhamento de Bugsprints **Vinculados a Histórias**")
        
        tipos_bugsprint = ["BUG - SPRINT", "Débito Técnico", "Bug"]
        
        # 1. Filtra os tipos de issue (Bugs/Débitos)
        df_bugsprints = df[df["Tipo"].isin(tipos_bugsprint)].copy()
        
        # 2. NOVO FILTRO: Apenas Bugs/Débitos que estão ligados a uma história
        df_bugsprints_vinculados = df_bugsprints[
            df_bugsprints["História Relacionada (Key)"] != "Nenhuma"
        ].copy() # Criamos um novo DataFrame filtrado
        
        if not df_bugsprints_vinculados.empty:
            # Usamos df_bugsprints_vinculados para a exibição e gráficos
            df_bugsprints_display = df_bugsprints_vinculados[[
                "Chave",
                "Tipo",
                "Resumo",
                "Responsável",
                "Status",
                "História Relacionada (Key)",
                "História Relacionada (Resumo)"
            ]].rename(columns={
                "Chave": "Bugsprint",
                "Resumo": "Título do Bug",
                "História Relacionada (Key)": "História Key",
                "História Relacionada (Resumo)": "História Título"
            })
            
            st.info(f"Mostrando **{len(df_bugsprints_vinculados)}** Bugsprints vinculados ás Histórias.")
            
            st.dataframe(df_bugsprints_display, use_container_width=True, hide_index=True)
            
            st.subheader("Bugsprints Vinculados por Responsável")
            # Contagem baseada apenas nos vinculados
            contagem_bugs = df_bugsprints_vinculados["Responsável"].value_counts().reset_index()
            contagem_bugs.columns = ["Responsável", "Quantidade"]
            
            fig_bugs = px.bar(contagem_bugs, x="Responsável", y="Quantidade", color="Responsável",
                             title="Quantidade de Bugsprints vinculados por Responsável", text="Quantidade")
            fig_bugs.update_traces(textposition="outside")
            st.plotly_chart(fig_bugs, use_container_width=True)
        else:
            st.info(f"Nenhum item de 'BUG - SPRINT' encontrado que esteja **vinculado a uma História** no filtro atual. (Total de Bugs/Débitos: {len(df_bugsprints)})")
