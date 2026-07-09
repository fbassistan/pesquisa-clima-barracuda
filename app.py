import streamlit as st
import extra_streamlit_components as stx
import pandas as pd
from datetime import datetime
import urllib.request
import json
import time

st.set_page_config(page_title="Pesquisa de Clima Barracuda", page_icon="🏨", layout="centered")

# ➔ COLE AQUI A SUA URL GERADA NO GOOGLE SCRIPTS (Terminada em /exec)
URL_WEB_APP = "https://script.google.com/macros/s/AKfycbzvxIXvcisyDL5ljMD8gSwYwKhF_bFdvKtG2M-_D1G7Rv26-TfFd-vYR-zxJ0PNIU-XtA/exec"
SENHA_ADMIN = "BARRACUDARH2026"

cookie_manager = stx.CookieManager()

# Mapeamento estático das escalas para manter o app rápido e leve
ESCALAS_MAPEAMENTO = {
    "frequencia": {
        "1 - Nunca": 1, "2 - Raramente": 2, "3 - Às vezes": 3, "4 - Frequentemente": 4, "5 - Sempre": 5
    },
    "concordancia": {
        "1 - Discordo totalmente": 1, "2 - Discordo parcialmente": 2, "3 - Neutro / Indiferente": 3, 
        "4 - Concordo parcialmente": 4, "5 - Concordo totalmente": 5
    }
}

# ==============================================================================
# FUNÇÕES DE BUSCA DINÂMICA (IGUAL AO SEU APP ANTERIOR)
# ==============================================================================
@st.cache_data(ttl=30)
def buscar_rodada_ativa():
    try:
        req = urllib.request.Request(f"{URL_WEB_APP}?acao=buscar_rodada", method="GET")
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.loads(res.read().decode('utf-8')).get("rodada_atual", "pesquisa_v1")
    except Exception:
        return "pesquisa_fallback"

@st.cache_data(ttl=300)
def buscar_perguntas_nuvem():
    try:
        req = urllib.request.Request(f"{URL_WEB_APP}?acao=buscar_perguntas", method="GET")
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode('utf-8'))
    except Exception:
        return []

RODADA_ATUAL = buscar_rodada_ativa()
PERGUNTAS_RAW = buscar_perguntas_nuvem()

# Agrupa as perguntas da nuvem em blocos temáticos automaticamente
PERGUNTAS_POR_BLOCO = {}
for p in PERGUNTAS_RAW:
    bloco = p.get("bloco", "Geral").strip()
    if bloco not in PERGUNTAS_POR_BLOCO:
        PERGUNTAS_POR_BLOCO[bloco] = []
    
    PERGUNTAS_POR_BLOCO[bloco].append({
        "id": int(p.get("id")),
        "tipo": p.get("tipo", "escala").strip(),
        "escala": ESCALAS_MAPEAMENTO.get(p.get("escala_tipo", "frequencia"), ESCALAS_MAPEAMENTO["frequencia"]),
        "texto": p.get("texto", "").strip()
    })

LISTA_BLOCOS = list(PERGUNTAS_POR_BLOCO.keys())

# Inicialização do Session State para controle de navegação e respostas
if 'bloco_index' not in st.session_state: st.session_state.bloco_index = 0
if 'respostas' not in st.session_state: st.session_state.respostas = {}

st.title("🔒 Pesquisa de Clima Organizacional")

aba_pesquisa, aba_admin = st.tabs(["📝 Responder Pesquisa", "⚙️ Painel de Controle"])

# ==============================================================================
# ABA 1: COMPORTAMENTO DO QUESTIONÁRIO (COLABORADOR)
# ==============================================================================
with aba_pesquisa:
    if cookie_manager:
        # Lê o cookie para saber se este navegador já respondeu ESTA rodada específica
        cookie_status = cookie_manager.get(RODADA_ATUAL)
        
        if cookie_status == "respondido":
            st.warning("### ⚠️ Participação já registrada!")
            st.info("Obrigado! Seu dispositivo já computou as respostas para este ciclo de forma 100% anônima.")
        elif not LISTA_BLOCOS:
            st.info("Carregando o acervo de perguntas da nuvem... Certifique-se de que preencheu a aba 'Perguntas' no Sheets.")
        else:
            bloco_nome = LISTA_BLOCOS[st.session_state.bloco_index]
            
            # Cabeçalho e barra de progresso por blocos de temas
            st.write(f"### Tema: {bloco_nome}")
            st.progress((st.session_state.bloco_index) / len(LISTA_BLOCOS))
            st.markdown("---")
            
            perguntas_atuais = PERGUNTAS_POR_BLOCO[bloco_nome]
            
            # Renderização dinâmica das perguntas do bloco atual
            for q in perguntas_atuais:
                q_key = f"q_{q['id']}"
                st.markdown(f"**Questão {q['id']}.** {q['texto']}")
                
                if q["tipo"] == "escala":
                    valor_previo = st.session_state.respostas.get(q_key, None)
                    opcoes = list(q["escala"].keys())
                    idx_default = opcoes.index(valor_previo) if valor_previo in opcoes else None
                    
                    resposta = st.radio(
                        label=q['texto'], label_visibility="collapsed",
                        options=opcoes, index=idx_default, key=f"ui_{q_key}"
                    )
                    if resposta:
                        # Salva o número da resposta na memória do app
                        st.session_state.respostas[q_key] = q["escala"][resposta]
                        
                elif q["tipo"] == "aberta":
                    valor_previo = st.session_state.respostas.get(q_key, "")
                    resposta_texto = st.text_area(
                        label=q['texto'], label_visibility="collapsed",
                        value=valor_previo, key=f"ui_{q_key}"
                    )
                    st.session_state.respostas[q_key] = resposta_texto
                
                st.write("")
            
            # Botões de Navegação Inferiores
            st.markdown("---")
            col_ant, _, col_prox = st.columns([1, 1, 1])
            
            with col_ant:
                if st.session_state.bloco_index > 0:
                    if st.button("⬅️ Voltar Tema"):
                        st.session_state.bloco_index -= 1
                        st.rerun()
                        
            with col_prox:
                if st.session_state.bloco_index < len(LISTA_BLOCOS) - 1:
                    if st.button("Avançar Tema ➡️", type="primary"):
                        st.session_state.bloco_index += 1
                        st.rerun()
                else:
                    # Último bloco exibe o botão de envio final
                    if st.button("🚀 Concluir e Enviar", type="primary"):
                        with st.spinner("Enviando dados anonimamente..."):
                            dados_envio = []
                            for bloco, itens in PERGUNTAS_POR_BLOCO.items():
                                for it in itens:
                                    k_id = f"q_{it['id']}"
                                    dados_envio.append({
                                        "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
                                        "Rodada": RODADA_ATUAL,
                                        "Bloco_Tema": bloco,
                                        "ID_Pergunta": it['id'],
                                        "Enunciado": it['texto'],
                                        "Resposta": st.session_state.respostas.get(k_id, "")
                                    })
                            
                            try:
                                payload = {"acao": "salvar_pesquisa_clima", "dados": dados_envio}
                                req = urllib.request.Request(
                                    URL_WEB_APP, method="POST",
                                    data=json.dumps(payload).encode('utf-8'),
                                    headers={'Content-Type': 'application/json'}
                                )
                                with urllib.request.urlopen(req) as res:
                                    if "Success" in res.read().decode('utf-8'):
                                        # Define o cookie local de proteção contra reenvio por 90 dias
                                        cookie_manager.set(RODADA_ATUAL, "respondido", max_age=7776000)
                                        st.balloons()
                                        st.success("Respostas salvas com total anonimato!")
                                        
                                        # Limpa cache do estado para novos preenchimentos caso o PC seja compartilhado
                                        st.session_state.respostas = {}
                                        st.session_state.bloco_index = 0
                                        time.sleep(2)
                                        st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao salvar dados na nuvem: {e}")

# ==============================================================================
# ABA 2: CONTROLE DO ADMINISTRADOR (RESET)
# ==============================================================================
with aba_admin:
    st.markdown("### ⚙️ Painel Administrativo")
    senha = st.text_input("Senha Master do RH:", type="password")
    
    if senha == SENHA_ADMIN:
        st.write(f"**Identificador da Pesquisa Atual:** `{RODADA_ATUAL}`")
        if st.button("🔄 Resetar Pesquisa (Iniciar Nova Rodada)", type="primary", use_container_width=True):
            try:
                payload_reset = {"acao": "virar_rodada_pesquisa"}
                req = urllib.request.Request(
                    URL_WEB_APP, method="POST",
                    data=json.dumps(payload_reset).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req) as res:
                    if "Success" in res.read().decode('utf-8'):
                        st.success("O identificador mudou na nuvem! Todos os navegadores foram liberados.")
                        st.cache_data.clear()
                        time.sleep(2)
                        st.rerun()
            except Exception as e:
                st.error(f"Falha ao executar reset remoto: {e}")
