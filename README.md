# Observatorio de convenios y contratos a cargo de DISAD (INEN)

Tablero Streamlit con dos vistas separadas (convenios no prestacionales y convenios/contratos prestacionales), semáforo de vencimientos, línea de tiempo, fecha límite para comunicar renovación o no renovación, descarga de cada PDF, cuadro de beneficios y criterios de derivación, y alertas por correo.

## Ejecutar
```
pip install -r requirements.txt
streamlit run app.py
```

## Logos
Los logos están en `logos/` (PNG con el mismo nombre que el `id` del convenio), recortados de los membretes oficiales de cada convenio. Para usar un logo publicado en la web, coloque su URL en el campo `logo_url` de `data/convenios.json`; el navegador lo cargará directamente. Oncosalud no tiene logo en su contrato: agregue `logos/ONCOSALUD.png` o su `logo_url`.

## Estructura
- `app.py`: tablero.
- `core.py`: cálculo de vencimientos, semáforo y envío de correo (SMTP).
- `enviar_alertas.py`: envío automático sin abrir el tablero.
- `data/convenios.json`: fechas, objeto, regla de renovación, días de aviso, responsable y PDF de cada convenio.
- `data/indicadores.json`: mapa de beneficios, capacidad de albergues, plazos de pago, cartas de garantía y guía de derivación (alimenta los gráficos).
- `data/beneficios.json`: qué brinda cada institución, para quién, capacidad, criterios de derivación, cómo se solicita y límites.
- `pdfs/`: convenios escaneados (descargables desde el tablero). Las adendas se listan en `pdfs_extra` de cada convenio y se descargan desde su ficha.

## Semáforo
- **Vencido**: pasó la fecha de fin del periodo vigente.
- **Crítico**: vence en 60 días o menos, o faltan 30 días o menos para la fecha límite de aviso (fin menos `aviso_dias`).
- **Por vencer**: vence en 180 días o menos.
- **Vigente**: el resto.

Para convenios con renovación automática, `fin_periodo_actual` es el fin del periodo en curso; al renovarse, actualice esa fecha.

## Alertas por correo
1. Cree una cuenta remitente con contraseña de aplicación (Gmail u Office 365).
2. Para el tablero: copie `.streamlit/secrets.toml.example` como `.streamlit/secrets.toml` y complete los datos (en Streamlit Cloud, péguelos en *Settings > Secrets*). La pestaña “Alertas por correo” permite previsualizar y enviar.
3. Para envío automático elija una opción:
   - **GitHub Actions** (incluido en `.github/workflows/alertas.yml`): cargue los secretos `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_FROM`, `ALERT_TO` y `TABLERO_URL` en el repositorio. Envía a diario las alertas por hito (180, 120, 90, 60, 30, 15, 7, 3, 1 y 0 días del vencimiento; 30, 15, 7, 3, 1 y 0 días de la fecha límite de aviso) y los lunes un resumen.
   - **Windows (Programador de tareas)** o **cron**: ejecutar `python enviar_alertas.py --modo hitos` a diario y `--modo resumen` semanalmente, con las variables de entorno anteriores.
   - Prueba sin enviar: `python enviar_alertas.py --modo resumen --simular`.

## Pendientes de verificación detectados al revisar los PDF
- INSPIRA vence el 20/11/2026 y la fecha para comunicar la renovación (60 días antes) ya pasó.
- FPC: solo se archivó la 2.a adenda (2023); faltan el convenio de 2013 y la 1.a adenda de 2016.
- FOSFAP y FOSMAR vencidos desde 2024 (en negociación).
- Fechas de MAGIA (2026) y Fundación Wiese (2026) tomadas del Anexo 1; los PDF no muestran el día de firma legible.
