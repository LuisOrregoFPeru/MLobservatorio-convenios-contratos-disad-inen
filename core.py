"""Lógica común: carga de datos, cálculo de vencimientos y envío de alertas por correo."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BASE = Path(__file__).parent
DATA = BASE / "data"
PDFS = BASE / "pdfs"
TZ = ZoneInfo("America/Lima")

# Hitos (días antes del vencimiento o de la fecha límite de aviso) que disparan un correo
HITOS_VENC = {180, 120, 90, 60, 30, 15, 7, 3, 1, 0}
HITOS_AVISO = {30, 15, 7, 3, 1, 0}

COLORES = {
    "Vencido": "#B42318",
    "Crítico": "#E8590C",
    "Por vencer": "#D9A400",
    "Vigente": "#2F9E44",
}
ORDEN_ESTADO = ["Vencido", "Crítico", "Por vencer", "Vigente"]


def hoy() -> date:
    return pd.Timestamp.now(tz=TZ).date()


def cargar_convenios(ref: date | None = None) -> pd.DataFrame:
    ref = ref or hoy()
    df = pd.DataFrame(json.loads((DATA / "convenios.json").read_text(encoding="utf-8")))
    df["inicio"] = pd.to_datetime(df["inicio"]).dt.date
    df["fin"] = pd.to_datetime(df["fin_periodo_actual"]).dt.date
    df["limite_aviso"] = [f - timedelta(days=int(a)) for f, a in zip(df["fin"], df["aviso_dias"])]
    df["dias_venc"] = [(f - ref).days for f in df["fin"]]
    df["dias_aviso"] = [(l - ref).days for l in df["limite_aviso"]]
    df["estado"] = df.apply(_estado, axis=1)
    df["orden"] = df["estado"].map({e: i for i, e in enumerate(ORDEN_ESTADO)})
    return df.sort_values(["orden", "dias_venc"]).reset_index(drop=True)


def _estado(r) -> str:
    if r["dias_venc"] < 0:
        return "Vencido"
    if r["dias_aviso"] <= 30 or r["dias_venc"] <= 60:
        return "Crítico"
    if r["dias_venc"] <= 180:
        return "Por vencer"
    return "Vigente"


def cargar_beneficios() -> pd.DataFrame:
    return pd.DataFrame(json.loads((DATA / "beneficios.json").read_text(encoding="utf-8")))


def accion_sugerida(r) -> str:
    if r["estado"] == "Vencido":
        return r["estado_manual"] or "Vencido: regularizar renovación o nuevo convenio."
    if r["dias_aviso"] < 0:
        return f"Ya pasó la fecha límite de aviso ({r['limite_aviso']:%d/%m/%Y}). Gestionar renovación de inmediato."
    if r["renovacion"].startswith("Automática"):
        return f"Se renueva sola. Si no conviene continuar, comunicar por escrito antes del {r['limite_aviso']:%d/%m/%Y}."
    return f"Requiere acción expresa. Iniciar evaluación y comunicación escrita desde el {r['limite_aviso']:%d/%m/%Y}."


# ---------------------------------------------------------------- correo
def config_correo(secrets: dict | None = None) -> dict:
    """Lee la configuración SMTP de st.secrets (si se pasa) o de variables de entorno."""
    src = dict(secrets or {})
    g = lambda k, d="": str(src.get(k, os.getenv(k, d)))
    return {
        "host": g("SMTP_HOST", "smtp.gmail.com"),
        "port": int(g("SMTP_PORT", "587") or 587),
        "user": g("SMTP_USER"),
        "password": g("SMTP_PASSWORD"),
        "remitente": g("ALERT_FROM") or g("SMTP_USER"),
        "destinatarios": [x.strip() for x in g("ALERT_TO").split(",") if x.strip()],
    }


def seleccionar_alertas(df: pd.DataFrame, modo: str = "hitos", horizonte: int = 180) -> pd.DataFrame:
    """modo='hitos': solo convenios que hoy cruzan un hito. modo='resumen': todo lo que vence en el horizonte o está vencido."""
    if modo == "resumen":
        return df[(df["dias_venc"] <= horizonte) | (df["dias_aviso"] <= 30)]
    m = df["dias_venc"].isin(HITOS_VENC) | df["dias_aviso"].isin(HITOS_AVISO)
    return df[m]


def html_alerta(sel: pd.DataFrame, titulo: str, url_tablero: str = "") -> str:
    filas = []
    for _, r in sel.iterrows():
        dias = f"{r['dias_venc']} días" if r["dias_venc"] >= 0 else f"vencido hace {-r['dias_venc']} días"
        filas.append(
            f"<tr><td style='padding:6px;border-bottom:1px solid #ddd'><b>{r['institucion']}</b><br>"
            f"<span style='color:#666'>{r['tipo']}</span></td>"
            f"<td style='padding:6px;border-bottom:1px solid #ddd'>{r['fin']:%d/%m/%Y}<br>{dias}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #ddd'>{r['limite_aviso']:%d/%m/%Y}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #ddd;color:{COLORES[r['estado']]}'><b>{r['estado']}</b></td>"
            f"<td style='padding:6px;border-bottom:1px solid #ddd'>{accion_sugerida(r)}<br>"
            f"<span style='color:#666'>Responsable: {r['responsable']}</span></td></tr>"
        )
    link = f"<p><a href='{url_tablero}'>Abrir tablero de seguimiento</a></p>" if url_tablero else ""
    return (
        f"<div style='font-family:Arial,sans-serif;font-size:13px'><h3>{titulo}</h3>"
        f"<p>Fecha de corte: {hoy():%d/%m/%Y}</p>"
        "<table style='border-collapse:collapse;width:100%'><tr style='background:#f2f4f7'>"
        "<th align='left'>Convenio</th><th align='left'>Vence</th><th align='left'>Límite de aviso</th>"
        "<th align='left'>Estado</th><th align='left'>Acción sugerida</th></tr>"
        + "".join(filas) + "</table>" + link +
        "<p style='color:#888'>Mensaje automático del Tablero de Convenios DISAD, INEN.</p></div>"
    )


def enviar_correo(cfg: dict, asunto: str, html: str, destinatarios: list[str] | None = None) -> None:
    to = destinatarios or cfg["destinatarios"]
    if not (cfg["user"] and cfg["password"] and to):
        raise ValueError("Falta configurar SMTP_USER, SMTP_PASSWORD o ALERT_TO.")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = asunto, cfg["remitente"], ", ".join(to)
    msg.attach(MIMEText(html, "html", "utf-8"))
    ctx = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx, timeout=30) as s:
            s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["remitente"], to, msg.as_string())
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
            s.starttls(context=ctx)
            s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["remitente"], to, msg.as_string())
