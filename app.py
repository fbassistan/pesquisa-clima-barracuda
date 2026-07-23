import hmac
import json
import logging
import threading
import time
import urllib.request
import urllib.error
import uuid
from datetime import datetime

import extra_streamlit_components as stx
import pandas as pd
import streamlit as st

# ==============================================================================
# CONFIGURAÇÃO E IDENTIDADE VISUAL
# ==============================================================================
st.set_page_config(page_title="Pesquisa de Clima Barracuda", page_icon="🏨", layout="centered")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pesquisa_clima")

# ➔ LINK DA SUA LOGO
URL_OU_CAMINHO_LOGO = "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRCoWtXmWKvlUcgGnpVEm56JhjQWztWcdAR6Q&s" 

# ➔ PALETA DE CORES DA EMPRESA
COR_FUNDO = "#42553f"          # Cor de Fundo da Aplicação
COR_PRIMARIA = "#6B8E23"       # Cor escura para Botões e Destaques (alta legibilidade sobre o fundo)
COR_HOVER_BOTAO = "#6B8E23"    # Cor ao passar o mouse por cima do botão

# Injeção de CSS personalizado no Streamlit
st.markdown(f"""
    <style>
    /* Cor de Fundo de toda a página */
    .stApp {{
        background-color: {COR_FUNDO} !important;
    }}
    
    /* Estilização dos Botões Principais */
    div.stButton > button[kind="primary"] {{
        background-color: {COR_PRIMARIA} !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: bold !important;
        transition: all 0.3s ease !important;
    }}
    div.stButton > button[kind="primary"]:hover {{
        background-color: {COR_HOVER_BOTAO} !important;
        transform: translateY(-1px) !important;
    }}
    
    /* Cor da Barra de Progresso */
    div.stProgress > div > div > div > div {{
        background-color: {COR_PRIMARIA} !important;
    }}
    
    /* Estilização das Abas (Tabs) */
    button[data-baseweb="tab"][aria-selected="true"] {{
        border-bottom-color: {COR_PRIMARIA} !important;
        color: {COR_PRIMARIA} !important;
        font-weight: bold !important;
    }}
    </style>
""", unsafe_allow_html=True)

# ➔ URL DO GOOGLE SCRIPTS E SENHA MASTER
URL_WEB_APP = "https://script.google.com/macros/s/AKfycbzvxIXvcisyDL5ljMD8gSwYwKhF_bFdvKtG2M-_D1G7Rv26-TfFd-vYR-zxJ0PNIU-XtA/exec"
SENHA_ADMIN = "RH2026"

TIMEOUT_PADRAO = 12
MAX_TENTATIVAS_LOGIN = 5
BLOQUEIO_LOGIN_SEGUNDOS = 60

cookie_manager = stx.CookieManager(key="barracuda_cookies_manager")

# ==============================================================================
# CLIENTE DE API — Comunicação com Google Apps Script
# ==============================================================================
def _chamar_api(acao_query: str = None, payload: dict = None, method: str = "GET",
                timeout: int = TIMEOUT_PADRAO, tentativas: int = 1):
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
    "respostas_enviadas": {},
    "id_sessao": None,
    "enviado": False,
    "restaurado": False,
    "tentativas_login": 0,
    "bloqueado_ate": 0.0,
    "envios_pendentes": [],
}
for chave, valor in _padroes.items():
    if chave not in st.session_state:
        st.session_state[chave] = valor

# ==============================================================================
# COOKIES & GERENCIAMENTO DE RESPOSTAS
# ==============================================================================
def salvar_progresso_cookie():
    if not cookie_manager or st.session_state.enviado:
        return
    try:
        now_ts = str(time.time())
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_bloco", val=str(st.session_state.bloco_index),
                           max_age=7776000, key=f"ck_bl_{now_ts}")
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_sessao", val=str(st.session_state.id_sessao),
                           max_age=7776000, key=f"ck_se_{now_ts}")
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_respostas", val=json.dumps(st.session_state.respostas),
                           max_age=7776000, key=f"ck_re_{now_ts}")
    except Exception as e:
        logger.warning("Falha ao salvar cookies de progresso: %s", e)


def limpar_cookies_progresso():
    if not cookie_manager:
        return
    try:
        now_end = str(time.time())
        cookie_manager.set(cookie=RODADA_ATUAL, val="respondido", max_age=7776000, key=f"ck_done_{now_end}")
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_bloco", val="", max_age=0, key=f"ck_del_bl_{now_end}")
        cookie_manager.set(cookie=f"{RODADA_ATUAL}_respostas", val="", max_age=0, key=f"ck_del_re_{now_end}")
    except Exception as e:
        logger.warning("Falha ao limpar cookies: %s", e)


def _enviar_resposta_background_sem_retry(payload: dict):
    ok, _ = _chamar_api(payload=payload, method="POST", timeout=12, tentativas=1)
    if not ok:
        st.session_state.envios_pendentes.append(payload)


def reenviar_pendentes():
    if not st.session_state.envios_pendentes:
        return
    pendentes = list(st.session_state.envios_pendentes)
    st.session_state.envios_pendentes = []
    for payload in pendentes:
        threading.Thread(target=_enviar_resposta_background_sem_retry, args=(payload,), daemon=True).start()


def salvar_resposta_se_necessario(q_id: int, bloco: str, texto: str, val_clean: str, assincrono: bool = True):
    if not val_clean or not str(val_clean).strip():
        return

    val_clean = str(val_clean).strip()
    q_key = f"q_{q_id}"
    id_sessao = st.session_state.get("id_sessao")
    if not id_sessao:
        return

    if st.session_state.respostas_enviadas.get(q_key) == val_clean:
        return

    st.session_state.respostas_enviadas[q_key] = val_clean
    st.session_state.respostas[q_key] = val_clean

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

    if assincrono:
        reenviar_pendentes()
        threading.Thread(target=_enviar_resposta_background_sem_retry, args=(payload,), daemon=True).start()
    else:
        _chamar_api(payload=payload, method="POST", timeout=12, tentativas=1)


def auto_salvar_resposta(q_id: int, bloco: str, texto: str, tipo: str):
    ui_key = f"ui_q_{q_id}"
    valor_raw = st.session_state.get(ui_key)
    if valor_raw is not None and str(valor_raw).strip() != "":
        salvar_resposta_se_necessario(q_id, bloco, texto, str(valor_raw).strip(), assincrono=True)


def garantir_todas_respostas_salvas():
    for q in PERGUNTAS_RAW:
        q_id = int(q["id"])
        q_key = f"q_{q_id}"
        val = st.session_state.respostas.get(q_key)
        if val and str(val).strip():
            bloco_nome = q.get("bloco", "Geral").strip()
            salvar_resposta_se_necessario(q_id, bloco_nome, q.get("texto", "").strip(), str(val).strip(), assincrono=False)


def verificar_bloco_completo(blocos_perguntas: list) -> bool:
    for q in blocos_perguntas:
        q_id = int(q["id"])
        ui_key = f"ui_q_{q_id}"
        q_key = f"q_{q_id}"
        val = st.session_state.get(ui_key) or st.session_state.respostas.get(q_key, "")
        if not val or not str(val).strip():
            return False
    return True


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

# Cabeçalho com Logo Pequena na Lateral Esquerda ao Lado do Título
col_logo, col_titulo = st.columns([1, 5])
with col_logo:
    try:
        st.image(URL_OU_CAMINHO_LOGO, width=80)
    except Exception:
        pass

with col_titulo:
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
                    st.session_state.respostas_enviadas = {
                        k: str(v).strip() for k, v in st.session_state.respostas.items() if v
                    }
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

            for q in perguntas_atuais:
                q_id = int(q["id"])
                q_key = f"q_{q_id}"
                ui_key = f"ui_q_{q_id}"
                st.markdown(f"**{q['texto']}**")

                if q["tipo"] == "radio":
                    options = [str(opt).strip() for opt in q["opcoes"]]
                    saved_val = st.session_state.respostas.get(q_key)

                    if saved_val and str(saved_val).strip() in options and ui_key not in st.session_state:
                        st.session_state[ui_key] = str(saved_val).strip()

                    idx_default = options.index(st.session_state[ui_key]) if ui_key in st.session_state and st.session_state[ui_key] in options else None

                    resposta = st.radio(
                        label=q["texto"], label_visibility="collapsed",
                        options=options, index=idx_default, key=ui_key,
                        on_change=auto_salvar_resposta,
                        args=(q_id, bloco_nome, q["texto"], q["tipo"]),
                    )

                    if resposta:
                        st.session_state.respostas[q_key] = str(resposta).strip()

                elif q["tipo"] == "aberta":
                    saved_val = str(st.session_state.respostas.get(q_key, ""))
                    if saved_val and ui_key not in st.session_state:
                        st.session_state[ui_key] = saved_val

                    resposta_texto = st.text_area(
                        label=q["texto"], label_visibility="collapsed", key=ui_key,
                        on_change=auto_salvar_resposta,
                        args=(q_id, bloco_nome, q["texto"], q["tipo"]),
                    )

                    if resposta_texto and resposta_texto.strip():
                        st.session_state.respostas[q_key] = resposta_texto.strip()
                    else:
                        st.session_state.respostas[q_key] = ""

                st.write("")

            st.markdown("---")
            col_ant, _, col_prox = st.columns([1, 1, 1])

            with col_ant:
                st.button("⬅️ Voltar Tema", on_click=callback_voltar_tema)

            with col_prox:
                bloco_pronto = verificar_bloco_completo(perguntas_atuais)

                if st.session_state.bloco_index < len(LISTA_BLOCOS) - 1:
                    if st.button("Avançar Tema ➡️", type="primary"):
                        if bloco_pronto:
                            callback_avancar_tema()
                            st.rerun()
                        else:
                            st.warning("⚠️ Responda a todas as perguntas deste bloco (incluindo o campo de texto) para avançar.")
                else:
                    if st.button("🚀 Concluir e Enviar", type="primary"):
                        if bloco_pronto:
                            with st.spinner("Concluindo sua participação..."):
                                garantir_todas_respostas_salvas()
                                payload = {
                                    "acao": "concluir_pesquisa",
                                    "id_sessao": st.session_state.id_sessao,
                                    "rodada": RODADA_ATUAL,
                                }
                                ok, resposta_api = _chamar_api(payload=payload, method="POST", timeout=12, tentativas=1)

                                sucesso = ok and isinstance(resposta_api, str) and "Success" in resposta_api
                                if sucesso:
                                    limpar_cookies_progresso()
                                    st.session_state.enviado = True
                                    st.session_state.respostas = {}
                                    st.session_state.respostas_enviadas = {}
                                    st.session_state.bloco_index = -1
                                    st.session_state.id_sessao = None

                                    st.balloons()
                                    st.success("### 🎉 Respostas enviadas com sucesso!")
                                    st.info("Obrigado! Sua participação foi registrada de forma 100% anônima.")
                                    time.sleep(1.5)
                                    st.rerun()
                                else:
                                    st.error("Não foi possível concluir o envio agora. Verifique sua conexão e tente novamente — suas respostas continuam salvas.")
                        else:
                            st.warning("⚠️ Responda a todas as perguntas deste bloco (incluindo o campo de texto) para concluir.")

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

        senha_correta = bool(senha) and hmac.compare_digest(senha, SENHA_ADMIN)

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
                ok, resposta_api = _chamar_api(payload={"acao": "virar_rodada_pesquisa"}, method="POST", tentativas=1)
                if ok and isinstance(resposta_api, str) and "Success" in resposta_api:
                    st.success("O identificador mudou na nuvem! Nova pesquisa iniciada com sucesso.")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Falha ao executar reset remoto. Verifique a conexão com o Apps Script e tente novamente.")
