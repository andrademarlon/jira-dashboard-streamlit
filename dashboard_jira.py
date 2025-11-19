import requests
from requests.auth import HTTPBasicAuth
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime, timedelta
import os

# ==============================
# CONFIGURAÇÕES DO JIRA
# ==============================
JIRA_DOMAIN = st.secrets["jira"]["domain"]
JIRA_EMAIL = st.secrets["jira"]["email"]
JIRA_API_TOKEN = st.secrets["jira"]["api_token"]
FILTER_ID = st.secrets["jira"]["filter_id"]

# JQL FORNECIDO PELO USUÁRIO (AGORA USADO DIRETAMENTE)
JQL_DIRETO = 'project = ODR AND issuetype IN (Bug, "BUG - SPRINT", "Débito Técnico", História, Melhoria, Tarefa, "Suíte de Teste", Subteste) AND status IN (Done, "IN CODING", "READY TO DEPLOY (SDXOK)", "To Do", "EM HOMOLOGAÇÃO (SdBx)", "EM HOMOLOGAÇÃO (STG)", "Evidência DEV (STG)", "PRONTO PARA SANDBOX", "TESTE DEV (STG)", "REEXECUCAO (STG)", "REPROVADO (STG)", "EM TESTES (STG)") AND assignee IN (61327d3f98a977006b1499ca, 712020:44938e36-874b-4f7c-ad56-f58caa54b2a4, 60d322e0c90cb200686479f0, 62026e8cc4e2c9006ae5ff19, 712020:7a7bab5f-220a-4380-9987-741f797b6ca0, 62c2df061bb561c33794dfd0, 613fa2fe54762c0069281495, 5faa8fef14da2600684768e0, 5e1c688dbf70110ca24c7c73, 5e3c700e3f647d0c99d80da0, 712020:3ae7e23d-d873-4a79-8f9a-39906fb4abef, 712020:82bd015-0e9e-4064-b307-6f7a2192ef35, 6245b04af813eb00692a1beb) AND sprint = 2015 ORDER BY assignee ASC, updated DESC'

# Status que consideramos como "Entregue" para o cálculo do THROUGHPUT
STATUS_ENTREGUE = ["Concluído"]

# ID DO CAMPO PERSONALIZADO PARA REEXECUÇÕES
CAMPO_REEXECUCOES = "customfield_10651"

# ====================================================
# FUNÇÃO: buscar issues do Jira (COM AJUSTE PARA SUÍTE DE TESTE)
# ====================================================
def buscar_dados_jira(jql):
    if not JIRA_EMAIL or not JIRA_API_TOKEN:
        st.error("Credenciais de API do Jira não configuradas. Por favor, defina JIRA_EMAIL e JIRA_API_TOKEN.")
        return pd.DataFrame()

    url = f"{JIRA_DOMAIN}/rest/api/3/search/jql"
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # Incluir o campo personalizado e issuelinks
    payload = {
        "jql": jql,
        "maxResults": 1000,
        "fields": [
            "summary", "assignee", "parent", "issuelinks", "issuetype", "status", "key",
            "created", "resolutiondate",
            CAMPO_REEXECUCOES
        ]
    }
    
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)

    try:
        response = requests.post(url, headers=headers, json=payload, auth=auth, timeout=30)
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com o Jira: {e}")
        return pd.DataFrame()


    if response.status_code != 200:
        st.error(f"Erro ao buscar dados do Jira: {response.status_code}.")
        st.caption("Detalhes do erro da API (Verifique o JQL, permissões ou a sintaxe do JQL):")
        try:
            st.code(response.json())
        except:
            st.code(response.text)
        return pd.DataFrame()

    data = response.json()
    issues = data.get("issues", [])
    
    registros = []
    for issue in issues:
        key = issue.get("key", "")
        fields = issue.get("fields", {})
        resumo = fields.get("summary", "")
        issuetype = fields.get("issuetype", {}).get("name", "N/A")
        status = fields.get("status", {}).get("name", "N/A")
        
        # --- Lógica de Lead Time ---
        data_criacao_str = fields.get("created")
        data_resolucao_str = fields.get("resolutiondate")
        lead_time_dias = None
        
        if data_criacao_str and data_resolucao_str:
            try:
                data_criacao = datetime.fromisoformat(data_criacao_str.split('.')[0])
                data_resolucao = datetime.fromisoformat(data_resolucao_str.split('.')[0])
                diferenca = data_resolucao - data_criacao
                lead_time_dias = round(diferenca.total_seconds() / 86400, 1)
            except ValueError:
                pass
                
        # --- Lógica de Responsável ---
        assignee = fields.get("assignee")
        responsavel = "Sem responsável"
        if assignee and isinstance(assignee, dict):
            responsavel = assignee.get("displayName", assignee.get("accountId", "Desconhecido"))
            
        # --------------------------------------------------------------------------
        # 🚨 Lógica de Parent/História Relacionada (AJUSTADA PARA INCLUIR SUÍTE DE TESTE)
        # --------------------------------------------------------------------------
        historia_relacionada_key = "Nenhuma"
        historia_relacionada_resumo = "Nenhuma"
        parent_key = "Nenhuma"
        parent_type = "Nenhuma"
        
        suite_parent_key = "Nenhuma"


        # 1. Tenta Parent Nativo (Sub-task)
        parent = fields.get("parent")
        if parent:
            parent_key = parent.get("key", "")
            parent_type = parent.get("fields", {}).get("issuetype", {}).get("name", "N/A")
            
            # Mapeamento de História 
            if parent_type == "História":
                historia_relacionada_key = parent_key
                historia_relacionada_resumo = parent.get("fields", {}).get("summary", "")
            
            # Mapeamento de Suíte de Teste
            if parent_type == "Suíte de Teste":
                 suite_parent_key = parent_key
        
        # 2. Tenta Issuelinks (Vínculo)
        if fields.get("issuelinks"):
            for link in fields["issuelinks"]:
                # Tenta obter a issue linkada (pode ser inward ou outward)
                issue_link = link.get("inwardIssue") or link.get("outwardIssue") 
                
                if issue_link:
                    issue_link_type = issue_link.get("fields", {}).get("issuetype", {}).get("name", "N/A")
                    issue_link_key = issue_link.get("key", "")
                    
                    # 🚨 GARANTE O VÍNCULO DA HISTÓRIA
                    # Verifica se o link é para uma História e se a chave da História ainda não foi preenchida
                    if issue_link_type == "História" and historia_relacionada_key == "Nenhuma":
                        # Se a issue atual é uma Suíte de Teste, o item linkado (a História) é o Pai.
                        # Isso deve capturar ODR-9289 e ODR-9110 se estiverem linkadas a uma História.
                        if issuetype == "Suíte de Teste": 
                            historia_relacionada_key = issue_link_key
                            historia_relacionada_resumo = issue_link.get("fields", {}).get("summary", "")
                        
                        # OU se a issue atual é um item filho/bug linkado à História
                        elif parent_key == "Nenhuma": 
                            historia_relacionada_key = issue_link_key
                            historia_relacionada_resumo = issue_link.get("fields", {}).get("summary", "")
                        
                    # 🚨 GARANTE O VÍNCULO DA SUÍTE DE TESTE (para itens filhos)
                    # Se o tipo linkado é Suíte de Teste e a chave da Suíte ainda não foi preenchida
                    if issue_link_type == "Suíte de Teste" and suite_parent_key == "Nenhuma":
                        # Se a issue atual NÃO é uma Suite de Teste (ou seja, é um item filho/subteste)
                        if issuetype != "Suíte de Teste":
                           suite_parent_key = issue_link_key
                        
                # Otimização: se achamos os dois, podemos parar de buscar links
                if historia_relacionada_key != "Nenhuma" and suite_parent_key != "Nenhuma":
                    break
        # --------------------------------------------------------------------------
        # --------------------------------------------------------------------------
            
        # --- Lógica de Reexecuções (ROBUSTA) ---
        valor_reexecucoes = fields.get(CAMPO_REEXECUCOES)
        reexecucoes = 0
        
        if valor_reexecucoes is not None:
            try:
                # Tenta converter para float e depois para int (para tratar strings ou floats)
                reexecucoes = int(float(valor_reexecucoes))
            except (ValueError, TypeError):
                # Se a conversão falhar, mantém 0.
                pass
            
        registros.append({
            "ID": key,
            "Resumo": resumo,
            "Tipo": issuetype,
            "Status": status,
            "Responsável": responsavel,
            "História Relacionada (Key)": historia_relacionada_key,
            "História Relacionada (Resumo)": historia_relacionada_resumo,
            "Lead Time (Dias)": lead_time_dias,
            "Data Criação": data_criacao_str,
            "Data Resolução": data_resolucao_str,
            "Parent Key": parent_key,
            "Parent Type": parent_type,
            "Reexecuções": reexecucoes,
            "Suite Parent Key": suite_parent_key # NOVO CAMPO CHAVE
        })

    return pd.DataFrame(registros)


# ==============================
# INTERFACE STREAMLIT
# ==============================
st.set_page_config(page_title="Dashboard Jira - Bugsprints e Detalhes", layout="wide")
st.title("📊 Painel de Indicadores - Dashboard Jira - ORDER")

jql = JQL_DIRETO

if jql:
    st.caption(f"JQL Usado (POST): `{jql}`")
    
    @st.cache_data(ttl=600)
    def load_data(jql_query):
        return buscar_dados_jira(jql_query)

    df = load_data(jql)

    if df.empty:
        st.warning(f"Nenhum dado encontrado ou erro de API. Verifique as configurações, o JQL ou as credenciais.")
    else:

        # --- Conversão de Datas ---
        df["Data Criação"] = pd.to_datetime(df["Data Criação"], errors='coerce', utc=True).dt.tz_localize(None)
        df["Data Resolução"] = pd.to_datetime(df["Data Resolução"], errors='coerce', utc=True).dt.tz_localize(None)
        
        # Cria o DataFrame filtrado (exclui Subteste e Suíte de Teste para contagens gerais)
        df_principal = df[~df["Tipo"].isin(["Subteste", "Suíte de Teste"])].copy()


        # ----------------------------------------------------
        # 👑 MÉTRICAS DE DESEMPENHO (LEAD TIME & THROUGHPUT)
        # ----------------------------------------------------
        st.markdown("---")
        st.header("✨ Métricas de Desempenho da Sprint")

        df_concluido = df_principal[df_principal["Lead Time (Dias)"].notna()].copy()
        lead_time_medio = df_concluido["Lead Time (Dias)"].mean()

        # 🚨 CORREÇÃO AQUI: Usando df_principal para o Throughput
        df_entregue = df_principal[df_principal["Status"].isin(STATUS_ENTREGUE)]
        throughput_total = len(df_entregue)

        col1, col2, col3 = st.columns(3)

# ... restante do código ...
        
        with col1:
            st.subheader("Tempo Médio de Execução")
            if not pd.isna(lead_time_medio):
                st.metric(label="Lead Time Médio (Dias)", value=f"{lead_time_medio:.1f} dias")
                st.caption(f"Baseado em **{len(df_concluido)}** tarefas de valor concluídas.")
            else:
                st.info("Lead Time indisponível.")
                
        with col2:
            st.subheader("Demanda Entregue")
            st.metric(label="Itens Entregues (Throughput)", value=throughput_total)
            st.caption(f"Itens nos status: {', '.join(STATUS_ENTREGUE)}")

        with col3:
            st.subheader("Visão Geral do Filtro")
            st.metric(label="Total de Issues no Filtro", value=len(df_principal))
            st.caption("Contagem total de issues na Sprint")
            
        # ----------------------------------------------------
        # ⏳ DETALHAMENTO DAS TASKS PARA CÁLCULO DE LEAD TIME
        # ----------------------------------------------------
        st.markdown("---")
        st.header("⏳ Tasks Usadas no Cálculo do Lead Time")

        if not df_concluido.empty:
            df_lead_time_display = df_concluido[[
                "ID", "Resumo", "Tipo", "Responsável", "Data Criação",
                "Data Resolução", "Lead Time (Dias)", "Status"
            ]].sort_values(by="Lead Time (Dias)", ascending=False).reset_index(drop=True)

            st.info(f"Listando **{len(df_lead_time_display)}** tarefas que contribuíram para o Lead Time Médio de **{lead_time_medio:.1f} dias**.")

            st.dataframe(
                df_lead_time_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ID": st.column_config.TextColumn("ID"),
                    "Resumo": st.column_config.TextColumn("Resumo da Task"),
                    "Lead Time (Dias)": st.column_config.NumberColumn("Lead Time (Dias)", format="%.1f dias")
                }
            )
        else:
            st.warning("Nenhuma tarefa com Lead Time calculado foi encontrada para exibição.")

        
        # ----------------------------------------------------
        # 📋 QUANTIDADE DE ATIVIDADES POR RESPONSÁVEL (VISÃO GERAL)
        # ----------------------------------------------------
        st.markdown("---")
        st.header("📋 Quantidade de Atividades por Responsável (Visão Geral)")

        df_filtrado_resp = df_principal.copy()

        contagem = df_filtrado_resp["Responsável"].value_counts().reset_index()
        contagem.columns = ["Responsável", "Quantidade"]

        st.dataframe(contagem, use_container_width=True)

        # 1. Criação do gráfico SEM o parâmetro 'title' na chamada px.bar
        fig = px.bar(contagem, x="Responsável", y="Quantidade", color="Responsável") 

        # 2. Coloca o número dentro da barra
        fig.update_traces(texttemplate='%{y}', textposition='inside')

        # 🚨 CORREÇÃO FINAL: Configurações para remover o título e seu espaço
        fig.update_layout(
            legend_title_text=None,
            # 🎯 LINHAS CHAVES: Define o título como string vazia e remove a altura do título
            title={
                'text': "", # Define o texto do título como vazio
                'yref': 'paper', 
                'y': 1, 
                'yanchor': 'top',
                'font': {'size': 1} # Reduz o tamanho da fonte para o mínimo
            },
            
            # Ajustes de Layout
            xaxis_tickangle=-45,  # Rotação de 45 graus para os rótulos do eixo X
            # t=50 (margem superior) deve ser suficiente para acomodar a legenda
            margin=dict(b=100, t=50), 
            legend=dict(
                orientation="h",       
                yanchor="bottom",      
                y=1.02,                
                xanchor="left",        
                x=0                    
            ),
        )

        st.plotly_chart(fig, use_container_width=True)

        if not contagem.empty:
            max_resp = contagem.iloc[0]
            st.success(f"👑 Responsável com mais tasks: **{max_resp['Responsável']}** ({max_resp['Quantidade']} atividades)")     
        # -----------------------------------------------------------------------------------------------------------------------------------
        # 📚 TABELA FINAL: HISTÓRIAS COM DETALHES DA SUITE E ITENS FILHOS (TESTES)
        # -----------------------------------------------------------------------------------------------------------------------------------
        st.markdown("---")
        st.header("📚 Histórias que possuem Suites de Teste")

        # 1. Isola as Suites de Teste. REMOVEMOS O FILTRO "História Relacionada (Key)" != "Nenhuma" 
        # para garantir que as Suites ODR-9289 e ODR-9110 (e outras) sejam carregadas.
        df_suites_de_teste = df[
            (df["Tipo"] == "Suíte de Teste") 
        ].copy()

        # 2. Renomeia e seleciona colunas da Suite de Teste para o merge
        df_suites_de_teste.rename(columns={
            "ID": "Suite de Teste ID",
            "Resumo": "Suite de Teste Resumo",
            "História Relacionada (Key)": "História Vinculada (Key)", # Nova coluna auxiliar
        }, inplace=True)

        df_suites_para_merge = df_suites_de_teste[[
            "História Vinculada (Key)",
            "Suite de Teste ID",
            "Suite de Teste Resumo",
            "Responsável" # Mantém o responsável da Suíte
        ]]

        # 3. Isola as Histórias
        df_historias = df[df["Tipo"] == "História"].copy()
        # Seleciona colunas da História para o merge
        df_historias_para_merge = df_historias[["ID", "Resumo", "Responsável"]].rename(columns={
            "ID": "História ID",
            "Resumo": "História Resumo",
            "Responsável": "Responsável História"
        })

        # 4. MERGE Final: Junta Histórias com Suas Suites de Teste
        # Faz um merge 'inner' garantindo que apenas Histórias que têm Suites (via a coluna 'História Vinculada (Key)') entrem
        # E vice-versa: apenas Suites que foram mapeadas como 'filhas' de uma História.
        df_display_final = pd.merge(
            df_historias_para_merge,
            df_suites_para_merge,
            left_on="História ID",
            right_on="História Vinculada (Key)",
            how="inner"
        )

        # Ajusta a chave de merge para a contagem de subtestes
        df_display_final.rename(columns={"Suite de Teste ID": "Parent Suite ID"}, inplace=True)

        # Define os tipos de issues que são consideradas 'Pais' e não devem ser contadas como 'filhos'
        TIPOS_PAIS_A_EXCLUIR_CONTAGEM = ["História", "Suíte de Teste"] 

        # 5. Isola *todos* os itens que foram mapeados como filhos de uma Suíte de Teste
        df_itens_suite = df[
            (df["Suite Parent Key"] != "Nenhuma") &
            (~df["Tipo"].isin(TIPOS_PAIS_A_EXCLUIR_CONTAGEM))
        ].copy()

        # 6. Agrupa os Itens relacionados por sua Suíte de Teste (Suite Parent Key)
        df_itens_agrupados = df_itens_suite.groupby("Suite Parent Key").agg(
            Itens_Suite_Count=("ID", "count"),
            Soma_Reexecucoes=("Reexecuções", "sum")
        ).reset_index()

        df_itens_agrupados.rename(columns={
            "Suite Parent Key": "Parent Suite ID" # Chave para o merge
        }, inplace=True)

        # 7. MERGE Final: Junta o resultado do merge anterior (História-Suíte) com as contagens de itens filhos
        df_display_final = pd.merge(
            df_display_final,
            df_itens_agrupados,
            on="Parent Suite ID",
            how="left"
        )

        if not df_display_final.empty:
            # 8. Seleciona as colunas de exibição e formata
            df_display = df_display_final[[
                "História ID", "História Resumo", "Responsável História", "Parent Suite ID",
                "Suite de Teste Resumo", "Itens_Suite_Count", "Soma_Reexecucoes"
            ]].sort_values(by="História ID", ascending=False).reset_index(drop=True)
            
            # Formatação final
            df_display["Itens_Suite_Count"] = df_display["Itens_Suite_Count"].fillna(0).astype(int)
            df_display["Soma_Reexecucoes"] = df_display["Soma_Reexecucoes"].fillna(0).astype(int)

            st.info(f"Mostrando **{len(df_display)}** Histórias vinculados a uma Suite de Teste.")

            st.dataframe(
                df_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "História ID": st.column_config.TextColumn("ID da História"),
                    "História Resumo": st.column_config.TextColumn("Título da História"),
                    "Parent Suite ID": st.column_config.TextColumn("Suite de Teste ID"),
                    "Suite de Teste Resumo": st.column_config.TextColumn("Descrição da Suite"),
                    "Responsável História": st.column_config.TextColumn("Responsável (História)"),
                    "Itens_Suite_Count": st.column_config.NumberColumn("Qtd. Subtestes"),
                    "Soma_Reexecucoes": st.column_config.NumberColumn("Total Reexecuções")
                    }
            )
        else:
            st.warning("Nenhuma tarefa do tipo 'História' foi encontrada com uma 'Suite de Teste' vinculada no filtro atual.")
    

        # ====================================================
        # 🐞 DETALHAMENTO DE BUGSPRINTS VINCULADOS
        # ====================================================
        st.markdown("---")
        st.header("🐞 Detalhamento de Bugsprints **Vinculados a Histórias**")

        tipos_bugsprint = ["BUG - SPRINT", "Débito Técnico", "Bug"]

        df_bugsprints = df[df["Tipo"].isin(tipos_bugsprint)].copy()

        # 🚨 Mantenha a definição da variável FORA de qualquer condição adicional.
        # Se df_bugsprints estiver vazio, este filtro resultará em um DataFrame vazio,
        # mas a variável EXISTIRÁ, prevenindo o NameError.
        df_bugsprints_vinculados = df_bugsprints[
            df_bugsprints["História Relacionada (Key)"] != "Nenhuma"
        ].copy() # Esta é a linha que estava causando problemas de definição

        # Agora o teste de .empty é seguro porque a variável foi definida acima
        if not df_bugsprints_vinculados.empty: # Esta é a linha 426 (aproximadamente)
            df_bugsprints_display = df_bugsprints_vinculados[[
                "ID", "Tipo", "Resumo", "Responsável", "Status",
                "História Relacionada (Key)", "História Relacionada (Resumo)"
            ]].rename(columns={
                "ID": "ID",
                "Resumo": "Título do Bug",
                "História Relacionada (Key)": "História Principal",
                "História Relacionada (Resumo)": "Título História Principal"
            })

            st.info(f"Mostrando **{len(df_bugsprints_vinculados)}** Bugsprints vinculados a uma História.")

            st.dataframe(df_bugsprints_display, use_container_width=True, hide_index=True)

            contagem_bugs = df_bugsprints_vinculados["Responsável"].value_counts().reset_index()
            contagem_bugs.columns = ["Responsável", "Quantidade"]

            fig_bugs = px.bar(contagem_bugs, x="Responsável", y="Quantidade", color="Responsável",
                                    title="Quantidade de Bugsprints vinculados por Responsável", text="Quantidade")

            # Adicionando o fix de layout sugerido anteriormente para evitar quebras
            fig_bugs.update_layout(
                xaxis_tickangle=-45,
                margin=dict(b=150)
            )

            st.plotly_chart(fig_bugs, use_container_width=True)
        else:
            st.info(f"Nenhum item de 'BUG - SPRINT', 'Débito Técnico' ou 'Bug' encontrado que esteja **vinculado a uma História** no filtro atual.")
