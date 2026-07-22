import streamlit as st
import extra_streamlit_components as stx
import pandas as pd
from datetime import datetime
import urllib.request
import json
import time
import hashlib
import uuid
import threading

st.set_page_config(page_title="Pesquisa de Clima Barracuda", page_icon="🏨", layout="centered")

# ➔ SUA URL DO GOOGLE SCRIPTS (Terminada em /exec)
URL_WEB_APP = "https://script.google.com/macros/s/AKfycbzvxIXvcisyDL5ljMD8gSwYwKhF_bFdvKtG2M-_D1G7Rv26-TfFd-vYR-zxJ0PNIU-XtA/exec"
SENHA_ADMIN = "RH2026"

cookie_manager = stx.CookieManager(key="barracuda_cookies_manager")

# Lista fixa de Setores
SETORES = ["RESTAURANTE / COZINHA", "BAR", "SALÃO", "RECEPÇÃO", "GOVERNANÇA", "MANUTENÇÃO", "ADMINISTRATIVO", "OUTROS"]

# ==============================================================================
# FUNÇÕES DE BUSCA DINÂMICA
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
        try:
            with open("perguntas.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

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

# Agrupa as perguntas dinâmicas em blocos temáticos lendo do JSON/Sheets
PERGUNTAS_POR_BLOCO = {}
for p in PERGUNTAS_RAW:
    bloco = p.get("bloco", "Geral").strip()
    if bloco not in PERGUNTAS_POR_BLOCO:
        PERGUNTAS_POR_BLOCO[bloco] = []
    
    PERGUNTAS_POR_BLOCO[bloco].append({
        "id": int(p.get("id")),
        "tipo": p.get("tipo", "radio").strip(),
        "opcoes": p.get("opcoes", []),
        "texto": p.get("texto", "").strip()
    })

LISTA_BLOCOS = list(PERGUNTAS_POR_BLOCO.keys())

# ==============================================================================
# INICIALIZAÇÃO DO SESSION STATE E AUTO-SALVAMENTO
# ==============================================================================
if 'bloco_index' not in st.session_state: st.session_state.bloco_index = -1
if 'respostas' not in st.session_state: st.session_state.respostas = {}
if 'setor_selecionado' not in st.session_state: st.session_state.setor_selecionado = None
if 'id_sessao' not in st.session_state: st.session_state.id_sessao = None
if 'enviado' not in st.session_state: st.session_state.enviado = False
if 'restaurado' not in st.session_state: st.session_state.restaurado = False

# Envio de resposta em segundo plano
def enviar_resposta_background(payload):
    try:
        req = urllib.request.Request(
            URL_WEB_APP, method="POST",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=5) as res:
            pass
    except Exception:
        pass

def auto_salvar_resposta(q_id, bloco, texto, tipo):
    q_key = f"ui_q_{q_id}"
    valor_raw = st.session_state.get(q_key)
    
    if valor_raw is None or valor_raw == "":
        return
        
    resposta_final = valor_raw
    st.session_state.respostas[f"q_{q_id}"] = resposta_final
    
    id_sessao = st.session_state.get("id_sessao")
    setor = st.session_state.get("setor_selecionado")
    
    if not id_sessao or not setor:
        return
        
    payload = {
        "acao": "salvar_resposta_avulsa",
        "id_sessao": id_sessao,
        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "rodada": RODADA_ATUAL,
        "bloco": bloco,
        "id_pergunta": q_id,
        "enunciado": texto,
        "resposta": resposta_final,
        "setor": setor
    }
    threading.Thread(target=enviar_resposta_background, args=(payload,), daemon=True).start()

# Callbacks de Navegação
def callback_iniciar_pesquisa():
    st.session_state.bloco_index = 0
    if cookie_manager:
        cookie_manager.set(f"{RODADA_ATUAL}_bloco", "0", key=f"btn_init_{time.time()}")

def callback_voltar_tema():
    if st.session_state.bloco_index == 0:
        st.session_state.bloco_index = -1
    else:
        st.session_state.bloco_index -= 1
    if cookie_manager:
        cookie_manager.set(f"{RODADA_ATUAL}_bloco", str(st.session_state.bloco_index), key=f"btn_back_{time.time()}")

def callback_avancar_tema():
    st.session_state.bloco_index += 1
    if cookie_manager:
        cookie_manager.set(f"{RODADA_ATUAL}_bloco", str(st.session_state.bloco_index), key=f"btn_next_{time.time()}")

st.title("🔒 Pesquisa de Clima Organizacional")

aba_pesquisa, aba_admin = st.tabs(["📝 Responder Pesquisa", "⚙️ Painel de Controle"])

# ==============================================================================
# ABA 1: FLUXO DO COLABORADOR
# ==============================================================================
with aba_pesquisa:
    cookie_status = cookie_manager.get(RODADA_ATUAL) if cookie_manager else None
    
    # TRAVA PRIORITÁRIA: Se já foi enviado nesta sessão OU se o cookie indica "respondido"
    if st.session_state.enviado or cookie_status == "respondido":
        st.balloons()
        st.warning("### ⚠️ Participação já registrada!")
        st.info("Obrigado! Seu dispositivo já computou as respostas para este ciclo de forma 100% anônima.")
        
    elif not LISTA_BLOCOS:
        st.info("Carregando as perguntas... Verifique se o arquivo perguntas.json foi enviado ao GitHub.")
    else:
        # ------------------------------------------------------------------
        # RESTAURAÇÃO DE ESTADO INTELIGENTE (APENAS PARA PESQUISAS EM ANDAMENTO)
        # ------------------------------------------------------------------
        if not st.session_state.restaurado and LISTA_BLOCOS:
            saved_respostas = cookie_manager.get(f"{RODADA_ATUAL}_respostas")
            saved_bloco = cookie_manager.get(f"{RODADA_ATUAL}_bloco")
            saved_setor = cookie_manager.get(f"{RODADA_ATUAL}_setor")
            saved_sessao = cookie_manager.get(f"{RODADA_ATUAL}_sessao_id")
            
            if saved_sessao:
                st.session_state.id_sessao = saved_sessao
            elif not st.session_state.id_sessao:
                st.session_state.id_sessao = f"S_{str(uuid.uuid4())[:8]}"
                cookie_manager.set(f"{RODADA_ATUAL}_sessao_id", st.session_state.id_sessao, key=f"set_sessao_id_{RODADA_ATUAL}")

            if saved_setor and st.session_state.setor_selecionado is None:
                st.session_state.setor_selecionado = saved_setor

            if saved_respostas and not st.session_state.respostas:
                try:
                    st.session_state.respostas = json.loads(saved_respostas)
                except Exception: pass

            # Se o cookie do bloco estiver salvo como "-1" ou não existir, fica no início
            if saved_bloco is not None:
                try:
                    idx_cookie = int(saved_bloco)
                    st.session_state.bloco_index = idx_cookie
                except ValueError:
                    st.session_state.bloco_index = -1

            st.session_state.restaurado = True

        # ------------------------------------------------------------------
        # TELA DE BOAS-VINDAS OFICIAL DO BARRACUDA (BLOCO -1)
        # ------------------------------------------------------------------
        if st.session_state.bloco_index == -1:
            st.markdown("### Seja bem-vindo(a) à nossa Pesquisa de Clima Organizacional – Ciclo 2026")
            st.write("Esta pesquisa é um espaço para você dizer, com liberdade, como está sendo a sua experiência aqui no Barracuda. Sua opinião é o que orienta decisões estratégicas sobre o que precisa melhorar e o que vale a pena manter.")
            
            st.markdown("#### 🔒 É confidencial")
            st.write("Ninguém vai saber quais foram as suas respostas individuais. Os resultados são analisados de forma consolidada, considerando toda a empresa. Ninguém terá acesso a respostas individuais nem a recortes por área ou equipe.")
            
            st.markdown("#### 🙋 É voluntária")
            st.write("Você decide se quer participar. Mas quanto mais gente responder, mais completo e representativo fica o retrato do nosso clima.")
            
            st.info("⏱️ **Leva poucos minutos.** As perguntas estão organizadas por tema e usam formatos rápidos: escalas de 1 a 5, sim ou não e alguns campos abertos para quem quiser se aprofundar.")
            st.warning("🤝 **Seja honesto(a).** Essa pesquisa só cumpre seu propósito se refletir a realidade, inclusive os pontos difíceis. Toda resposta é bem-vinda, elogio ou crítica.")
            st.success("✅ Depois da aplicação, vamos compartilhar os resultados gerais e o plano de ação. Responder à pesquisa é o primeiro passo para transformar percepção em mudança real. **Contamos com a sua participação!**")
            
            st.markdown("---")
            st.markdown("### Nossa Identidade")
            st.markdown("**🎯 Nossa Missão:** *\"Proporcionar estadias transformadoras por meio da sabedoria e hospitalidade genuína dos baianos, e de experiências que promovam conexões autênticas com a natureza e a cultura local, além de contribuir com um legado positivo para Itacaré\"*")
            st.markdown("**👁️ Nossa Visão:** *Consolidar-se como um destino único, reconhecido globalmente*")
            st.markdown("**💎 Nossos Valores:**\n- Excelência em hospitalidade\n- Autenticidade\n- Integridade\n- Responsabilidade socioambiental\n- Inovação")
            
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
            
            st.write(f"### {bloco_nome}")
            st.progress((st.session_state.bloco_index) / len(LISTA_BLOCOS))
            st.caption(f"Setor selecionado: **{st.session_state.setor_selecionado}**")
            
            if "Postura da Liderança Direta" in bloco_nome:
                st.info("ℹ️ **Importante:** As próximas perguntas são sobre seu(sua) **líder direto(a)**: a pessoa a quem você se reporta no dia a dia. Se você não ocupa cargo de liderança, refere-se ao seu supervisor(a) ou coordenador(a). Se você é supervisor(a) ou coordenador(a), refere-se ao seu gestor(a).")
            
            st.markdown("---")
            
            perguntas_atuais = PERGUNTAS_POR_BLOCO[bloco_nome]
            bloco_completo = True
            
            for q in perguntas_atuais:
                q_key = f"q_{q['id']}"
                st.markdown(f"**{q['texto']}**")
                
                if q["tipo"] == "radio":
                    valor_previo = st.session_state.respostas.get(q_key, None)
                    options = q["opcoes"]
                    idx_default = options.index(valor_previo) if valor_previo in options else None
                    
                    resposta = st.radio(
                        label=q['texto'], label_visibility="collapsed",
                        options=options, index=idx_default, key=f"ui_q_{q['id']}",
                        on_change=auto_salvar_resposta,
                        args=(q['id'], bloco_nome, q['texto'], q['tipo'])
                    )
                    if resposta:
                        st.session_state.respostas[q_key] = resposta
                    else:
                        bloco_completo = False
                        
                elif q["tipo"] == "aberta":
                    valor_previo = st.session_state.respostas.get(q_key, "")
                    resposta_texto = st.text_area(
                        label=q['texto'], label_visibility="collapsed",
                        value=valor_previo, key=f"ui_q_{q['id']}",
                        on_change=auto_salvar_resposta,
                        args=(q['id'], bloco_nome, q['texto'], q['tipo'])
                    )
                    st.session_state.respostas[q_key] = resposta_texto
                
                st.write("")
            
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
                        with st.spinner("Concluindo sua participação..."):
                            try:
                                payload = {
                                    "acao": "concluir_pesquisa",
                                    "id_sessao": st.session_state.id_sessao,
                                    "rodada": RODADA_ATUAL
                                }
                                req = urllib.request.Request(
                                    URL_WEB_APP, method="POST",
                                    data=json.dumps(payload).encode('utf-8'),
                                    headers={'Content-Type': 'application/json'}
                                )
                                with urllib.request.urlopen(req, timeout=10) as res:
                                    if "Success" in res.read().decode('utf-8'):
                                        # 1. Define o cookie principal de travamento
                                        cookie_manager.set(RODADA_ATUAL, "respondido", max_age=7776000, key=f"set_done_{RODADA_ATUAL}")
                                        
                                        # 2. Reseta os cookies temporários sobrescrevendo com estado limpo
                                        cookie_manager.set(f"{RODADA_ATUAL}_bloco", "-1", key=f"rst_bloco_{RODADA_ATUAL}")
                                        cookie_manager.set(f"{RODADA_ATUAL}_respostas", "{}", key=f"rst_resp_{RODADA_ATUAL}")
                                        cookie_manager.set(f"{RODADA_ATUAL}_setor", "", key=f"rst_setor_{RODADA_ATUAL}")
                                        
                                        # 3. Zera o Session State
                                        st.session_state.respostas = {}
                                        st.session_state.bloco_index = -1
                                        st.session_state.setor_selecionado = None
                                        st.session_state.id_sessao = None
                                        st.session_state.enviado = True
                                        st.session_state.restaurado = True
                                        st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao concluir pesquisa: {e}")
                    if not bloco_completo:
                        st.caption("⚠️ Responda a todas as questões de múltipla escolha para liberar o envio.")

# ==============================================================================
# SINCRONIZAÇÃO DE SEGURANÇA EM SEGUNDO PLANO
# ==============================================================================
if cookie_manager and not st.session_state.enviado and cookie_status != "respondido":
    if st.session_state.bloco_index >= 0:
        cookie_manager.set(f"{RODADA_ATUAL}_bloco", str(st.session_state.bloco_index), key="sync_bloco_curr")
        if st.session_state.setor_selecionado:
            cookie_manager.set(f"{RODADA_ATUAL}_setor", st.session_state.setor_selecionado, key="sync_setor_curr")
            
        respostas_str = json.dumps(st.session_state.respostas, sort_keys=True)
        respostas_hash = hashlib.md5(respostas_str.encode()).hexdigest()[:8]
        cookie_manager.set(f"{RODADA_ATUAL}_respostas", respostas_str, key=f"sync_resp_{respostas_hash}")

# ==============================================================================
# ABA 2: CONTROLE DO ADMINISTRADOR
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
