# app.py
import os
from pathlib import Path
import pandas as pd
import streamlit as st
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from PIL import Image
from io import BytesIO

# ==========================
# Configurações básicas
# ==========================
BASE_DIR = Path(__file__).resolve().parent
APP_TITLE = "Repositório – Rito de York"
CATALOGO_PATH = BASE_DIR / "data" / "catalogo.csv"
CONFIG_PATH = BASE_DIR / "auth_config.yaml"
CONTEUDO_DIR = BASE_DIR / "conteudo"
ASSETS_DIR = BASE_DIR / "assets"

ROLE_LEVEL = {"aprendiz": 1, "companheiro": 2, "mestre": 3}
GRAU_LEVEL = {"Aprendiz": 1, "Companheiro": 2, "Mestre": 3}

st.set_page_config(page_title=APP_TITLE, page_icon="📚", layout="wide")

# ==========================
# Utilitários de imagem (PIL)
# ==========================
def is_valid_image_file(p: Path) -> bool:
    if not p or not p.is_file():
        return False
    try:
        with Image.open(p) as im:
            im.verify()
        return True
    except Exception:
        return False

def pil_from_path(p: Path) -> Image.Image | None:
    if not is_valid_image_file(p):
        return None
    try:
        with Image.open(p) as im:
            return im.copy()
    except Exception:
        return None

def pil_fallback(width=600, height=340, color=(240, 240, 240)) -> Image.Image:
    return Image.new("RGB", (width, height), color)

def normalize_catalog_path(raw: str) -> Path:
    """
    Normaliza o texto vindo do CSV (coluna 'capa' OU 'arquivo') em um Path local.
    - troca '\' por '/'
    - corrige 'assets.' -> 'assets/' (erro comum)
    - remove './' inicial
    - se for relativo, ancora em BASE_DIR
    - fallback: tenta ASSETS_DIR/<nome_arquivo>
    """
    if not raw:
        return Path("__INVALID__")
    s = str(raw).strip()
    s = s.replace("\\", "/")
    if s.startswith("assets."):
        s = s.replace("assets.", "assets/", 1)
    if s.startswith("./"):
        s = s[2:]

    p = Path(s)
    if not p.is_absolute():
        p = BASE_DIR / s

    if p.is_file():
        return p

    # fallback para assets/<nome>
    alt = ASSETS_DIR / Path(s).name
    if alt.is_file():
        return alt

    return Path("__INVALID__")

def cover_from_csv(capa_field: str | None) -> Image.Image:
    """
    SEMPRE usa o caminho informado na coluna 'capa' do CSV.
    Se inválido/inexistente, retorna placeholder.
    """
    p = normalize_catalog_path(capa_field or "")
    if p.name != "__INVALID__":
        img = pil_from_path(p)
        if img is not None:
            return img
    return pil_fallback()

# ==========================
# Utilitários gerais
# ==========================
def atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(path)

@st.cache_data
def load_catalogo(path: Path) -> pd.DataFrame:
    REQUIRED_COLS = ["id", "titulo", "autor", "genero", "descricao",
                     "grau_minimo", "arquivo", "capa"]

    def write_template(p: Path):
        p.parent.mkdir(parents=True, exist_ok=True)
        df_start = pd.DataFrame(columns=REQUIRED_COLS)
        atomic_write_csv(df_start, p)

    # cria se não existir ou arquivo vazio
    if not path.exists() or path.stat().st_size == 0:
        write_template(path)
        return pd.read_csv(path)

    # tenta ler com vários encodings/separadores
    df = None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        for sep in (None, ",", ";", "\t"):
            try:
                df = pd.read_csv(path, sep=sep, engine="python", encoding=enc)
                break
            except Exception:
                df = None
        if df is not None:
            break

    if df is None:
        st.error("Não foi possível ler 'data/catalogo.csv'. Exibindo catálogo vazio para não sobrescrever seu arquivo.")
        return pd.DataFrame(columns=REQUIRED_COLS)

    # garante colunas obrigatórias
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    for c in missing:
        df[c] = ""

    # mantém apenas as colunas na ordem esperada
    df = df[REQUIRED_COLS]
    return df

@st.cache_data
def load_config(path: Path) -> dict:
    if not path.exists():
        st.error("Arquivo 'auth_config.yaml' não encontrado.")
        st.stop()
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=SafeLoader)

def get_user_role(config: dict, username: str, name: str | None = None, email: str | None = None) -> str:
    try:
        users = config["credentials"]["usernames"]
    except Exception:
        return "aprendiz"

    if username and username in users:
        return users[username].get("role", "aprendiz").lower()

    if email:
        for _, udata in users.items():
            if str(udata.get("email", "")).strip().lower() == str(email).strip().lower():
                return udata.get("role", "aprendiz").lower()

    if name:
        for _, udata in users.items():
            if str(udata.get("name", "")).strip().lower() == str(name).strip().lower():
                return udata.get("role", "aprendiz").lower()

    return "aprendiz"

def allowed_by_role(user_role: str, grau_minimo: str) -> bool:
    return ROLE_LEVEL.get(user_role, 1) >= GRAU_LEVEL.get(grau_minimo, 3)

def ensure_dirs():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for d in [CONTEUDO_DIR / "aprendiz", CONTEUDO_DIR / "companheiro", CONTEUDO_DIR / "mestre"]:
        d.mkdir(parents=True, exist_ok=True)

def safe_filename(name: str) -> str:
    keep = [c if c.isalnum() or c in ("-", "_", ".", " ") else "_" for c in name]
    return "".join(keep)

# ==========================
# Autenticação (compat múltiplas versões)
# ==========================
config = load_config(CONFIG_PATH)

try:
    authenticator = stauth.Authenticate(
        credentials=config["credentials"],
        cookie_name=config["cookie"]["name"],
        key=config["cookie"]["key"],
        cookie_expiry_days=config["cookie"]["expiry_days"],
    )
except TypeError:
    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

def do_login_compat():
    try:
        ret = authenticator.login(location="sidebar")
        if isinstance(ret, tuple) and len(ret) == 3:
            return ret
        return (
            st.session_state.get("name"),
            st.session_state.get("authentication_status"),
            st.session_state.get("username"),
        )
    except TypeError:
        try:
            return authenticator.login("Entrar", "sidebar")
        except TypeError:
            ret = authenticator.login("Entrar")
            if isinstance(ret, tuple) and len(ret) == 3:
                return ret
            return (
                st.session_state.get("name"),
                st.session_state.get("authentication_status"),
                st.session_state.get("username"),
            )

with st.sidebar:
    st.header("🔐 Acesso Restrito")
name, auth_status, username = do_login_compat()

if auth_status is False:
    st.error("Usuário ou senha inválidos.")
    st.stop()
elif auth_status is None:
    st.info("Informe usuário e senha para acessar o repositório.")
    st.stop()

email = st.session_state.get("email")
user_role = get_user_role(config, username, name=name, email=email)

def do_logout_compat():
    try:
        authenticator.logout(location="sidebar")
    except TypeError:
        try:
            authenticator.logout("Sair", "sidebar")
        except TypeError:
            authenticator.logout("Sair")

with st.sidebar:
    do_logout_compat()
    st.success(f"Bem-vindo, {name} — Grau: {user_role.title()}")
    st.caption(f"📁 Catálogo: {CATALOGO_PATH}")
    if st.button("Limpar cache de dados"):
        st.cache_data.clear()
        st.rerun()

ensure_dirs()

# ==========================
# Carregamento do catálogo
# ==========================
df = load_catalogo(CATALOGO_PATH)

# Normaliza valores de grau_minimo e filtra por papel
if not df.empty:
    df["grau_minimo"] = (
        df["grau_minimo"]
        .astype(str)
        .str.strip()
        .str.lower()
        .map({"aprendiz": "Aprendiz", "companheiro": "Companheiro", "mestre": "Mestre"})
        .fillna("Mestre")
    )
    df = df[df["grau_minimo"].apply(lambda g: allowed_by_role(user_role, str(g)))]

# ==========================
# Barra superior / filtros
# ==========================
st.title(APP_TITLE)
st.caption("Conteúdos exclusivamente ligados ao Rito de York, respeitando os princípios maçônicos e a segregação por grau.")

col_busca, col_genero = st.columns([2, 1])
with col_busca:
    termo = st.text_input("🔎 Buscar por título, autor ou descrição", placeholder="Ex.: Simbolismo, História, Administração...")
with col_genero:
    generos = sorted(df["genero"].dropna().unique().tolist()) if not df.empty else []
    genero_sel = st.multiselect("Gêneros", options=generos, default=[])

# Aplica filtros
if not df.empty:
    base = df.copy()
    if termo:
        t = termo.strip().lower()
        base = base[
            base.apply(
                lambda r: t in str(r["titulo"]).lower()
                or t in str(r["autor"]).lower()
                or t in str(r["descricao"]).lower(),
                axis=1,
            )
        ]
    if genero_sel:
        base = base[base["genero"].isin(genero_sel)]
else:
    base = df

# ==========================
# Renderização dos cards
# ==========================
if base.empty:
    st.warning("Nenhum conteúdo disponível para o seu grau ou filtros aplicados.")
else:
    blocos = base.groupby("genero")
    for genero, bloco in blocos:
        st.subheader(f"🎞️ {genero}")
        cards = bloco.sort_values(by=["titulo"]).to_dict(orient="records")
        ncols = 4
        rows = [cards[i : i + ncols] for i in range(0, len(cards), ncols)]
        for row in rows:
            cols = st.columns(ncols)
            for col, item in zip(cols, row):
                with col:
                    with st.container(border=True):
                        # Capa lida EXCLUSIVAMENTE do CSV
                        cover_img = cover_from_csv(item.get("capa"))
                        st.image(cover_img, use_column_width=True)

                        # Informações
                        st.markdown(f"**{item['titulo']}**")
                        st.caption(f"Autor: {item.get('autor','–')} · Grau mínimo: {item.get('grau_minimo','–')}")
                        if item.get("descricao"):
                            desc = str(item["descricao"])
                            st.write(desc[:180] + ("..." if len(desc) > 180 else ""))

                        # Download do arquivo
                        arquivo_path = normalize_catalog_path(item.get("arquivo", ""))

                        # use chaves únicas por item
                        item_id = str(item.get("id", ""))
                        dl_key  = f"dl_{item_id}"
                        na_key  = f"na_{item_id}"

                        if arquivo_path.name != "__INVALID__" and arquivo_path.is_file():
                            with open(arquivo_path, "rb") as f:
                                st.download_button(
                                    "📥 Baixar",
                                    data=f.read(),
                                    file_name=arquivo_path.name,
                                    key=dl_key,  # <-- chave única
                                )
                        else:
                            st.button("Arquivo indisponível", disabled=True, key=na_key)    
        st.divider()

# ==========================
# Área de gestão (somente Mestres)
# ==========================
st.markdown("---")
if user_role == "mestre":
    st.header("⚙️ Gestão de Conteúdo (Mestres)")
    st.write("Envie novos trabalhos e atualize o catálogo. **Atenção ao sigilo e ao grau mínimo**.")

    with st.expander("➕ Adicionar novo trabalho"):
        with st.form("form_upload"):
            titulo = st.text_input("Título do trabalho *")
            autor = st.text_input("Autor *")
            genero = st.text_input("Gênero *", placeholder="Ex.: Simbolismo, História, Administração...")
            descricao = st.text_area("Descrição *", height=120)
            grau_minimo = st.selectbox("Grau mínimo *", ["Aprendiz", "Companheiro", "Mestre"], index=0)
            arquivo = st.file_uploader(
                "Arquivo (PDF, DOCX, etc.) *",
                type=["pdf", "docx", "doc", "txt", "pptx", "xlsx"],
                accept_multiple_files=False,
            )
            capa = st.file_uploader("Capa (PNG/JPG) — será gravada e usada no CSV", type=["png", "jpg", "jpeg"], accept_multiple_files=False)
            submitted = st.form_submit_button("Salvar")

        if submitted:
            if not (titulo and autor and genero and descricao and arquivo is not None):
                st.error("Preencha todos os campos obrigatórios e selecione um arquivo.")
            else:
                CONTEUDO_DIR.mkdir(parents=True, exist_ok=True)
                pasta = CONTEUDO_DIR / grau_minimo.lower()
                pasta.mkdir(parents=True, exist_ok=True)

                # salva o arquivo de conteúdo
                nome_seguro = safe_filename(arquivo.name)
                destino = pasta / nome_seguro
                with open(destino, "wb") as f:
                    f.write(arquivo.getbuffer())

                # salva a capa SEMPRE em assets/ e grava caminho RELATIVO no CSV
                capa_destino = ""
                if capa is not None:
                    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                    capa_nome = safe_filename(capa.name)
                    capa_destino_path = ASSETS_DIR / capa_nome
                    with open(capa_destino_path, "wb") as f:
                        f.write(capa.getbuffer())
                    if is_valid_image_file(capa_destino_path):
                        capa_destino = f"assets/{capa_nome}"
                    else:
                        try:
                            capa_destino_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                        st.warning("A capa enviada não parece ser uma imagem válida. Um placeholder será exibido.")

                # atualiza o catálogo
                df_atual = load_catalogo(CATALOGO_PATH).copy()
                for c in ["id","titulo","autor","genero","descricao","grau_minimo","arquivo","capa"]:
                    if c not in df_atual.columns:
                        df_atual[c] = ""

                novo_id = int(pd.to_numeric(df_atual["id"], errors="coerce").max()) + 1 if not df_atual.empty else 1
                nova_linha = {
                    "id": novo_id,
                    "titulo": titulo,
                    "autor": autor,
                    "genero": genero,
                    "descricao": descricao,
                    "grau_minimo": grau_minimo,
                    "arquivo": str(destino).replace("\\", "/"),
                    "capa": capa_destino,  # EXCLUSIVO: o que for gravado aqui será usado na vitrine
                }
                df_atual = pd.concat([df_atual, pd.DataFrame([nova_linha])], ignore_index=True)
                atomic_write_csv(df_atual, CATALOGO_PATH)

                st.success("Trabalho salvo com sucesso!")
                st.cache_data.clear()
                st.rerun()

    with st.expander("🗂️ Catálogo (visualizar/baixar CSV)"):
        df_show = load_catalogo(CATALOGO_PATH)
        st.dataframe(df_show, use_container_width=True)
        csv_bytes = df_show.to_csv(index=False).encode("utf-8")
        st.download_button("Baixar catálogo (CSV)", data=csv_bytes, file_name="catalogo.csv", mime="text/csv")
else:
    st.info("Área de gestão disponível apenas para Mestres.")

# ==========================
# Rodapé
# ==========================
st.markdown(
    """
    ---
    **Observação:** Este repositório destina-se **exclusivamente** a estudos do **Rito de York**. 
    Respeite a legislação vigente, o sigilo maçônico e as diretrizes da Loja. Conteúdos ritualísticos práticos devem ser tratados com extremo cuidado e acesso restrito.
    """
)
