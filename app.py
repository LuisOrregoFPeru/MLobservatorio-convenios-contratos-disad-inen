"""Tablero de seguimiento de convenios DISAD, INEN."""
from __future__ import annotations

import base64
import textwrap
import io
import json
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from consultas import EJEMPLOS, responder_ia, responder_local
from core import (BASE, COLORES, ORDEN_ESTADO, PDFS, accion_sugerida, cargar_beneficios, cargar_convenios,
                  config_correo, enviar_correo, hoy, html_alerta, seleccionar_alertas)

st.set_page_config(page_title="Observatorio de convenios y contratos | INEN", page_icon="📑", layout="wide")

# ---------------------------------------------------------------- compatibilidad entre versiones de Streamlit
try:
    _V = tuple(int(x) for x in st.__version__.split(".")[:2])
except Exception:  # noqa: BLE001
    _V = (1, 0)
ANCHO = {"width": "stretch"} if _V >= (1, 50) else {"use_container_width": True}


def grafico(fig, key):
    st.plotly_chart(fig, key=key, config={"displayModeBar": False}, **ANCHO)


def tabla(df, **kw):
    st.dataframe(df, hide_index=True, **ANCHO, **kw)


def boton_descarga(label, data, file_name, mime, key):
    st.download_button(label, data, file_name=file_name, mime=mime, key=key, **ANCHO)


def ventana(label):
    """Popover si existe; si no, expander."""
    return st.popover(label, **ANCHO) if hasattr(st, "popover") and _V >= (1, 50) else (
        st.popover(label) if hasattr(st, "popover") else st.expander(label))


# ---------------------------------------------------------------- datos
HOY = hoy()
URL_APP = "https://mlobservatorio-convenios-contratos-disad-inen.streamlit.app/"
df = cargar_convenios(HOY)
ben = cargar_beneficios().set_index("id")
IND = json.loads((BASE / "data" / "indicadores.json").read_text(encoding="utf-8"))
df["inicio_periodo"] = pd.to_datetime(df["inicio_periodo"]).dt.date
df["avance"] = [min(1.0, max(0.0, (HOY - i).days / max(1, (f - i).days))) for i, f in zip(df["inicio_periodo"], df["fin"])]
CORTO = dict(zip(df["id"], df["corto"]))
LOGOS = BASE / "logos"
COLOR_SIN_LOGO = {"ONCOSALUD": "#00A651"}
PAGO = {x["id"]: x for x in IND["prestacionales"]}


@st.cache_data
def _b64(p: str) -> str:
    return base64.b64encode(Path(p).read_bytes()).decode()


def logo_html(id_: str, h: int = 54, url: str = "") -> str:
    p = LOGOS / f"{id_}.png"
    if url:
        src = url
    elif p.exists():
        src = f"data:image/png;base64,{_b64(str(p))}"
    else:
        col = COLOR_SIN_LOGO.get(id_, "#475467")
        return (f"<div style='height:{h}px;display:flex;align-items:center'><span style='background:{col};color:#fff;"
                f"font-weight:800;font-size:{h*0.38:.0f}px;padding:4px 12px;border-radius:8px'>{CORTO.get(id_, id_)}</span></div>")
    return f"<img src='{src}' style='max-height:{h}px;max-width:100%;object-fit:contain'>"


st.markdown(
    """
    <style>
    .block-container {padding-top: 3.2rem;}
    .kpi {border-radius:12px;padding:14px 18px;color:#fff}
    .kpi .n {font-size:2.2rem;font-weight:800;line-height:1}
    .kpi .l {font-size:.85rem;opacity:.95;margin-top:4px}
    .card-top {display:flex;justify-content:space-between;align-items:center;gap:8px;min-height:62px}
    .pill {display:inline-block;padding:2px 10px;border-radius:999px;color:#fff;font-size:.75rem;font-weight:700}
    .big {font-size:2.4rem;font-weight:800;line-height:1}
    .muted {opacity:.65;font-size:.8rem}
    .bar {height:8px;border-radius:6px;background:rgba(128,128,128,.2);overflow:hidden;margin:6px 0 2px}
    .bar > div {height:100%}
    .chip {display:inline-block;background:rgba(21,112,239,.1);color:#175CD3;border-radius:6px;padding:2px 8px;
           margin:2px 4px 2px 0;font-size:.78rem;font-weight:600}
    [class*="st-key-ej_"] button {justify-content:flex-start !important; text-align:left !important; width:100%;
                                  padding-left:0 !important; min-height:0 !important; border:none !important;
                                  background:transparent !important; box-shadow:none !important}
    [class*="st-key-ej_"] button div, [class*="st-key-ej_"] button p {text-align:left !important; justify-content:flex-start !important;
                                  width:100%}
    [class*="st-key-ej_"] button p {color:#175CD3; font-style:italic}
    .perfil {border-left:5px solid #1570EF;padding:8px 12px;border-radius:8px;background:rgba(21,112,239,.05);height:100%}
    </style>
    """,
    unsafe_allow_html=True,
)


def kpis(d: pd.DataFrame) -> None:
    cols = st.columns(5)
    vals = [("Total", len(d), "#344054")] + [(e, int((d["estado"] == e).sum()), COLORES[e]) for e in ORDEN_ESTADO]
    for c, (lab, n, col) in zip(cols, vals):
        c.markdown(f"<div class='kpi' style='background:{col}'><div class='n'>{n}</div><div class='l'>{lab}</div></div>",
                   unsafe_allow_html=True)


def tarjeta(r) -> None:
    col = COLORES[r["estado"]]
    dias = r["dias_venc"]
    txt_dias = f"{dias}" if dias >= 0 else f"{-dias}"
    sub = "días para vencer" if dias >= 0 else "días vencido"
    icono = "🔁 Automática" if r["renovacion"].startswith("Automática") else (
        "🤝 En negociación" if "negociación" in r["renovacion"] else "✍️ Requiere acción")
    with st.container(border=True):
        st.markdown(
            f"<div class='card-top'><div style='flex:1'>{logo_html(r['id'], 54, r.get('logo_url', ''))}</div>"
            f"<span class='pill' style='background:{col}'>{r['estado']}</span></div>"
            f"<div style='font-weight:700;margin-top:6px'>{r['corto']}</div>"
            f"<div class='muted' style='min-height:34px'>{r['objeto_corto']}</div>"
            f"<div style='display:flex;justify-content:space-between;align-items:flex-end;margin-top:8px'>"
            f"<div><span class='big' style='color:{col}'>{txt_dias}</span><div class='muted'>{sub}</div></div>"
            f"<div style='text-align:right' class='muted'>Vence <b>{r['fin']:%d/%m/%Y}</b><br>Aviso hasta {r['limite_aviso']:%d/%m/%Y}"
            f"<br>{icono}</div></div>"
            f"<div class='bar'><div style='width:{r['avance']*100:.0f}%;background:{col}'></div></div>"
            f"<div class='muted'>{r['avance']*100:.0f}% del periodo vigente transcurrido</div>",
            unsafe_allow_html=True,
        )
        b1, b2 = st.columns(2)
        with b1:
            pdf = PDFS / r["pdf"]
            if pdf.exists():
                boton_descarga(f"⬇️ {r.get('pdf_etiqueta') or 'PDF'}", pdf.read_bytes(), r["pdf"], "application/pdf", f"pdf_{r['id']}")
            else:
                st.caption(f"Falta el archivo pdfs/{r['pdf']}")
        with b2:
            with ventana("📄 Ficha"):
                st.markdown(f"**{r['institucion']}**  \n{r['modalidad']}")
                st.markdown(f"**Objeto.** {r['objeto']}")
                st.markdown(f"**Renovación.** {r['regla_renovacion']}")
                st.markdown(f"**Responsable INEN.** {r['responsable']}")
                st.markdown(f"**Contraparte.** {r['coordinador_contraparte']}")
                cp = PAGO.get(r["id"])
                if cp:
                    st.markdown("**Condiciones de pago**")
                    tiles = [(a, f"{cp[k]} {u}") for a, k, u in [("Conformidad IAFAS", "conformidad_d", "d"),
                             ("Subsanación INEN", "subsanacion_d", "d"), ("Pago", "pago_d", "d"),
                             ("Regularizar emergencia", "emergencia_h", "h")] if cp.get(k)]
                    st.markdown("<div style='display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px'>" + "".join(
                        f"<div style='background:rgba(21,112,239,.08);border-radius:8px;padding:6px 10px'>"
                        f"<div class='muted'>{a}</div><div style='font-size:1.3rem;font-weight:800;color:#175CD3'>{v}</div></div>"
                        for a, v in tiles) + "</div>", unsafe_allow_html=True)
                    chips = f"<span class='chip'>{cp['mecanismo']}</span><span class='chip'>{cp['autorizacion']}</span>"
                    for e in cp.get("extra", []):
                        chips += f"<span class='chip'>{e}</span>"
                    if cp["cg_amb"]:
                        chips += (f"<br><span class='chip'>CG ambulatorio S/ {cp['cg_amb']:,.0f}</span>"
                                  f"<span class='chip'>CG emergencia S/ {cp['cg_eme']:,.0f}</span>"
                                  f"<span class='chip'>CG hospitalización S/ {cp['cg_hosp']:,.0f}</span>")
                    st.markdown(chips, unsafe_allow_html=True)
                st.caption(r["nota_fechas"])
        extras = r.get("pdfs_extra") if isinstance(r.get("pdfs_extra"), list) else []
        for j, ex in enumerate(extras):
            px = PDFS / ex["archivo"]
            if px.exists():
                boton_descarga(f"📎 {ex['etiqueta']}", px.read_bytes(), ex["archivo"], "application/pdf", f"px_{r['id']}_{j}")
            else:
                st.caption(f"Falta el archivo pdfs/{ex['archivo']}")
        if r["estado"] in ("Vencido", "Crítico"):
            st.caption(f"⚠️ {accion_sugerida(r)}")


def grilla(d: pd.DataFrame, n: int = 3) -> None:
    filas = [d.iloc[i:i + n] for i in range(0, len(d), n)]
    for f in filas:
        cols = st.columns(n)
        for c, (_, r) in zip(cols, f.iterrows()):
            with c:
                tarjeta(r)


def linea_tiempo(d: pd.DataFrame) -> go.Figure:
    d = d.iloc[::-1]
    ini = HOY - timedelta(days=900)
    fig = go.Figure()
    for _, r in d.iterrows():
        x0 = max(r["inicio_periodo"], ini)
        fig.add_trace(go.Bar(y=[r["corto"]], x=[(r["fin"] - x0).days * 86400000], base=[pd.Timestamp(x0)],
                             orientation="h", marker_color=COLORES[r["estado"]], showlegend=False,
                             hovertemplate=f"<b>{r['corto']}</b><br>{r['inicio_periodo']:%d/%m/%Y} a {r['fin']:%d/%m/%Y}<extra></extra>"))
    fig.add_trace(go.Scatter(y=d["corto"], x=pd.to_datetime(d["limite_aviso"]), mode="markers", name="Límite de aviso",
                             marker=dict(symbol="diamond", size=12, color="#101828", line=dict(color="white", width=1)),
                             hovertemplate="Aviso hasta %{x|%d/%m/%Y}<extra></extra>"))
    fig.add_shape(type="line", x0=pd.Timestamp(HOY), x1=pd.Timestamp(HOY), y0=0, y1=1, yref="paper",
                  line=dict(dash="dash", color="#1570EF"))
    fig.add_annotation(x=pd.Timestamp(HOY), y=1.06, yref="paper", text="Hoy", showarrow=False, font=dict(color="#1570EF"))
    fig.update_layout(height=90 + 46 * len(d), margin=dict(l=10, r=10, t=30, b=10), barmode="overlay",
                      xaxis=dict(type="date"), legend=dict(orientation="h", y=-0.15), plot_bgcolor="rgba(0,0,0,0)")
    return fig


def dona_estados(d: pd.DataFrame) -> go.Figure:
    c = d["estado"].value_counts().reindex(ORDEN_ESTADO).dropna()
    fig = go.Figure(go.Pie(labels=c.index, values=c.values, hole=.62, sort=False,
                           marker=dict(colors=[COLORES[e] for e in c.index]), textinfo="value"))
    fig.update_layout(height=240, margin=dict(l=0, r=0, t=0, b=0), showlegend=True,
                      legend=dict(orientation="h", y=-0.05),
                      annotations=[dict(text=f"<b>{len(d)}</b><br>convenios", showarrow=False, font=dict(size=15))])
    return fig


def a_excel(hojas: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nombre, h in hojas.items():
            h.to_excel(xw, sheet_name=nombre[:31], index=False)
            for col in xw.sheets[nombre[:31]].columns:
                xw.sheets[nombre[:31]].column_dimensions[col[0].column_letter].width = 40
    return buf.getvalue()


# ================================================================ cabecera
st.markdown(
    f"<div style='display:flex;align-items:center;gap:24px;padding:16px 24px;border-radius:14px;"
    f"border:1px solid rgba(21,112,239,.35);background:linear-gradient(90deg,rgba(21,112,239,.10),rgba(21,112,239,.02));"
    f"margin-bottom:14px'>"
    f"<div style='background:#fff;border-radius:10px;padding:6px 10px'>{logo_html('INEN', 78)}</div>"
    f"<div><div style='font-size:1.9rem;font-weight:800;line-height:1.15;color:#0B4A9E'>"
    f"Observatorio de convenios y contratos</div>"
    f"<div style='font-size:1.25rem;font-weight:600;color:#175CD3;margin-top:4px'>"
    f"Dirección de Servicios de Apoyo al Diagnóstico y Tratamiento</div>"
    f"<div style='margin-top:6px;opacity:.75'>Instituto Nacional de Enfermedades Neoplásicas · corte {HOY:%d/%m/%Y}</div>"
    f"</div></div>",
    unsafe_allow_html=True,
)

urg = df[df["estado"].isin(["Vencido", "Crítico"])]
if not urg.empty:
    chips = " ".join(
        f"<span class='pill' style='background:{COLORES[r['estado']]};margin-right:6px'>{r['corto']} · "
        f"{'vencido' if r['dias_venc'] < 0 else str(r['dias_venc']) + ' d'}</span>" for _, r in urg.iterrows())
    st.markdown(f"⚠️ **Requieren atención:** {chips}", unsafe_allow_html=True)

def leer_secretos() -> dict:
    """Lee st.secrets sin mostrar el aviso de Streamlit cuando no existe secrets.toml."""
    try:
        if hasattr(st.secrets, "load_if_toml_exists") and not st.secrets.load_if_toml_exists():
            return {}
        return dict(st.secrets)
    except Exception:  # noqa: BLE001
        return {}


SECRETOS = leer_secretos()

# ================================================================ panel lateral
if "qa_pregunta" not in st.session_state:
    st.session_state.qa_pregunta = ""
    st.session_state.qa_respuesta = ""


def _preguntar(texto: str) -> None:
    st.session_state.qa_pregunta = texto
    st.session_state.qa_txt = texto
    st.session_state.qa_lanzar = True


def _limpiar() -> None:
    st.session_state.qa_pregunta = ""
    st.session_state.qa_respuesta = ""
    st.session_state.qa_txt = ""


with st.sidebar:
    st.markdown("## ⚙️ Panel de control")
    with st.expander("💬 Pregunta a los datos", expanded=True):
        usar_filtros = st.toggle("Aplicar los filtros del panel", value=True,
                                 help="Si está activo, la respuesta considera solo los convenios filtrados.")
        st.text_area("Pregunta", key="qa_txt", label_visibility="collapsed", height=80,
                     placeholder="Ej.: ¿qué albergue acepta a un niño de 13 años?")
        c1, c2 = st.columns(2)
        consultar = c1.button("Consultar", type="primary", **ANCHO)
        c2.button("Limpiar", on_click=_limpiar, **ANCHO)
        st.caption("Ejemplos de preguntas (tócalos para consultar)")
        for k, ej in enumerate(EJEMPLOS):
            st.button(ej, key=f"ej_{k}", on_click=_preguntar, args=(ej,),
                      **({"type": "tertiary"} if _V >= (1, 43) else {}))
        try:
            clave_secreta = SECRETOS.get("ANTHROPIC_API_KEY", "")
        except Exception:  # noqa: BLE001
            clave_secreta = ""
        with ventana("✨ Activar modo IA"):
            clave = st.text_input("Clave de API de Anthropic", type="password", value="",
                                  help="Se usa solo en esta sesión y no se guarda. También puede definirse como "
                                       "ANTHROPIC_API_KEY en los secretos de Streamlit.")
        clave = clave or clave_secreta
        st.caption("🟢 Modo IA activo" if clave else "⚪ Modo básico (sin IA)")

    with st.expander("🔎 Filtros", expanded=False):
        f_tipo = st.multiselect("Tipo", ["No prestacional", "Prestacional"], default=["No prestacional", "Prestacional"])
        f_estado = st.multiselect("Estado", ORDEN_ESTADO, default=ORDEN_ESTADO)
        f_inst = st.multiselect("Institución", list(df["id"]), format_func=lambda i: CORTO[i],
                                help="Vacío muestra todas")
    dfv = df[df["tipo"].isin(f_tipo) & df["estado"].isin(f_estado)]
    if f_inst:
        dfv = dfv[dfv["id"].isin(f_inst)]

    if consultar or st.session_state.pop("qa_lanzar", False):
        pregunta = (st.session_state.get("qa_txt") or "").strip()
        st.session_state.qa_pregunta = pregunta
        base = dfv if usar_filtros else df
        if not pregunta:
            st.session_state.qa_respuesta = "Escribe una pregunta o toca un ejemplo."
        elif clave:
            ids = set(base["id"])
            ctx = {"fecha_corte": f"{HOY:%d/%m/%Y}",
                   "convenios": base.drop(columns=["orden"], errors="ignore").to_dict(orient="records"),
                   "beneficios": ben[ben.index.isin(ids)].reset_index().to_dict(orient="records"),
                   "indicadores": IND}
            try:
                with st.spinner("Consultando…"):
                    st.session_state.qa_respuesta = responder_ia(pregunta, clave, ctx)
            except Exception as e:  # noqa: BLE001
                st.session_state.qa_respuesta = (f"No se pudo usar el modo IA ({e}). Respuesta del modo básico:\n\n"
                                                 + responder_local(pregunta, base, ben, IND, CORTO))
        else:
            st.session_state.qa_respuesta = responder_local(pregunta, base, ben, IND, CORTO)

if st.session_state.qa_respuesta:
    with st.container(border=True):
        h1, h2 = st.columns([12, 1])
        h1.markdown(f"**💬 {st.session_state.qa_pregunta}**")
        h2.button("✖", key="qa_cerrar", on_click=_limpiar)
        st.markdown(st.session_state.qa_respuesta)

t1, t2, t4 = st.tabs(["🤝 No prestacionales", "🏥 Prestacionales", "✉️ Alertas y descargas"])


def mapa_beneficios(ids: list[str], key: str, primero: list[str] | None = None) -> None:
    mb = IND["matriz_beneficios"]
    par = mb.get("parciales", {})
    notas = mb.get("notas", {})
    cols = [c for c in mb["columnas"] if any(c in mb["filas"].get(i, []) or c in par.get(i, {}) for i in ids)]
    if primero:
        cols = [c for c in primero if c in cols] + [c for c in cols if c not in primero]
    z, txt, hov = [], [], []
    for i in ids:
        fz, ft, fh = [], [], []
        for c in cols:
            if c in mb["filas"].get(i, []):
                fz.append(1); ft.append("✓")
            elif c in par.get(i, {}):
                fz.append(0.5); ft.append(par[i][c])
            else:
                fz.append(0); ft.append("")
            fh.append(notas.get(i, {}).get(c, ft[-1] or "No incluye"))
        z.append(fz); txt.append(ft); hov.append(fh)
    hov = [["<br>".join(textwrap.wrap(h, 60)) for h in fila] for fila in hov]
    fig = go.Figure(go.Heatmap(z=z, x=cols, y=[CORTO[i] for i in ids], showscale=False, xgap=4, ygap=4, zmin=0, zmax=1,
                               colorscale=[[0, "rgba(128,128,128,0.08)"], [0.5, "#84CAFF"], [1, "#1570EF"]],
                               text=txt, texttemplate="%{text}", textfont=dict(color="white", size=14),
                               customdata=hov, hovertemplate="<b>%{y} · %{x}</b><br>%{customdata}<extra></extra>"))
    fig.update_layout(height=80 + 40 * len(ids), margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(side="top", showgrid=False, zeroline=False, showline=False, ticks=""),
                      yaxis=dict(autorange="reversed", showgrid=False, zeroline=False, showline=False, ticks=""),
                      plot_bgcolor="rgba(0,0,0,0)")
    grafico(fig, key)
    if par.keys() & set(ids):
        st.caption("Celeste: cobertura condicionada. Pase el cursor sobre cada celda para ver la cláusula que lo sustenta.")


def criterios(ids: list[str], key: str) -> None:
    with st.expander("Ver criterios completos de derivación y exclusiones"):
        sel = st.selectbox("Institución", ids, format_func=lambda i: CORTO[i], key=key)
        b = ben.loc[sel]
        c1, c2 = st.columns(2)
        c1.markdown(f"**Qué nos da.** {b['que_brinda']}\n\n**Para quién.** {b['poblacion']}\n\n**Capacidad.** {b['capacidad']}")
        c2.markdown(f"**Criterios.** {b['criterios_derivacion']}\n\n**Cómo se solicita.** {b['como_solicitar']}\n\n"
                    f"**Límites.** {b['limites']}")


# ================================================================ 1. No prestacionales
with t1:
    d = dfv[dfv["tipo"] == "No prestacional"]
    kpis(d)
    st.write("")
    grilla(d)
    st.markdown("#### Vigencia de los periodos actuales")
    grafico(linea_tiempo(d), "lt_np")

    st.divider()
    st.markdown("### 🎁 Qué nos da cada uno")
    ids_np = ["INSPIRA", "MAGIA", "SAN_VICENTE", "FPC", "ALINEN", "WIESE", "IRD"]
    mapa_beneficios(ids_np, "mapa_np")

    st.markdown("#### Guía rápida de derivación")
    perf = IND["perfiles"]
    for i in range(0, len(perf), 4):
        cols = st.columns(4)
        for c, p in zip(cols, perf[i:i + 4]):
            logos = "".join(f"<span style='display:inline-block;margin-right:10px'>{logo_html(o, 38)}</span>" for o in p["opciones"])
            c.markdown(f"<div class='perfil' style='margin-bottom:18px'><b>{p['perfil']}</b><div style='margin:8px 0'>{logos}</div>"
                       f"<span class='muted'>{p['nota']}</span></div>", unsafe_allow_html=True)
    st.caption("Toda derivación a albergues, medicamentos o traslados pasa por la calificación socioeconómica de Trabajo Social.")

    st.markdown("#### Albergues en convenio")
    alb = pd.DataFrame(IND["albergues"])
    alb["corto"] = alb["id"].map(CORTO)
    k = st.columns(4)
    for c, (lab, v) in zip(k, [("Camas en convenio", alb["camas"].sum()), ("Habitaciones operativas", alb["operativas"].sum()),
                               ("Ambientes TAMO", alb["tamo"].sum()), ("Aptos silla de ruedas", int((alb["silla_ruedas"] == "Sí").sum()))]):
        c.markdown(f"<div class='kpi' style='background:#175CD3'><div class='n'>{v}</div><div class='l'>{lab}</div></div>",
                   unsafe_allow_html=True)
    st.write("")
    a1, a2, a3 = st.columns(3)
    with a1:
        st.markdown("**Edad que acepta**")
        fig = go.Figure()
        for _, r in alb.iterrows():
            fig.add_trace(go.Bar(y=[r["corto"]], x=[r["edad_max"] - r["edad_min"]], base=[r["edad_min"]], orientation="h",
                                 marker_color="#1570EF", showlegend=False, text=f"{r['edad_min']} a {r['edad_max']}",
                                 textposition="inside", hovertemplate=r["poblacion"] + "<extra></extra>"))
            if r["edad_max_reingreso"] > r["edad_max"]:
                fig.add_trace(go.Bar(y=[r["corto"]], x=[r["edad_max_reingreso"] - r["edad_max"]], base=[r["edad_max"]],
                                     orientation="h", marker_color="#84CAFF", showlegend=False,
                                     hovertemplate="Reingresos<extra></extra>"))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Años", barmode="overlay",
                          yaxis=dict(autorange="reversed"), plot_bgcolor="rgba(0,0,0,0)")
        grafico(fig, "edades")
        st.caption("Celeste: reingresos. ALINEN: mujeres adultas, sin tope indicado.")
    with a2:
        st.markdown("**Camas**")
        fig = go.Figure(go.Bar(y=alb["corto"], x=alb["camas"], orientation="h", marker_color="#1570EF",
                               text=alb["camas"], textposition="auto"))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"),
                          plot_bgcolor="rgba(0,0,0,0)")
        grafico(fig, "camas")
    with a3:
        st.markdown("**Ambientes especiales**")
        fig = go.Figure()
        for campo, nom, colr in [("tamo", "TAMO", "#7A5AF8"), ("yodoterapia", "Yodoterapia", "#F79009"),
                                 ("neurologia", "Neurología", "#EE46BC")]:
            fig.add_trace(go.Bar(y=alb["corto"], x=alb[campo], name=nom, orientation="h", marker_color=colr,
                                 text=[v if v else "" for v in alb[campo]], textposition="auto"))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), barmode="group",
                          yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=-0.12),
                          plot_bgcolor="rgba(0,0,0,0)")
        grafico(fig, "ambientes")
    acc = {"Sí": "♿ ✅", "Parcial": "♿ ⚠️", "No": "♿ ❌"}
    cols = st.columns(len(alb))
    for c, (_, r) in zip(cols, alb.iterrows()):
        c.markdown(f"<div style='text-align:center'>{logo_html(r['id'], 44)}<div style='font-size:1.3rem'>{acc[r['silla_ruedas']]}</div>"
                   f"<div class='muted'>🚐 {r['movilidad']}</div></div>", unsafe_allow_html=True)
    criterios(ids_np, "crit_np")

# ================================================================ 2. Prestacionales
with t2:
    d = dfv[dfv["tipo"] == "Prestacional"]
    kpis(d)
    st.markdown("### 📑 Convenios")
    grilla(d[d["clase"] == "Convenio"])
    st.markdown("### 🧾 Contratos")
    grilla(d[d["clase"] == "Contrato"])
    st.markdown("#### Vigencia de los periodos actuales")
    grafico(linea_tiempo(d), "lt_p")

    st.divider()
    st.markdown("### 🎁 Qué nos da cada uno")
    ids_p = ["SIS_FISSAL", "EJERCITO", "SALUDPOL", "FOSFAP", "FOSMAR", "ONCOSALUD"]
    mapa_beneficios(ids_p, "mapa_p", ["Financia prestaciones", "Medicamentos e insumos", "Medicamentos alto costo"])
    cols = st.columns(len(ids_p))
    for c, i in zip(cols, ids_p):
        b = ben.loc[i]
        c.markdown(f"<div class='perfil'>{logo_html(i, 36)}<div style='margin-top:6px'><b>Cubre a</b></div>"
                   f"<span class='muted'>{b['poblacion']}</span></div>", unsafe_allow_html=True)
    criterios(ids_p, "crit_p")

# ================================================================ 4. Alertas y descargas
with t4:
    try:
        secrets = SECRETOS
    except Exception:  # noqa: BLE001
        secrets = {}
    cfg = config_correo(secrets)
    ok = bool(cfg["user"] and cfg["password"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Correo configurado", "Sí" if ok else "No")
    c2.metric("Alertas por hito hoy", len(seleccionar_alertas(df, "hitos")))
    c3.metric("En resumen semanal", len(seleccionar_alertas(df, "resumen")))
    modo = st.radio("Contenido del correo", ["resumen", "hitos"], horizontal=True,
                    format_func=lambda m: "Resumen (vencidos y próximos 180 días)" if m == "resumen" else "Solo hitos de hoy")
    sel = seleccionar_alertas(df, modo)
    dest = st.text_input("Destinatarios (separados por coma)", ", ".join(cfg["destinatarios"]))
    if sel.empty:
        st.success("Sin convenios que alertar con este criterio.")
    else:
        asunto = f"[Convenios DISAD] {len(sel)} convenio(s) requieren atención"
        with st.expander("Vista previa del correo"):
            st.markdown(html_alerta(sel, asunto, URL_APP), unsafe_allow_html=True)
        if st.button("✉️ Enviar ahora", type="primary", disabled=not ok):
            try:
                enviar_correo(cfg, asunto, html_alerta(sel, asunto, URL_APP), [x.strip() for x in dest.split(",") if x.strip()])
                st.success("Correo enviado.")
            except Exception as e:  # noqa: BLE001
                st.error(f"No se pudo enviar: {e}")
    if not ok:
        st.info("Para activar el envío, complete `.streamlit/secrets.toml` (ver README). "
                "El envío diario automático lo hace `enviar_alertas.py`.")
    st.divider()
    st.markdown("**Descargas**")
    d1, d2 = st.columns(2)
    with d1:
        boton_descarga("⬇️ Matriz de convenios (Excel)",
                       a_excel({"Convenios": df.drop(columns=["orden", "fin_periodo_actual", "logo_url", "pdfs_extra"], errors="ignore")}),
                       f"matriz_convenios_DISAD_{HOY:%Y%m%d}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "x1")
    with d2:
        boton_descarga("⬇️ Beneficios y criterios (Excel)",
                       a_excel({"Beneficios": ben.reset_index(), "Albergues": pd.DataFrame(IND["albergues"])}),
                       f"beneficios_convenios_DISAD_{HOY:%Y%m%d}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "x2")

# ================================================================ pie: autoría y cita
TIT_ES = ("Observatorio de Convenios y Contratos de la Dirección de Servicios de Apoyo al Diagnóstico y "
          "Tratamiento: Vigencia, Beneficios y Criterios de Derivación")
TIT_EN = ("INEN Agreements and Contracts Observatory of the Directorate of Diagnostic and Treatment Support "
          "Services: Validity, Benefits and Referral Criteria")
INST_ES, INST_EN = "Instituto Nacional de Enfermedades Neoplásicas", "National Institute of Neoplastic Diseases"
AUTOR = "Orrego-Ferreyros LA"
ANIO = "2026"
MES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
MES_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
acc_es = f"{HOY.day} de {MES_ES[HOY.month - 1]} de {HOY.year}"
acc_en = f"{MES_EN[HOY.month - 1]} {HOY.day}, {HOY.year}"
ref_es = f"{AUTOR}. {TIT_ES}. {INST_ES}. Published {ANIO}. Accessed {acc_es}. {URL_APP}"
ref_en = f"{AUTOR}. {TIT_EN}. {INST_EN}. Published {ANIO}. Accessed {acc_en}. {URL_APP}"

bib = f"""@misc{{orrego_observatorio_convenios_{ANIO},
  author       = {{Orrego-Ferreyros, Luis Alexander}},
  title        = {{{TIT_ES}}},
  howpublished = {{\\url{{{URL_APP}}}}},
  organization = {{{INST_ES}}},
  year         = {{{ANIO}}},
  note         = {{Accedido el {acc_es}}}
}}
"""
ris = f"""TY  - ELEC
AU  - Orrego-Ferreyros, Luis Alexander
TI  - {TIT_ES}
PB  - {INST_ES}
PY  - {ANIO}
UR  - {URL_APP}
Y2  - {HOY:%Y/%m/%d}
LA  - es
ER  - 
"""
xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<xml><records><record>
<ref-type name="Web Page">12</ref-type>
<contributors><authors><author>Orrego-Ferreyros, Luis Alexander</author></authors></contributors>
<titles><title>{TIT_ES}</title></titles>
<publisher>{INST_ES}</publisher>
<dates><year>{ANIO}</year></dates>
<urls><related-urls><url>{URL_APP}</url></related-urls></urls>
<access-date>{HOY:%Y-%m-%d}</access-date>
<language>spa</language>
</record></records></xml>
"""

st.divider()
st.markdown(
    "<div style='text-align:center;opacity:.7;font-size:.9rem;margin:6px 0 16px'>"
    "© Luis A. Orrego Ferreyros, Econ., MCE, MMD, PhD(c), CQRM · Epidemiólogo y Economista de la Salud · INEN</div>"
    "<div style='border:1px solid rgba(128,128,128,.25);background:rgba(128,128,128,.06);border-radius:10px;"
    "padding:16px 20px;font-size:.88rem;line-height:1.7'>"
    "<div style='font-weight:700;color:#0B4A9E;font-size:.82rem'>REFERENCIA WEB (formato AMA)</div>"
    f"<div style='margin-bottom:12px'>{ref_es}</div>"
    "<div style='font-weight:700;color:#0B4A9E;font-size:.82rem'>WEB REFERENCE (AMA format)</div>"
    f"<div>{ref_en}</div></div>",
    unsafe_allow_html=True,
)
r1, r2, r3 = st.columns(3)
with r1:
    st.download_button("⬇️ BibTeX (*.bib)", bib, file_name="observatorio_convenios_inen.bib", mime="application/x-bibtex", key="cit_bib")
with r2:
    st.download_button("⬇️ EndNote XML (*.xml)", xml, file_name="observatorio_convenios_inen.xml", mime="application/xml", key="cit_xml")
with r3:
    st.download_button("⬇️ RIS (*.ris)", ris, file_name="observatorio_convenios_inen.ris", mime="application/x-research-info-systems", key="cit_ris")
