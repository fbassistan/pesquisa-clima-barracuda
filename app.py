import streamlit as st
import extra_streamlit_components as stx
import pandas as pd
from datetime import datetime
import urllib.request
import json
import time

st.set_page_config(page_title="Pesquisa de Clima Barracuda", page_icon="🏨", layout="centered")

URL_WEB_APP = "https://script.google.com/macros/s/AKfycbvxIXvcisyDL5ljMD8gSwYwKhF_bFdvKtG2M-_D1G7Rv26-TfFd-vYR-zxJ0PNIU-XtA/exec"
SENHA_ADMIN = "RH2026"

cookie_manager = stx.CookieManager()

# Lista fixa de Setores para enriquecer a análise do RH (Modificação 2)
SETORES = ["RESTAURANTE / COZINHA", "BAR", "SALÃO", "RECEPÇÃO", "GOVERNANÇA", "MANUTENÇÃO", "ADMINISTRATIVO", "OUTROS"]

ESCALAS_MAPEAMENTO = {
    "frequencia": {
        "1 - Nunca": 1, "2 - Raramente": 2, "3 - Às vezes": 3, "4 - Frequentemente": 4, "5 - Sempre": 5
    },
    "concordancia": {
        "1 - Discordo totalmente": 1, "2 - Discordo parcialmente": 2, "3 - Neutro / Indiferente": 3, 
        "4 - Concordo parcialmente": 4, "5 - Concordo totalmente": 5
    }
}

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

# ==============================================================================
# INICIALIZAÇÃO DO SESSION STATE
# ==============================================================================
# Modificação 3: Começa em -1 para exibir a Tela de Boas-Vindas antes das perguntas
if 'bloco_index' not in st.session_state: st.session_state.bloco_index = -1
if 'respostas' not in st.session_state: st.session_state.respostas = {}
if 'setor_selecionado' not in st.session_state: st.session_state.setor_selecionado = None
if 'progresso_carregado' not in st.session_state: st.session_state.progresso_carregado = False

st.title("🔒 Pesquisa de Clima Organizacional")

aba_pesquisa, aba_admin = st.tabs(["📝 Responder Pesquisa", "⚙️ Painel de Controle"])

# ==============================================================================
# ABA 1: FLUXO DO COLABORADOR
# ==============================================================================
with aba_pesquisa:
    if cookie_manager:
        cookie_status = cookie_manager.get(RODADA_ATUAL)
        
        if cookie_status == "respondido":
            st.warning("### ⚠️ Participação já registrada!")
            st.info("Obrigado! Seu dispositivo já computou as respostas para este ciclo de forma 100% anônima.")
        
        elif not LISTA_BLOCOS:
            st.info("Carregando o acervo de perguntas da nuvem... Certifique-se de que preencheu a aba 'Perguntas' no Sheets.")
        
        else:
            # ------------------------------------------------------------------
            # MODIFICAÇÃO 4: RECUPERAÇÃO AUTOMÁTICA DE PROGRESSO (COOKIE)
            # ------------------------------------------------------------------
            if not st.session_state.progresso_carregado:
                saved_respostas = cookie_manager.get(f"{RODADA_ATUAL}_respostas")
                saved_bloco = cookie_manager.get(f"{RODADA_ATUAL}_bloco")
                saved_setor = cookie_manager.get(f"{RODADA_ATUAL}_setor")
                
                if saved_respostas:
                    try:
                        st.session_state.respostas = json.loads(saved_respostas)
                    except: pass
                if saved_bloco is not None:
                    st.session_state.bloco_index = int(saved_bloco)
                if saved_setor:
                    st.session_state.setor_selecionado = saved_setor
                    
                st.session_state.progresso_carregado = True
                st.rerun()

            # ------------------------------------------------------------------
            # MODIFICAÇÃO 3: TELA DE BOAS-VINDAS E INSTRUÇÕES (BLOCO -1)
            # ------------------------------------------------------------------
            if st.session_state.bloco_index == -1:
                st.markdown("### Bem-vindo(a) à nossa Pesquisa Anual!")
                
                # Textos institucionais recuperados diretamente do documento de diretrizes
                st.write("A Pesquisa de Clima Organizacional é uma ferramenta usada para entender a percepção dos colaboradores sobre o ambiente de trabalho[cite: 4]. "
                         "Ela avalia aspectos como cultura da empresa, relacionamento com a liderança, satisfação com as funções, infraestrutura, benefícios e oportunidades de crescimento[cite: 5].")
                
                st.info("⏱️ **Tempo estimado:** A pesquisa leva aproximadamente 20 minutos para ser concluída. Reserve um tempo tranquilo para preenchê-la[cite: 18].")
                
                st.success("🔒 **Confidencialidade Garantida:** Nossos sistemas não coletam seu nome, e-mail ou IP. Suas respostas serão tratadas de forma 100% confidencial e analisadas apenas coletivamente[cite: 15, 16].")
                
                st.markdown("---")
                
                # --------------------------------------------------------------
                # MODIFICAÇÃO 2: COLETA DO SETOR ANÔNIMO
                # --------------------------------------------------------------
                st.markdown("#### Para começarmos, selecione o seu setor:")
                idx_setor = SETORES.index(st.session_state.setor_selecionado) if st.session_state.setor_selecionado in SETORES else None
                
                setor_atual = st.selectbox("Seu Setor/Departamento:", SETORES, index=idx_setor, placeholder="Escolha uma opção...", key="select_setor_main")
                
                if setor_atual:
                    st.session_state.setor_selecionado = setor_atual
                    cookie_manager.set(f"{RODADA_ATUAL}_setor", setor_atual)

                st.write("")
                # Validação simples: Só deixa iniciar se escolher o setor
                btn_desabilitado = True if not st.session_state.setor_selecionado else False
                
                if st.button("📝 Iniciar Pesquisa", type="primary", use_container_width=True, disabled=btn_desabilitado):
                    st.session_state.bloco_index = 0
                    cookie_manager.set(f"{RODADA_ATUAL}_bloco", "0")
                    st.rerun()
                    
                if btn_desabilitado:
                    st.caption("⚠️ Selecione o seu setor acima para liberar o botão de início.")

            # ------------------------------------------------------------------
            # RENDERIZAÇÃO DOS BLOCOS DE PERGUNTAS (BLOCO >= 0)
            # ------------------------------------------------------------------
            else:
                bloco_nome = LISTA_BLOCOS[st.session_state.bloco_index]
                
                st.write(f"### Tema: {bloco_nome}")
                st.progress((st.session_state.bloco_index) / len(LISTA_BLOCOS))
                st.caption(f"Setor selecionado: **{st.session_state.setor_selecionado}**")
                st.markdown("---")
                
                perguntas_atuais = PERGUNTAS_POR_BLOCO[bloco_nome]
                
                # Variável de controle para validação obrigatória (Modificação 1)
                bloco_completo = True
                
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
                            st.session_state.respostas[q_key] = q["escala"][resposta]
                        else:
                            # Se alguma pergunta de escala não foi respondida, o bloco não está completo
                            bloco_completo = False
                            
                    elif q["tipo"] == "aberta":
                        # Perguntas abertas são livres/opcionais conforme o manual original [cite: 8]
                        valor_previo = st.session_state.respostas.get(q_key, "")
                        resposta_texto = st.text_area(
                            label=q['texto'], label_visibility="collapsed",
                            value=valor_previo, key=f"ui_{q_key}"
                        )
                        st.session_state.respostas[q_key] = resposta_texto
                    
                    st.write("")
                
                # --------------------------------------------------------------
                # NAVEGAÇÃO INFERIOR E SALVAMENTO DE COOKIES DE PROGRESSO
                # --------------------------------------------------------------
                st.markdown("---")
                col_ant, _, col_prox = st.columns([1, 1, 1])
                
                # Salvamento preventivo em cookies sempre que houver interação
                cookie_manager.set(f"{RODADA_ATUAL}_respostas", json.dumps(st.session_state.respostas))
                
                with col_ant:
                    if st.button("⬅️ Voltar Tema"):
                        if st.session_state.bloco_index == 0:
                            st.session_state.bloco_index = -1  # Volta para as instruções
                        else:
                            st.session_state.bloco_index -= 1
                        cookie_manager.set(f"{RODADA_ATUAL}_bloco", str(st.session_state.bloco_index))
                        st.rerun()
                        
                with col_prox:
                    if st.session_state.bloco_index < len(LISTA_BLOCOS) - 1:
                        # MODIFICAÇÃO 1: Botão só fica ativo se o bloco estiver 100% preenchido
                        if st.button("Avançar Tema ➡️", type="primary", disabled=not bloco_completo):
                            st.session_state.bloco_index += 1
                            cookie_manager.set(f"{RODADA_ATUAL}_bloco", str(st.session_state.bloco_index))
                            st.rerun()
                        if not bloco_completo:
                            st.caption("⚠️ Responda a todas as questões de múltipla escolha para avançar.")
                    else:
                        # Último bloco exibe o botão de envio final
                        if st.button("🚀 Concluir e Enviar", type="primary", disabled=not bloco_completo):
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
                                            "Resposta": st.session_state.respostas.get(k_id, ""),
                                            "Setor": st.session_state.setor_selecionado # Envia o setor de forma desacoplada
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
                                            # Define o cookie definitivo de trava contra reenvio
                                            cookie_manager.set(RODADA_ATUAL, "respondido", max_age=7776000)
                                            
                                            # Limpa os cookies temporários de progresso
                                            cookie_manager.delete(f"{RODADA_ATUAL}_respostas")
                                            cookie_manager.delete(f"{RODADA_ATUAL}_bloco")
                                            cookie_manager.delete(f"{RODADA_ATUAL}_setor")
                                            
                                            st.balloons()
                                            st.success("Respostas salvas com total anonimato!")
                                            
                                            st.session_state.respostas = {}
                                            st.session_state.bloco_index = -1
                                            st.session_state.setor_selecionado = None
                                            time.sleep(2)
                                            st.rerun()
                                except Exception as e:
                                    st.error(f"Erro ao salvar dados na nuvem: {e}")
                        if not bloco_completo:
                            st.caption("⚠️ Responda a todas as questões de múltipla escolha para liberar o envio.")

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
