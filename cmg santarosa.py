#!/usr/bin/env python3
"""
CMg en tiempo real (preliminar) COES - Barra SANTA ROSA 220 -> Telegram.

Grafica el PROMEDIO DIARIO desde el día 1 del mes en curso, en USD/MWh,
y reporta el promedio acumulado del mes.

Fuentes (portal público del COES):
  POST .../costosmarginales/listaproceso  fecha=dd/mm/aaaa  -> intervalos del día
  POST .../costosmarginales/mapa          correlativo=N     -> CMg por barra

Histórico de intervalos en data/cmg.csv (en S/ por MWh, tal como publica el COES).
Variables de entorno: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (obligatorias);
TC (default 3.45), BARRA_REGEX, ALERTA_CMG (USD/MWh, opcional).
"""
import calendar
import csv
import datetime as dt
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

LIMA = ZoneInfo("America/Lima")
BASE = "https://www.coes.org.pe/Portal/mercadomayorista/costosmarginales"
TC = float(os.getenv("TC") or 3.45)
BARRA_RE = re.compile(os.getenv("BARRA_REGEX") or r"^S(AN)?TA\.?\s*ROSA\s*220$", re.I)
ALERTA = float(os.getenv("ALERTA_CMG") or 0)
CSV_PATH = Path("data") / "cmg.csv"
PNG_PATH = Path("cmg.png")
PRESUPUESTO_SEG = 6 * 60          # tiempo máximo de descarga por ejecución
HILOS = 4

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE}/index",
})


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def post(url, data, intentos=3):
    for i in range(intentos):
        try:
            r = S.post(url, data=data, timeout=45)
            r.raise_for_status()
            return r
        except Exception:
            if i == intentos - 1:
                raise
            time.sleep(3 * (i + 1))


# --------------------------------------------------------------------------- COES
def procesos_del_dia(dia: dt.date):
    """{timestamp Lima: correlativo}; si hay reprocesos se queda con el mayor."""
    r = post(f"{BASE}/listaproceso", {"fecha": dia.strftime("%d/%m/%Y")})
    out = {}
    for p in r.json():
        m = re.search(r"/Date\((\d+)", str(p.get("Cmgnfecha")))
        corr = p.get("Cmgncorrelativo")
        if not m or not corr:
            continue
        ts = dt.datetime.fromtimestamp(int(m.group(1)) / 1000, LIMA)
        if corr > out.get(ts, 0):
            out[ts] = corr
    return out


def cmg_barra(correlativo):
    """CMg total (S/ por MWh) de la barra en un intervalo."""
    html = post(f"{BASE}/mapa", {"correlativo": correlativo, "defecto": "S"}).text
    for bloque in html.split("coorx:")[1:]:
        m = re.search(r"Barra:\s*([^<]+)<", bloque)
        if not m or not BARRA_RE.search(norm(m.group(1))):
            continue
        t = re.search(r">\s*Total\s*<.*?MWh\s*(-?[\d.,]+)", bloque, re.S)
        if t:
            return norm(m.group(1)), float(t.group(1).replace(",", ""))
    return None, None


# --------------------------------------------------------------------------- histórico
def leer_hist():
    if not CSV_PATH.exists():
        return {}
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return {dt.datetime.fromisoformat(r["ts"]): (int(r["correlativo"]), float(r["cmg_soles"]))
                for r in csv.DictReader(f)}


def guardar_hist(hist):
    CSV_PATH.parent.mkdir(exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "correlativo", "cmg_soles"])
        for ts in sorted(hist):
            corr, v = hist[ts]
            w.writerow([ts.isoformat(), corr, f"{v:.2f}"])


def dia_operativo(ts):
    """El intervalo que termina a las 00:00 pertenece al día anterior (24:00)."""
    return (ts - dt.timedelta(minutes=1)).date()


def actualizar(hist, hoy):
    inicio = hoy.replace(day=1)
    pendientes = []          # (ts, correlativo)
    dia = inicio
    while dia <= hoy:
        completos = sum(1 for t in hist if dia_operativo(t) == dia)
        if dia == hoy or completos < 48:
            for ts, corr in procesos_del_dia(dia).items():
                if ts not in hist or corr > hist[ts][0]:
                    pendientes.append((ts, corr))
        dia += dt.timedelta(days=1)

    pendientes.sort(reverse=True)            # primero lo más reciente
    t0, nuevos, fallos, barra = time.time(), 0, 0, None
    with ThreadPoolExecutor(HILOS) as ex:
        futuros = {ex.submit(cmg_barra, c): (ts, c) for ts, c in pendientes}
        for fut in as_completed(futuros):
            ts, c = futuros[fut]
            try:
                nombre, val = fut.result()
            except Exception:
                fallos += 1
                continue
            if val is not None:
                hist[ts] = (c, val)
                barra, nuevos = nombre, nuevos + 1
            if time.time() - t0 > PRESUPUESTO_SEG:
                for f in futuros:
                    f.cancel()
                break
    faltan = max(len(pendientes) - nuevos - fallos, 0)
    return barra, nuevos, faltan


# --------------------------------------------------------------------------- gráfico
def graficar(prom_dia, hoy, prom_mes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ndias = calendar.monthrange(hoy.year, hoy.month)[1]
    dias = list(range(1, ndias + 1))
    vals = [prom_dia.get(hoy.replace(day=d)) for d in dias]

    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=160)
    for d, v in zip(dias, vals):
        if v is None:
            continue
        parcial = d == hoy.day
        ax.bar(d, v, width=0.75, color="#8ab4f8" if parcial else "#1a73e8",
               hatch="//" if parcial else None, edgecolor="#1a73e8", lw=0.6)
        ax.text(d, v, f"{v:.0f}", ha="center", va="bottom", fontsize=6.5, rotation=90 if ndias > 20 else 0,
                color="#202124")
    if prom_mes is not None:
        ax.axhline(prom_mes, color="#c5221f", lw=1.2, ls="--")
        ax.text(ndias + 0.6, prom_mes, f"Prom. mes\n{prom_mes:.2f}", va="center", ha="left",
                fontsize=7.5, color="#c5221f", weight="bold")
    if ALERTA:
        ax.axhline(ALERTA, color="#f29900", lw=1, ls=":")

    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]
    ax.set_xlim(0.3, ndias + 0.7)
    ax.set_xticks(dias, [str(d) for d in dias], fontsize=7)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_ylabel("CMg promedio diario (USD/MWh)", fontsize=9)
    ax.set_xlabel(f"Día de {meses[hoy.month - 1]} {hoy.year}", fontsize=9)
    ax.set_title(f"CMg tiempo real · Barra Santa Rosa 220 kV · {meses[hoy.month - 1].capitalize()} {hoy.year}",
                 fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.text(0.99, 0.01, f"Fuente: COES (preliminar, PR-07) · TC {TC:.2f} S/ por USD · "
             "barra rayada = día en curso", ha="right", fontsize=6, color="#5f6368")
    fig.tight_layout(rect=(0, 0.02, 0.93, 1))
    fig.savefig(PNG_PATH)
    plt.close(fig)


# --------------------------------------------------------------------------- telegram
def tg(metodo, **kw):
    r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/{metodo}",
                      timeout=60, **kw)
    if not r.ok:
        print("Telegram:", r.status_code, r.text, file=sys.stderr)
    r.raise_for_status()


def main():
    chat = os.environ["TELEGRAM_CHAT_ID"]
    ahora = dt.datetime.now(LIMA)
    hoy = dia_operativo(ahora)
    hist = leer_hist()
    try:
        barra, nuevos, faltan = actualizar(hist, hoy)
    except Exception as e:
        guardar_hist(hist)
        tg("sendMessage", data={"chat_id": chat, "text": f"⚠️ CMg Santa Rosa: error consultando COES: {e}"})
        raise
    guardar_hist(hist)

    mes = {t: v for t, (_, v) in hist.items()
           if dia_operativo(t).year == hoy.year and dia_operativo(t).month == hoy.month}
    if not mes:
        tg("sendMessage", data={"chat_id": chat,
                                "text": "⚠️ CMg Santa Rosa: no se encontraron datos de la barra en el mes."})
        sys.exit(1)

    por_dia = {}
    for t, v in mes.items():
        por_dia.setdefault(dia_operativo(t), []).append(v / TC)
    prom_dia = {d: sum(v) / len(v) for d, v in por_dia.items()}
    todos = [v / TC for v in mes.values()]
    prom_mes = sum(todos) / len(todos)

    graficar(prom_dia, hoy, prom_mes)

    t_ult = max(mes)
    ult = mes[t_ult] / TC
    hoy_prom = prom_dia.get(hoy)
    hoy_n = len(por_dia.get(hoy, []))
    alerta = bool(ALERTA and ult >= ALERTA)
    texto = (f"{'🚨 ' if alerta else ''}*CMg Santa Rosa 220 kV* (USD/MWh, TC {TC:.2f})\n"
             f"Promedio del mes: *{prom_mes:.2f}* ({len(por_dia)} días)\n")
    if hoy_prom is not None:
        texto += f"Hoy (parcial, {hoy_n}/48): {hoy_prom:.2f}\n"
    texto += f"Último intervalo {t_ult:%d/%m %H:%M}: {ult:.2f}"
    if faltan:
        texto += f"\n⏳ Completando histórico: faltan {faltan} intervalos (se completan en las próximas corridas)"

    with PNG_PATH.open("rb") as f:
        tg("sendPhoto", data={"chat_id": chat, "caption": texto, "parse_mode": "Markdown",
                              "disable_notification": "false" if alerta else "true"},
           files={"photo": f})
    print(f"OK barra={barra} nuevos={nuevos} faltan={faltan} prom_mes={prom_mes:.2f} USD/MWh")


if __name__ == "__main__":
    main()
