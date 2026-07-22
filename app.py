import streamlit as st
import extra_streamlit_components as stx
import pandas as pd
from datetime import datetime
import urllib.request
import json
import uuid
import threading
import time

st.set_page_config(page_title="Pesquisa de Clima Barracuda", page_icon="🏨", layout="centered")

# ➔ URL DO GOOGLE SCRIPTS CORRIGIDA (Sem o 'z' incorreto)
URL_WEB_APP = "https://script.google.com/macros/s/AKfycbvxIXvcisyDL5ljMD8gSwYwKhF_bFdvKtG2M-_D1G7Rv26-TfFd-vYR-zxJ0PNIU-XtA/exec"
SENHA_ADMIN = "RH2026"

cookie_manager = stx.CookieManager(key="barracuda_cookies_manager")

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

# Agrupa as perguntas dinâmicas em blocos temáticos
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
# INICIALIZAÇÃO DO SESSION STATE
# ==============================================================================
if 'bloco_index' not in st.session_state: st.session_state.bloco_index = -1
if 'respostas' not in st.session_state: st.session_state.respostas = {}
if 'id_sessao' not in st.session_state: st.session_state.id_sessao = None
if 'enviado' not in st.session_state: st.session_state.enviado = False
if 'restaurado' not in st.session_state: st.session_state.restaurado = False

# Salva o progresso no navegador com chave ESTÁTICA
def salvar_progresso_cookie():
    if cookie_manager and not st.session_state.enviado:
        prog = {
            "bloco": st.session_state.bloco_index,
            "sessao": st.session_state.id_sessao,
            "respostas": st.session_state.respostas
        }
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_progress", val=json.dumps(prog), key="static_prog_cookie_key")

# Envio de resposta em segundo plano (Silencioso)
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
    
    if id_sessao:
        payload = {
            "acao": "salvar_resposta_avulsa",
            "id_sessao": id_sessao,
            "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "rodada": RODADA_ATUAL,
            "bloco": bloco,
            "id_pergunta": q_id,
            "enunciado": texto,
            "resposta": resposta_final,
            "setor": "Geral"
        }
        threading.Thread(target=enviar_resposta_background, args=(payload,), daemon=True).start()

# Callbacks de Navegação
def callback_iniciar_pesquisa():
    st.session_state.bloco_index = 0
    salvar_progresso_cookie()

def callback_voltar_tema():
    if st.session_state.bloco_index == 0:
        st.session_state.bloco_index = -1
    else:
        st.session_state.bloco_index -= 1
    salvar_progresso_cookie()

def callback_avancar_tema():
    st.session_state.bloco_index += 1
    salvar_progresso_cookie()

st.title("🔒 Pesquisa de Clima Organizacional")

aba_pesquisa, aba_admin = st.tabs(["📝 Responder Pesquisa", "⚙️ Painel de Controle"])

# ==============================================================================
# ABA 1: FLUXO DO COLABORADOR
# ==============================================================================
with aba_pesquisa:
    # 1. LEITURA DOS COOKIES
    all_cookies = cookie_manager.get_all() if cookie_manager else {}
    is_done_cookie = (all_cookies.get(RODADA_ATUAL) == "respondido")
    is_done_session = st.session_state.get("enviado", False)

    # 2. TRAVA ABSOLUTA DE SEGURANÇA
    if is_done_cookie or is_done_session:
        st.balloons()
        st.warning("### ⚠️ Participação já registrada!")
        st.info("Obrigado! Seu dispositivo já computou as respostas para este ciclo de forma 100% anônima.")
    
    elif not LISTA_BLOCOS:
        st.info("Carregando as perguntas... Verifique se o arquivo perguntas.json foi enviado ao GitHub.")
    else:
        # 3. RESTAURAÇÃO DE PROGRESSO PARA PESQUISAS EM ANDAMENTO
        if not st.session_state.restaurado and LISTA_BLOCOS:
            progress_raw = all_cookies.get(f"{RODADA_ATUAL}_progress")
            
            if progress_raw:
                try:
                    prog_data = json.loads(progress_raw)
                    if "respostas" in prog_data and isinstance(prog_data["respostas"], dict):
                        st.session_state.respostas = prog_data["respostas"]
                    if "sessao" in prog_data and prog_data["sessao"]:
                        st.session_state.id_sessao = prog_data["sessao"]
                    if "bloco" in prog_data and isinstance(prog_data["bloco"], int):
                        st.session_state.bloco_index = prog_data["bloco"]
                except Exception:
                    pass
            
            if not st.session_state.id_sessao:
                st.session_state.id_sessao = f"S_{str(uuid.uuid4())[:8]}"
            
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
            st.write("")
            st.button("📝 Iniciar Pesquisa", type="primary", use_container_width=True, on_click=callback_iniciar_pesquisa)

        # ------------------------------------------------------------------
        # RENDERIZAÇÃO DOS BLOCOS DE PERGUNTAS (BLOCO >= 0)
        # ------------------------------------------------------------------
        else:
            bloco_nome = LISTA_BLOCOS[st.session_state.bloco_index]
            
            st.write(f"### {bloco_nome}")
            st.progress((st.session_state.bloco_index) / len(LISTA_BLOCOS))
            
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
                                        # 1. Grava o cookie definitivo de travamento
                                        cookie_manager.set(cookie=RODADA_ATUAL, val="respondido", max_age=7776000, key=f"set_done_{RODADA_ATUAL}")
                                        
                                        # 2. Apaga o cookie temporário de progresso
                                        cookie_manager.set(cookie=f"{RODADA_ATUAL}_progress", val="", max_age=0, key=f"del_prog_{RODADA_ATUAL}")
                                        
                                        # 3. Atualiza estado local de envio
                                        st.session_state.enviado = True
                                        st.session_state.respostas = {}
                                        st.session_state.bloco_index = -1
                                        st.session_state.id_sessao = None
                                        
                                        st.balloons()
                                        st.success("### 🎉 Respostas enviadas com sucesso!")
                                        st.info("Obrigado! Sua participação foi registrada de forma 100% anônima.")
                                        time.sleep(1.5)
                                        st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao concluir pesquisa: {e}")
                    if not bloco_completo:
                        st.caption("⚠️ Responda a todas as questões de múltipla escolha para liberar o envio.")

# ==============================================================================
# ABA 2: CONTROLE DO ADMINISTRADOR
# ==============================================================================
with aba_admin:
    st.markdown("### ⚙️ Painel Administrativo")
    senha = st.text_input("Senha Master do RH:", type="password")
    
    if senha == SENHA_ADMIN:
        st.write(f"**Identificador da Pesquisa Atual:** `{RODADA_ATUAL}`")
        st.markdown("---")
        
        st.subheader("📊 Engajamento de Colaboradores")
        
        col_res, col_btn = st.columns([3, 1])
        with col_btn:
            if st.button("🔄 Atualizar Dados", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        dados_adesao = buscar_adesao_nuvem()
        total_participantes = sum(dados_adesao.values())
        
        st.metric("Total de Questionários Respondidos", f"{total_participantes} colaboradores")
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
                        st.rerun()
            except Exception as e:
                st.error(f"Falha ao executar reset remoto: {e}")
