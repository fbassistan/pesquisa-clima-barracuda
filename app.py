import hmac
import json
import logging
import threading
import time
import urllib.request
import urllib.error
import uuid
import queue
from datetime import datetime

import extra_streamlit_components as stx
import pandas as pd
import streamlit as st

# ==============================================================================
# CONFIGURAÇÃO
# ==============================================================================
st.set_page_config(page_title="Pesquisa de Clima Barracuda", page_icon="🏨", layout="centered")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pesquisa_clima")

# ➔ URL DO GOOGLE SCRIPTS E SENHA MASTER
URL_WEB_APP = "https://script.google.com/macros/s/AKfycbzvxIXvcisyDL5ljMD8gSwYwKhF_bFdvKtG2M-_D1G7Rv26-TfFd-vYR-zxJ0PNIU-XtA/exec"
SENHA_ADMIN = "RH2026"

TIMEOUT_PADRAO = 8
MAX_TENTATIVAS = 3
MAX_TENTATIVAS_LOGIN = 5
BLOQUEIO_LOGIN_SEGUNDOS = 60

cookie_manager = stx.CookieManager(key="barracuda_cookies_manager")

# Fila global e Thread-Safe para respostas pendentes (Não usar session_state aqui)
FILA_ENVIOS_PENDENTES = queue.Queue()

# ==============================================================================
# CLIENTE DE API — Comunicação com Google Apps Script
# ==============================================================================
def _chamar_api(acao_query: str = None, payload: dict = None, method: str = "GET",
                timeout: int = TIMEOUT_PADRAO, tentativas: int = 1):
    """
    Faz a chamada HTTP para o Web App do Google Scripts com Retry e Backoff.
    Retorna (sucesso: bool, dados: dict|str|None).
    """
    url = f"{URL_WEB_APP}?acao={acao_query}" if acao_query else URL_WEB_APP
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}

    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, method=method, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                bruto = res.read().decode("utf-8")
                try:
                    return True, json.loads(bruto)
                except json.JSONDecodeError:
                    return True, bruto
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultimo_erro = e
            logger.warning("Falha na chamada '%s' (tentativa %s/%s): %s", acao_query or "POST", tentativa, tentativas, e)
            if tentativa < tentativas:
                time.sleep(0.5 * tentativa)

    logger.error("Chamada '%s' falhou definitivamente: %s", acao_query or "POST", ultimo_erro)
    return False, None

@st.cache_data(ttl=30)
def buscar_rodada_ativa() -> str:
    ok, dados = _chamar_api(acao_query="buscar_rodada", tentativas=2)
    if ok and isinstance(dados, dict):
        return dados.get("rodada_atual", "pesquisa_v1")
    return "pesquisa_fallback"

def _validar_pergunta(p: dict) -> bool:
    """Garante que a pergunta vinda da nuvem possui formato correto."""
    try:
        int(p.get("id"))
    except (TypeError, ValueError):
        return False
    if p.get("tipo", "radio").strip() not in ("radio", "aberta"):
        return False
    if not str(p.get("texto", "")).strip():
        return False
    return True

@st.cache_data(ttl=300)
def buscar_perguntas_nuvem() -> list:
    ok, dados = _chamar_api(acao_query="buscar_perguntas", timeout=10, tentativas=2)
    if ok and isinstance(dados, list):
        validas = [p for p in dados if _validar_pergunta(p)]
        if len(validas) < len(dados):
            logger.warning("%s pergunta(s) descartada(s) por formato inválido.", len(dados) - len(validas))
        return validas

    # Fallback para arquivo local se estiver sem internet no carregamento inicial
    try:
        with open("perguntas.json", "r", encoding="utf-8") as f:
            dados_local = json.load(f)
            return [p for p in dados_local if _validar_pergunta(p)]
    except Exception as e:
        logger.error("Não foi possível carregar perguntas (nuvem nem local): %s", e)
        return []

@st.cache_data(ttl=10)
def buscar_adesao_nuvem() -> dict:
    ok, dados = _chamar_api(acao_query="buscar_adesao", timeout=10, tentativas=2)
    if ok and isinstance(dados, dict):
        return dados
    return {}

RODADA_ATUAL = buscar_rodada_ativa()
PERGUNTAS_RAW = buscar_perguntas_nuvem()

# Agrupa as perguntas dinâmicas em blocos temáticos
PERGUNTAS_POR_BLOCO = {}
for p in PERGUNTAS_RAW:
    bloco = p.get("bloco", "Geral").strip()
    PERGUNTAS_POR_BLOCO.setdefault(bloco, []).append({
        "id": int(p.get("id")),
        "tipo": p.get("tipo", "radio").strip(),
        "opcoes": p.get("opcoes", []),
        "texto": p.get("texto", "").strip(),
    })

LISTA_BLOCOS = list(PERGUNTAS_POR_BLOCO.keys())

# ==============================================================================
# INICIALIZAÇÃO DO SESSION STATE
# ==============================================================================
_padroes = {
    "bloco_index": -1,
    "respostas": {},
    "id_sessao": None,
    "enviado": False,
    "restaurado": False,
    "tentativas_login": 0,
    "bloqueado_ate": 0.0,
}
for chave, valor in _padroes.items():
    if chave not in st.session_state:
        st.session_state[chave] = valor

# ==============================================================================
# COOKIES & GERENCIAMENTO DE RESPOSTAS EM BACKGROUND
# ==============================================================================
def salvar_progresso_cookie():
    """Salva o progresso no navegador com chaves ESTÁTICAS para evitar pulo de tela."""
    if not cookie_manager or st.session_state.enviado:
        return
    try:
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_bloco", val=str(st.session_state.bloco_index), max_age=7776000, key="ck_save_bloco")
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_sessao", val=str(st.session_state.id_sessao), max_age=7776000, key="ck_save_sessao")
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_respostas", val=json.dumps(st.session_state.respostas), max_age=7776000, key="ck_save_respostas")
    except Exception as e:
        logger.warning("Falha ao salvar cookies de progresso: %s", e)

def limpar_cookies_progresso():
    """Bloqueia o navegador pós-envio e limpa os cookies temporários estaticamente."""
    if not cookie_manager:
        return
    try:
        cookie_manager.set(cookie=RODADA_ATUAL, val="respondido", max_age=7776000, key="ck_end_done")
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_bloco", val="", max_age=0, key="ck_end_del_bl")
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_respostas", val="", max_age=0, key="ck_end_del_re")
    except Exception as e:
        logger.warning("Falha ao limpar cookies: %s", e)

def enviar_resposta_background(payload: dict):
    """Executado na Thread: Envia a resposta avulsa. Se falhar, joga na fila Thread-Safe."""
    ok, _ = _chamar_api(payload=payload, method="POST", tentativas=MAX_TENTATIVAS)
    if not ok:
        FILA_ENVIOS_PENDENTES.put(payload)

def reenviar_pendentes():
    """Tira da fila itens pendentes e tenta enviar novamente."""
    while not FILA_ENVIOS_PENDENTES.empty():
        payload = FILA_ENVIOS_PENDENTES.get()
        threading.Thread(target=enviar_resposta_background, args=(payload,), daemon=True).start()

def auto_salvar_resposta(q_id: int, bloco: str, texto: str, tipo: str):
    ui_key = f"ui_q_{q_id}"
    valor_raw = st.session_state.get(ui_key)
    if valor_raw is None or valor_raw == "":
        return

    val_clean = str(valor_raw).strip()
    st.session_state.respostas[f"q_{q_id}"] = val_clean
    id_sessao = st.session_state.get("id_sessao")
    
    if not id_sessao:
        return

    payload = {
        "acao": "salvar_resposta_avulsa",
        "id_sessao": id_sessao,
        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "rodada": RODADA_ATUAL,
        "bloco": bloco,
        "id_pergunta": q_id,
        "enunciado": texto,
        "resposta": val_clean,
        "setor": "Geral",
    }
    
    reenviar_pendentes() # Sempre tenta limpar a fila antes de enviar um novo
    threading.Thread(target=enviar_resposta_background, args=(payload,), daemon=True).start()

# ==============================================================================
# CALLBACKS DE NAVEGAÇÃO
# ==============================================================================
def callback_iniciar_pesquisa():
    st.session_state.bloco_index = 0
    salvar_progresso_cookie()

def callback_voltar_tema():
    st.session_state.bloco_index = max(-1, st.session_state.bloco_index - 1)
    salvar_progresso_cookie()

def callback_avancar_tema():
    st.session_state.bloco_index += 1
    salvar_progresso_cookie()

# ==============================================================================
# INTERFACE GRÁFICA (UI)
# ==============================================================================
st.title("🔒 Pesquisa de Clima Organizacional")

aba_pesquisa, aba_admin = st.tabs(["📝 Responder Pesquisa", "⚙️ Painel de Controle"])

# ------------------------------------------------------------------------------
# ABA 1: FLUXO DO COLABORADOR
# ------------------------------------------------------------------------------
with aba_pesquisa:
    all_cookies = cookie_manager.get_all() if cookie_manager else {}

    if not st.session_state.restaurado and all_cookies:
        if all_cookies.get(RODADA_ATUAL) == "respondido":
            st.session_state.enviado = True
            st.session_state.restaurado = True
        else:
            saved_bloco = all_cookies.get(f"{RODADA_ATUAL}_bloco")
            saved_sessao = all_cookies.get(f"{RODADA_ATUAL}_sessao")
            saved_resp = all_cookies.get(f"{RODADA_ATUAL}_respostas")

            if saved_sessao:
                st.session_state.id_sessao = saved_sessao
            if saved_bloco is not None:
                try:
                    st.session_state.bloco_index = int(saved_bloco)
                except ValueError:
                    pass
            if saved_resp:
                try:
                    st.session_state.respostas = json.loads(saved_resp)
                except Exception:
                    pass

            if saved_bloco is not None or saved_sessao is not None or saved_resp is not None:
                st.session_state.restaurado = True

    if not st.session_state.id_sessao:
        st.session_state.id_sessao = f"S_{str(uuid.uuid4())[:8]}"

    if st.session_state.enviado:
        st.balloons()
        st.warning("### ⚠️ Participação já registrada!")
        st.info("Obrigado! Você já computou as respostas de forma 100% anônima.")

    elif not LISTA_BLOCOS:
        st.info("Carregando as perguntas... Verifique se o arquivo perguntas.json foi enviado ao GitHub.")

    else:
        # ---------------- TELA DE BOAS-VINDAS ----------------
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
            st.markdown('**🎯 Nossa Missão:** *"Proporcionar estadias transformadoras por meio da sabedoria e hospitalidade genuína dos baianos, e de experiências que promovam conexões autênticas com a natureza e a cultura local, além de contribuir com um legado positivo para Itacaré"*')
            st.markdown("**👁️ Nossa Visão:** *Consolidar-se como um destino único, reconhecido globalmente*")
            st.markdown("**💎 Nossos Valores:**\n- Excelência em hospitalidade\n- Autenticidade\n- Integridade\n- Responsabilidade socioambiental\n- Inovação")

            st.markdown("---")
            st.write("")
            st.button("📝 Iniciar Pesquisa", type="primary", use_container_width=True, on_click=callback_iniciar_pesquisa)

        # ---------------- BLOCOS DE PERGUNTAS ----------------
        else:
            bloco_nome = LISTA_BLOCOS[st.session_state.bloco_index]

            st.write(f"### {bloco_nome}")
            st.progress(st.session_state.bloco_index / len(LISTA_BLOCOS))

            if "Postura da Liderança Direta" in bloco_nome:
                st.info("ℹ️ **Importante:** As próximas perguntas são sobre seu(sua) **líder direto(a)**: a pessoa a quem você se reporta no dia a dia. Se você não ocupa cargo de liderança, refere-se ao seu supervisor(a) ou coordenador(a). Se você é supervisor(a) ou coordenador(a), refere-se ao seu gestor(a).")

            st.markdown("---")

            perguntas_atuais = PERGUNTAS_POR_BLOCO[bloco_nome]
            bloco_completo = True

            for q in perguntas_atuais:
                q_key = f"q_{q['id']}"
                ui_key = f"ui_q_{q['id']}"
                st.markdown(f"**{q['texto']}**")

                if q["tipo"] == "radio":
                    options = [str(opt).strip() for opt in q["opcoes"]]
                    saved_val = st.session_state.respostas.get(q_key)

                    # Força a pré-seleção da resposta previamente gravada
                    if saved_val and str(saved_val).strip() in options:
                        st.session_state[ui_key] = str(saved_val).strip()

                    idx_default = options.index(st.session_state[ui_key]) if ui_key in st.session_state and st.session_state[ui_key] in options else None

                    resposta = st.radio(
                        label=q["texto"], label_visibility="collapsed",
                        options=options, index=idx_default, key=ui_key,
                        on_change=auto_salvar_resposta,
                        args=(q["id"], bloco_nome, q["texto"], q["tipo"]),
                    )

                    if resposta:
                        st.session_state.respostas[q_key] = str(resposta).strip()
                    else:
                        bloco_completo = False

                elif q["tipo"] == "aberta":
                    saved_val = str(st.session_state.respostas.get(q_key, ""))
                    if saved_val and ui_key not in st.session_state:
                        st.session_state[ui_key] = saved_val

                    resposta_texto = st.text_area(
                        label=q["texto"], label_visibility="collapsed", key=ui_key,
                        on_change=auto_salvar_resposta,
                        args=(q["id"], bloco_nome, q["texto"], q["tipo"]),
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
                            payload = {
                                "acao": "concluir_pesquisa",
                                "id_sessao": st.session_state.id_sessao,
                                "rodada": RODADA_ATUAL,
                            }
                            ok, resposta_api = _chamar_api(payload=payload, method="POST", timeout=10, tentativas=MAX_TENTATIVAS)

                            sucesso = ok and isinstance(resposta_api, str) and "Success" in resposta_api
                            if sucesso:
                                limpar_cookies_progresso()
                                st.session_state.enviado = True
                                st.session_state.respostas = {}
                                st.session_state.bloco_index = -1
                                st.session_state.id_sessao = None

                                st.balloons()
                                st.success("### 🎉 Respostas enviadas com sucesso!")
                                st.info("Obrigado! Sua participação foi registrada de forma 100% anônima.")
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                st.error("Não foi possível concluir o envio agora. Verifique sua conexão e tente novamente — suas respostas continuam salvas.")
                    if not bloco_completo:
                        st.caption("⚠️ Responda a todas as questões de múltipla escolha para liberar o envio.")

# ------------------------------------------------------------------------------
# ABA 2: CONTROLE DO ADMINISTRADOR
# ------------------------------------------------------------------------------
with aba_admin:
    st.markdown("### ⚙️ Painel Administrativo")

    agora = time.time()
    if agora < st.session_state.bloqueado_ate:
        segundos_restantes = int(st.session_state.bloqueado_ate - agora)
        st.error(f"🔒 Muitas tentativas incorretas. Tente novamente em {segundos_restantes}s.")
    else:
        senha = st.text_input("Senha Master do RH:", type="password")

        senha_correta = bool(senha) and hmac.compare_digest(senha.encode('utf-8'), SENHA_ADMIN.encode('utf-8'))

        if senha and not senha_correta:
            st.session_state.tentativas_login += 1
            restantes = MAX_TENTATIVAS_LOGIN - st.session_state.tentativas_login
            if restantes <= 0:
                st.session_state.bloqueado_ate = time.time() + BLOQUEIO_LOGIN_SEGUNDOS
                st.session_state.tentativas_login = 0
                st.rerun()
            else:
                st.error(f"Senha incorreta. Tentativas restantes: {restantes}")

        elif senha_correta:
            st.session_state.tentativas_login = 0
            st.write(f"**Identificador da Pesquisa Atual:** `{RODADA_ATUAL}`")
            st.markdown("---")

            st.subheader("📊 Engajamento de Colaboradores")

            col_res, col_btn = st.columns([3, 1])
            with col_btn:
                if st.button("🔄 Atualizar Dados", use_container_width=True):
                    st.cache_data.clear()
                    st.rerun()

            dados_adesao = buscar_adesao_nuvem()
            total_participantes = sum(dados_adesao.values()) if dados_adesao else 0

            st.metric("Total de Questionários Respondidos", f"{total_participantes} colaboradores")

            if dados_adesao:
                df_adesao = pd.DataFrame(list(dados_adesao.items()), columns=["Status/Rodada", "Respostas"])
                df_adesao = df_adesao.set_index("Status/Rodada")
                st.bar_chart(df_adesao)
            else:
                st.caption("Ainda não há dados de adesão para exibir.")

            st.markdown("---")

            st.subheader("⚠️ Zona de Perigo")
            st.caption("Ao iniciar um novo ciclo, os navegadores de todos os colaboradores serão desbloqueados automaticamente para responderem à nova rodada.")

            confirmar_reset = st.checkbox("Confirmo que quero iniciar um novo ciclo (esta ação não pode ser desfeita).")
            if st.button("🔄 Iniciar Novo Ciclo de Pesquisa", type="primary", use_container_width=True, disabled=not confirmar_reset):
                ok, resposta_api = _chamar_api(payload={"acao": "virar_rodada_pesquisa"}, method="POST", tentativas=MAX_TENTATIVAS)
                if ok and isinstance(resposta_api, str) and "Success" in resposta_api:
                    st.success("O identificador mudou na nuvem! Nova pesquisa iniciada com sucesso.")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Falha ao executar reset remoto. Verifique a conexão com o Apps Script e tente novamente.")
