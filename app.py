import streamlit as st
import extra_streamlit_components as stx
import pandas as pd
from datetime import datetime
import urllib.request
import json
import time
import hashlib

st.set_page_config(page_title="Pesquisa de Clima Barracuda", page_icon="🏨", layout="centered")

# ➔ SUA URL DO GOOGLE SCRIPTS (Terminada em /exec)
URL_WEB_APP = "https://script.google.com/macros/s/AKfycbzvxIXvcisyDL5ljMD8gSwYwKhF_bFdvKtG2M-_D1G7Rv26-TfFd-vYR-zxJ0PNIU-XtA/exec"
SENHA_ADMIN = "RH2026"

# Inicializa o gerenciador de cookies com chave persistente
cookie_manager = stx.CookieManager(key="barracuda_cookies_manager")

# Lista fixa de Setores
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

# ==============================================================================
# FUNÇÕES DE BUSCA DINÂMICA (COM FALLBACK LOCAL NO JSON EXTERNO)
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
    except Exception as e:
        try:
            with open("perguntas.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

# Busca o resumo de adesão de forma agregada e anônima
@st.cache_data(ttl=10)
def buscar_adesao_nuvem():
    try:
        req = urllib.request.Request(f"{URL_WEB_APP}?acao=buscar_adesao", method="GET")
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode('utf-8'))
    except Exception:
        return {}

RODADA_ATUAL = buscar_rodada_ativa()
PERGUNTAS_RAW = buscar_perguntas_nuvem()

# Agrupa as perguntas dinâmicas em blocos temáticos
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
# INICIALIZAÇÃO DO SESSION STATE E CALLBACKS DE NAVEGAÇÃO
# ==============================================================================
if 'bloco_index' not in st.session_state: st.session_state.bloco_index = -1
if 'respostas' not in st.session_state: st.session_state.respostas = {}
if 'setor_selecionado' not in st.session_state: st.session_state.setor_selecionado = None
if 'enviado' not in st.session_state: st.session_state.enviado = False

def callback_iniciar_pesquisa():
    st.session_state.bloco_index = 0

def callback_voltar_tema():
    if st.session_state.bloco_index == 0:
        st.session_state.bloco_index = -1
    else:
        st.session_state.bloco_index -= 1

def callback_avancar_tema():
    st.session_state.bloco_index += 1

st.title("🔒 Pesquisa de Clima Organizacional")

aba_pesquisa, aba_admin = st.tabs(["📝 Responder Pesquisa", "⚙️ Painel de Controle"])

# ==============================================================================
# ABA 1: COMPORTAMENTO DO QUESTIONÁRIO (COLABORADOR)
# ==============================================================================
with aba_pesquisa:
    if st.session_state.enviado:
        st.balloons()
        st.success("### 🎉 Respostas enviadas com sucesso!")
        st.info("Obrigado! Sua participação foi registrada de forma 100% anônima e segura. Você já pode fechar esta aba.")
    
    elif cookie_manager:
        cookie_status = cookie_manager.get(RODADA_ATUAL)
        
        if cookie_status == "respondido":
            st.warning("### ⚠️ Participação já registrada!")
            st.info("Obrigado! Seu dispositivo já computou as respostas para este ciclo de forma 100% anônima.")
        elif not LISTA_BLOCOS:
            st.info("Carregando as perguntas... Verifique se o arquivo perguntas.json foi enviado ao GitHub.")
        else:
            # ------------------------------------------------------------------
            # RECUPERAÇÃO AUTOMÁTICA DE PROGRESSO
            # ------------------------------------------------------------------
            saved_respostas = cookie_manager.get(f"{RODADA_ATUAL}_respostas")
            saved_bloco = cookie_manager.get(f"{RODADA_ATUAL}_bloco")
            saved_setor = cookie_manager.get(f"{RODADA_ATUAL}_setor")
            
            if saved_respostas and not st.session_state.respostas:
                try:
                    st.session_state.respostas = json.loads(saved_respostas)
                except Exception: pass
            if saved_bloco is not None and st.session_state.bloco_index == -1:
                st.session_state.bloco_index = int(saved_bloco)
            if saved_setor and st.session_state.setor_selecionado is None:
                st.session_state.setor_selecionado = saved_setor

            # ------------------------------------------------------------------
            # TELA DE BOAS-VINDAS E INSTRUÇÕES (BLOCO -1)
            # ------------------------------------------------------------------
            if st.session_state.bloco_index == -1:
                st.markdown("### Bem-vindo(a) à nossa Pesquisa Anual!")
                st.write("A Pesquisa de Clima Organizacional é uma ferramenta usada para entender a percepção dos colaboradores sobre o ambiente de trabalho. "
                         "Ela avalia aspectos como cultura da empresa, relacionamento com a liderança, satisfação com as funções, infraestrutura, benefícios e oportunidades de crescimento.")
                st.info("⏱️ **Tempo estimado:** A pesquisa leva aproximadamente 20 minutos para ser concluída. Reserve um tempo tranquilo para preenchê-la.")
                st.success("🔒 **Confidencialidade Garantida:** Nossos sistemas não coletam seu nome, e-mail ou IP. Suas respostas serão tratadas de forma 100% confidencial e analisadas apenas coletivamente.")
                st.markdown("---")
                
                st.markdown("#### Para começarmos, selecione o seu setor:")
                idx_setor = SETORES.index(st.session_state.setor_selecionado) if st.session_state.setor_selecionado in SETORES else None
                
                setor_atual = st.selectbox("Seu Setor/Departamento:", SETORES, index=idx_setor, placeholder="Escolha uma opção...", key="select_setor_main")
                
                if setor_atual:
                    st.session_state.setor_selecionado = setor_atual

                st.write("")
                btn_desabilitado = True if not st.session_state.setor_selecionado else False
                
                st.button("📝 Iniciar Pesquisa", type="primary", use_container_width=True, disabled=btn_desabilitado, on_click=callback_iniciar_pesquisa)
                    
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
                bloco_completo = True
                
                for q in perguntas_atuais:
                    q_key = f"q_{q['id']}"
                    st.markdown(f"**Questão {q['id']}.** {q['texto']}")
                    
                    if q["tipo"] == "escala":
                        valor_previo = st.session_state.respostas.get(q_key, None)
                        options = list(q["escala"].keys())
                        idx_default = options.index(valor_previo) if valor_previo in options else None
                        
                        resposta = st.radio(
                            label=q['texto'], label_visibility="collapsed",
                            options=options, index=idx_default, key=f"ui_{q_key}"
                        )
                        if resposta:
                            st.session_state.respostas[q_key] = q["escala"][resposta]
                        else:
                            bloco_completo = False
                            
                    elif q["tipo"] == "aberta":
                        valor_previo = st.session_state.respostas.get(q_key, "")
                        resposta_texto = st.text_area(
                            label=q['texto'], label_visibility="collapsed",
                            value=valor_previo, key=f"ui_{q_key}"
                        )
                        st.session_state.respostas[q_key] = resposta_texto
                    
                    st.write("")
                
                # --------------------------------------------------------------
                # NAVEGAÇÃO INFERIOR
                # --------------------------------------------------------------
                st.markdown("---")
                col_ant, _, col_prox = st.columns([1, 1, 1])
                
                with col_ant:
                    st.button("⬅️ Voltar Tema", on_click=callback_voltar_tema)
                        
                with col_prox:
                    if st.session_state.bloco_index < len(LISTA_BLOCOS) - 1:
                        st.button("Avançar Tema ➡️", type="primary", disabled=not bloco_completo, on_click=callback_avancar_tema)
                        if not bloco_completo:
                            st.caption("⚠️ Responda a todas as questões de múltipla escolha para avançar.")
                    else:
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
                                            "Setor": st.session_state.setor_selecionado
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
                                            # 1. Trava o reenvio usando chaves exclusivas no navegador
                                            cookie_manager.set(RODADA_ATUAL, "respondido", max_age=7776000, key=f"set_respondido_final_{RODADA_ATUAL}")
                                            
                                            # 2. Deleta os cookies temporários de progresso de forma silenciosa
                                            for temp_cookie in [f"{RODADA_ATUAL}_respostas", f"{RODADA_ATUAL}_bloco", f"{RODADA_ATUAL}_setor"]:
                                                try:
                                                    cookie_manager.delete(temp_cookie, key=f"del_{temp_cookie}")
                                                except Exception:
                                                    pass
                                            
                                            # 3. Limpa a memória interna e altera o estado para Sucesso
                                            st.session_state.respostas = {}
                                            st.session_state.bloco_index = -1
                                            st.session_state.setor_selecionado = None
                                            st.session_state.enviado = True
                                            
                                except Exception as e:
                                    st.error(f"Erro ao salvar dados na nuvem: {e}")
                        if not bloco_completo:
                            st.caption("⚠️ Responda a todas as questões de múltipla escolha para liberar o envio.")

# ==============================================================================
# SINCRONIZAÇÃO EM TEMPO REAL DE COOKIES DE PROGRESSO (AO FINAL DA RENDERIZAÇÃO)
# ==============================================================================
if cookie_manager and not st.session_state.enviado and cookie_status != "respondido":
    if st.session_state.bloco_index >= 0:
        # Salva o Bloco Atual no Cookie
        cookie_manager.set(
            f"{RODADA_ATUAL}_bloco", 
            str(st.session_state.bloco_index), 
            key=f"sync_bloco_{st.session_state.bloco_index}"
        )
        
        # Salva o Setor no Cookie
        if st.session_state.setor_selecionado:
            cookie_manager.set(
                f"{RODADA_ATUAL}_setor", 
                st.session_state.setor_selecionado, 
                key=f"sync_setor_{st.session_state.setor_selecionado}"
            )
            
        # Salva as Respostas Atuais no Cookie (Gerando Hash única para atualizar dinamicamente)
        respostas_str = json.dumps(st.session_state.respostas, sort_keys=True)
        respostas_hash = hashlib.md5(respostas_str.encode()).hexdigest()[:8]
        cookie_manager.set(
            f"{RODADA_ATUAL}_respostas", 
            respostas_str, 
            key=f"sync_respostas_{respostas_hash}"
        )

# ==============================================================================
# ABA 2: CONTROLE DO ADMINISTRADOR (RESET + GRÁFICO DE ADESÃO)
# ==============================================================================
with aba_admin:
    st.markdown("### ⚙️ Painel Administrativo")
    senha = st.text_input("Senha Master do RH:", type="password")
    
    if senha == SENHA_ADMIN:
        st.write(f"**Identificador da Pesquisa Atual:** `{RODADA_ATUAL}`")
        st.markdown("---")
        
        st.subheader("📊 Adesão de Colaboradores por Setor")
        
        col_res, col_btn = st.columns([3, 1])
        with col_btn:
            if st.button("🔄 Atualizar Dados", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        dados_adesao = buscar_adesao_nuvem()
        total_participantes = sum(dados_adesao.values())
        
        st.metric("Total de Questionários Respondidos", f"{total_participantes} colaboradores")
        
        adesao_completa = {setor: dados_adesao.get(setor, 0) for setor in SETORES}
        df_adesao = pd.DataFrame(list(adesao_completa.items()), columns=["Setor", "Respondidos"])
        df_adesao = df_adesao.set_index("Setor")
        
        st.bar_chart(df_adesao)
        st.markdown("---")
        
        st.subheader("⚠️ Zona de Perigo")
        st.caption("Ao iniciar um novo ciclo, os navegadores de todos os colaboradores serão desbloqueados automaticamente para responderem à nova rodada.")
        if st.button("🔄 Iniciar Novo Ciclo de Pesquisa", type="primary", use_container_width=True):
            try:
                payload_reset = {"acao": "virar_rodada_pesquisa"}
                req = urllib.request.Request(
                    URL_WEB_APP, method="POST",
                    data=json.dumps(payload_reset).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req) as res:
                    if "Success" in res.read().decode('utf-8'):
                        st.success("O identificador mudou na nuvem! Nova pesquisa iniciada com sucesso.")
                        st.cache_data.clear()
                        time.sleep(2)
                        st.rerun()
            except Exception as e:
                st.error(f"Falha ao executar reset remoto: {e}")
