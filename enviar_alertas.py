"""Envío programado de alertas de vencimiento (sin abrir el tablero).

Uso:
    python enviar_alertas.py --modo hitos     # diario: solo si algún convenio cruza un hito hoy
    python enviar_alertas.py --modo resumen   # semanal: todo lo vencido o por vencer en 180 días
    python enviar_alertas.py --modo resumen --simular   # muestra el correo sin enviarlo

Configuración por variables de entorno: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
ALERT_FROM, ALERT_TO (correos separados por coma) y opcionalmente TABLERO_URL.
"""
import argparse
import os
import sys

from core import cargar_convenios, config_correo, enviar_correo, html_alerta, seleccionar_alertas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["hitos", "resumen"], default="hitos")
    ap.add_argument("--horizonte", type=int, default=180)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()

    df = cargar_convenios()
    sel = seleccionar_alertas(df, a.modo, a.horizonte)
    if sel.empty:
        print("Sin alertas para hoy.")
        return 0
    n_crit = int(sel["estado"].isin(["Vencido", "Crítico"]).sum())
    asunto = (f"[Convenios DISAD] {'Resumen semanal' if a.modo == 'resumen' else 'Alerta de vencimiento'}: "
              f"{len(sel)} convenio(s), {n_crit} crítico(s) o vencido(s)")
    html = html_alerta(sel, asunto, os.getenv("TABLERO_URL", ""))
    if a.simular:
        print(asunto)
        print(sel[["institucion", "fin", "dias_venc", "limite_aviso", "estado"]].to_string(index=False))
        return 0
    enviar_correo(config_correo(), asunto, html)
    print(f"Enviado: {asunto}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
