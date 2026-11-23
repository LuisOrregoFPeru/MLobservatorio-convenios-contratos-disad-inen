"""Pregunta a los datos: motor de reglas local y modo IA (API de Anthropic)."""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request

import pandas as pd

MODELO_IA = "claude-sonnet-5-5"
EJEMPLOS = [
    "¿Qué convenios están vencidos?",
    "¿Qué convenios vencen en los próximos 6 meses?",
    "¿Qué albergue acepta a un niño de 13 años?",
    "¿Qué albergues son aptos para silla de ruedas?",
    "¿Quiénes financian medicamentos de alto costo?",
    "¿Cuál es el plazo de pago de FOSFAP?",
    "¿Quién es el responsable del convenio con SaludPol?",
    "¿Qué institución dona prótesis?",
]


def _n(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


ALIAS = {
    "ALINEN": ["alinen", "alianza"], "FPC": ["fpc", "fundacion peruana"], "MAGIA": ["magia"],
    "INSPIRA": ["inspira"], "SAN_VICENTE": ["san vicente", "congregacion", "mision"],
    "WIESE": ["wiese"], "IRD": ["ird", "francia"], "SIS_FISSAL": ["sis", "fissal"],
    "EJERCITO": ["ejercito"], "SALUDPOL": ["saludpol", "policia"], "FOSFAP": ["fosfap", "fuerza aerea"],
    "FOSMAR": ["fosmar", "marina"], "ONCOSALUD": ["oncosalud"],
}


def _instituciones(q: str, ids: list[str]) -> list[str]:
    out = []
    for i in ids:
        for a in ALIAS.get(i, [i.lower()]):
            if re.search(rf"\b{re.escape(a)}\b", q):
                out.append(i)
                break
    return out


def _tabla(df: pd.DataFrame, cols: dict) -> str:
    if df.empty:
        return "_Sin resultados con los filtros actuales._"
    h = "| " + " | ".join(cols.values()) + " |\n|" + "---|" * len(cols) + "\n"
    for _, r in df.iterrows():
        h += "| " + " | ".join(str(r[c]).replace("|", "/") for c in cols) + " |\n"
    return h


def responder_local(pregunta: str, df: pd.DataFrame, ben: pd.DataFrame, ind: dict, corto: dict) -> str:
    q = _n(pregunta)
    d = df.copy()
    d["Vence"] = [f"{x:%d/%m/%Y}" for x in d["fin"]]
    d["Días"] = d["dias_venc"]
    ids = list(d["id"])
    inst = _instituciones(q, ids)

    # vencidos / por vencer
    if "vencid" in q:
        r = d[d["dias_venc"] < 0].sort_values("dias_venc")
        r = r.assign(Hace=[f"{-x} días" for x in r["dias_venc"]])
        return "**Convenios vencidos**\n\n" + _tabla(r, {"corto": "Convenio", "tipo": "Tipo", "Vence": "Venció", "Hace": "Hace"})
    m = re.search(r"(\d+)\s*(mes|dia)", q)
    if ("venc" in q or "renov" in q) and not inst:
        dias = 180
        if m:
            dias = int(m.group(1)) * (30 if m.group(2) == "mes" else 1)
        r = d[(d["dias_venc"] >= 0) & (d["dias_venc"] <= dias)].sort_values("dias_venc")
        r = r.assign(Aviso=[f"{x:%d/%m/%Y}" for x in r["limite_aviso"]])
        return (f"**Convenios que vencen en los próximos {dias} días**\n\n"
                + _tabla(r, {"corto": "Convenio", "Vence": "Vence", "Días": "Días", "Aviso": "Límite de aviso", "renovacion": "Renovación"}))

    # albergues
    alb = pd.DataFrame(ind["albergues"])
    alb = alb[alb["id"].isin(ids)]
    alb["Albergue"] = alb["id"].map(corto)
    if "silla" in q or "accesib" in q or "ruedas" in q:
        return "**Accesibilidad para silla de ruedas**\n\n" + _tabla(alb, {"Albergue": "Albergue", "silla_ruedas": "Silla de ruedas", "camas": "Camas"})
    edad = re.search(r"(\d{1,2})\s*anos", q)
    if edad and ("albergue" in q or "aloj" in q or "nino" in q or "acepta" in q):
        e = int(edad.group(1))
        r = alb[(alb["edad_min"] <= e) & (alb["edad_max_reingreso"] >= e)]
        r = r.assign(Rango=[f"{a} a {b}" + (f" (reingresos hasta {c})" if c > b else "") for a, b, c in
                            zip(r["edad_min"], r["edad_max"], r["edad_max_reingreso"])])
        return (f"**Albergues que aceptan pacientes de {e} años**\n\n"
                + _tabla(r, {"Albergue": "Albergue", "poblacion": "Población", "Rango": "Edad", "camas": "Camas", "silla_ruedas": "Silla de ruedas"})
                + "\n\nLa derivación requiere la calificación socioeconómica de Trabajo Social.")
    if any(k in q for k in ["albergue", "cama", "aloja", "tamo", "yodo", "neurolog"]):
        return "**Albergues en convenio**\n\n" + _tabla(alb, {"Albergue": "Albergue", "poblacion": "Población", "camas": "Camas", "tamo": "TAMO", "yodoterapia": "Yodoterapia", "neurologia": "Neurología", "silla_ruedas": "Silla de ruedas"})

    # beneficios del mapa
    mb = ind["matriz_beneficios"]
    claves = {"alto costo": "Medicamentos alto costo", "medicament": "Medicamentos e insumos", "protesis": "Prótesis",
              "traslad": "Traslados", "psicolog": "Psicología", "examen": "Exámenes auxiliares", "financ": "Financia prestaciones",
              "investig": "Investigación", "alimenta": "Alimentación", "terapia": "Terapia física", "equipo": "Equipos médicos"}
    for k, col in claves.items():
        if k in q and not inst:
            filas = []
            for i in ids:
                if col in mb["filas"].get(i, []):
                    filas.append((corto[i], "Sí", mb.get("notas", {}).get(i, {}).get(col, "")))
                elif col in mb.get("parciales", {}).get(i, {}):
                    filas.append((corto[i], mb["parciales"][i][col], mb.get("notas", {}).get(i, {}).get(col, "")))
            r = pd.DataFrame(filas, columns=["Institución", "Cobertura", "Sustento"])
            return f"**{col}**\n\n" + _tabla(r, {"Institución": "Institución", "Cobertura": "Cobertura", "Sustento": "Sustento"})

    # preguntas sobre una institución
    if inst:
        partes = []
        pagos = {x["id"]: x for x in ind["prestacionales"]}
        for i in inst:
            r = d[d["id"] == i].iloc[0]
            b = ben.loc[i] if i in ben.index else None
            txt = f"### {r['corto']}\n"
            if any(k in q for k in ["plazo", "pago", "conformidad", "pagar"]) and i in pagos:
                p = pagos[i]
                det = [f"{lab}: {p[c]} {u}" for lab, c, u in [("Conformidad IAFAS", "conformidad_d", "días"),
                       ("Subsanación INEN", "subsanacion_d", "días"), ("Pago", "pago_d", "días"),
                       ("Regularizar emergencia", "emergencia_h", "horas")] if p.get(c)]
                txt += f"Mecanismo: {p['mecanismo']}. Autorización: {p['autorizacion']}.\n\n" + "\n".join(f"- {x}" for x in det)
                txt += "".join(f"\n- {e}" for e in p.get("extra", []))
            elif any(k in q for k in ["responsable", "coordin", "quien"]):
                txt += f"- Responsable INEN: {r['responsable']}\n- Contraparte: {r['coordinador_contraparte']}"
            elif any(k in q for k in ["venc", "vigen", "renov", "hasta"]):
                txt += (f"- Vence: {r['fin']:%d/%m/%Y} ({r['dias_venc']} días)\n- Límite de aviso: {r['limite_aviso']:%d/%m/%Y}\n"
                        f"- Renovación: {r['regla_renovacion']}")
            elif b is not None and any(k in q for k in ["criterio", "derivar", "deriv", "requisito", "solicit"]):
                txt += f"- Criterios: {b['criterios_derivacion']}\n- Cómo se solicita: {b['como_solicitar']}"
            elif b is not None and any(k in q for k in ["exclu", "limite", "no cubre"]):
                txt += f"- {b['limites']}"
            else:
                txt += (f"- Estado: {r['estado']} · vence {r['fin']:%d/%m/%Y}\n- Objeto: {r['objeto_corto']}\n")
                if b is not None:
                    txt += f"- Qué nos da: {b['que_brinda']}\n- Para quién: {b['poblacion']}"
            partes.append(txt)
        return "\n\n".join(partes)

    return ("No encontré una respuesta directa con el motor básico. Prueba con uno de los ejemplos, menciona una "
            "institución (por ejemplo, SaludPol o MAGIA) o activa el modo IA para preguntas abiertas.")


def responder_ia(pregunta: str, clave: str, contexto: dict) -> str:
    sistema = ("Eres un analista de la Dirección de Servicios de Apoyo al Diagnóstico y Tratamiento del INEN (Perú). "
               "Responde en español, de forma breve y precisa, usando SOLO los datos JSON proporcionados sobre convenios "
               "y contratos (vigencias, renovación, beneficios, criterios de derivación, condiciones de pago y albergues). "
               "Si el dato no está, dilo. Cita la institución y las fechas en formato dd/mm/aaaa. Usa tablas Markdown "
               "cuando compares varias instituciones.")
    cuerpo = {
        "model": MODELO_IA, "max_tokens": 1200, "system": sistema,
        "messages": [{"role": "user", "content": f"Datos:\n{json.dumps(contexto, ensure_ascii=False, default=str)}\n\nPregunta: {pregunta}"}],
    }
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(cuerpo).encode(),
                                 headers={"x-api-key": clave, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []))
