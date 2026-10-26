#!/usr/bin/env python3
"""
CMg en tiempo real (preliminar) COES -> Telegram.
Barras: SANTA ROSA 220, SOCABAYA 220 y PIURA 220.

Reporte nocturno (00:20): promedio diario desde el día 1 del mes en curso,
en USD/MWh, más el promedio acumulado del mes por barra.

Fuentes (portal público del COES):
  POST .../costosmarginales/listaproceso  fecha=dd/mm/aaaa  -> intervalos del día
  POST .../costosmarginales/mapa          correlativo=N     -> CMg por barra

Histórico de intervalos en data/cmg.csv (S/ por MWh, tal como publica el COES).
Variables de entorno: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (obligatorias);
TC (default 3.45), ALERTA_CMG (USD/MWh, opcional).
"""
import calendar
import csv
import json
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
ALERTA = float(os.getenv("ALERTA_CMG") or 0)

# etiqueta -> (regex del nombre en el COES, palabra clave para el diagnóstico, color)
BARRAS = {
    "Santa Rosa 220": (r"^S(AN)?TA\.?\s*ROSA\s*220$", "ROSA", "#1a73e8"),
    "Socabaya 220": (r"^SOCABAYA\s*220$", "SOCABAYA", "#e8710a"),
    "Piura 220": (r"^PIURA(\s*OESTE)?\s*220$", "PIURA", "#188038"),
}
SIN_DATO = "nd"                    # intervalo consultado, barra no publicada

CSV_PATH = Path("data") / "cmg.csv"
PRESUPUESTO_SEG = 12 * 60
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


def leer_mapa(correlativo):
    """{nombre barra normalizado: CMg total S/ por MWh} de todo el SEIN en un intervalo."""
    html = post(f"{BASE}/mapa", {"correlativo": correlativo, "defecto": "S"}).text
    out = {}
    for bloque in html.split("coorx:")[1:]:
        m = re.search(r"Barra:\s*([^<]+)<", bloque)
        t = re.search(r">\s*Total\s*<.*?MWh\s*(-?[\d.,]+)", bloque, re.S)
        if m and t:
            out[norm(m.group(1))] = float(t.group(1).replace(",", ""))
    return out


def elegir(mapa, regex):
    """Valor de la barra; si calzan varias (p.ej. PIURA 220 y PIURA OESTE 220) toma la más corta."""
    nombres = sorted((n for n in mapa if re.search(regex, n)), key=len)
    return (nombres[0], mapa[nombres[0]]) if nombres else (None, None)


# --------------------------------------------------------------------------- histórico
def leer_hist():
    """{ts: {"corr": int, etiqueta: float | SIN_DATO}}"""
    if not CSV_PATH.exists():
        return {}
    hist = {}
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            reg = {"corr": int(r["correlativo"])}
            if "cmg_soles" in r:                       # formato anterior: solo Santa Rosa
                r = {**r, "Santa Rosa 220": r["cmg_soles"]}
            for b in BARRAS:
                v = (r.get(b) or "").strip()
                if v == SIN_DATO:
                    reg[b] = SIN_DATO
                elif v:
                    reg[b] = float(v)
            hist[dt.datetime.fromisoformat(r["ts"])] = reg
    return hist


def guardar_hist(hist):
    CSV_PATH.parent.mkdir(exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "correlativo", *BARRAS])
        for ts in sorted(hist):
            reg = hist[ts]
            fila = [ts.isoformat(), reg["corr"]]
            for b in BARRAS:
                v = reg.get(b)
                fila.append("" if v is None else v if v == SIN_DATO else f"{v:.2f}")
            w.writerow(fila)


def dia_operativo(ts):
    """El intervalo que termina a las 00:00 pertenece al día anterior (24:00)."""
    return (ts - dt.timedelta(minutes=1)).date()


def incompleto(reg):
    return any(b not in reg for b in BARRAS)


def actualizar(hist, hoy):
    pendientes, dia = [], hoy.replace(day=1)
    while dia <= hoy:
        del_dia = [t for t in hist if dia_operativo(t) == dia]
        if dia == hoy or len(del_dia) < 48 or any(incompleto(hist[t]) for t in del_dia):
            for ts, corr in procesos_del_dia(dia).items():
                if ts not in hist or corr > hist[ts]["corr"] or incompleto(hist[ts]):
                    pendientes.append((ts, corr))
        dia += dt.timedelta(days=1)

    pendientes.sort(reverse=True)            # primero lo más reciente
    t0, nuevos, fallos, nombres, muestra = time.time(), 0, 0, {}, {}
    with ThreadPoolExecutor(HILOS) as ex:
        futuros = {ex.submit(leer_mapa, c): (ts, c) for ts, c in pendientes}
        for fut in as_completed(futuros):
            ts, c = futuros[fut]
            try:
                mapa = fut.result()
            except Exception:
                fallos += 1
                continue
            if mapa:
                muestra = mapa
                reg = {"corr": c}
                for b, (rx, _, _) in BARRAS.items():
                    nombre, val = elegir(mapa, rx)
                    reg[b] = SIN_DATO if val is None else val
                    if nombre:
                        nombres[b] = nombre
                hist[ts] = reg
                nuevos += 1
            if time.time() - t0 > PRESUPUESTO_SEG:
                for f in futuros:
                    f.cancel()
                break
    faltan = max(len(pendientes) - nuevos - fallos, 0)
    return nombres, muestra, nuevos, faltan


# --------------------------------------------------------------------------- bloques horarios
# Intervalo de 30 min identificado por su hora de FIN; se clasifica por su hora de INICIO.
BLOQUES = {"Punta (18-23 h)": "#c5221f", "Media (6-18 h)": "#f29900", "Base (23-6 h)": "#188038"}


def bloque(ts):
    h = (ts - dt.timedelta(minutes=30)).hour
    if 18 <= h < 23:
        return "Punta (18-23 h)"
    if 6 <= h < 18:
        return "Media (6-18 h)"
    return "Base (23-6 h)"


def promedio(v):
    return sum(v) / len(v) if v else None


# --------------------------------------------------------------------------- gráficos
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
SR = "Santa Rosa 220"


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _formato(ax, fig, hoy, titulo, nota):
    ndias = calendar.monthrange(hoy.year, hoy.month)[1]
    ax.set_xlim(0.4, ndias + 0.6)
    ax.set_xticks(range(1, ndias + 1))
    ax.tick_params(axis="x", labelsize=7)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_ylabel("USD/MWh", fontsize=9)
    ax.set_xlabel(f"Día de {MESES[hoy.month - 1]} {hoy.year}", fontsize=9)
    ax.set_title(titulo, fontsize=10)
    ax.grid(alpha=0.3)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.text(0.99, 0.01, f"Fuente: COES (CMg tiempo real preliminar, PR-07) · TC {TC:.2f} S/ por USD{nota}",
             ha="right", fontsize=6, color="#5f6368")


def _etiqueta_final(ax, x, y, texto, color):
    ax.annotate(texto, (x, y), xytext=(6, 0), textcoords="offset points", va="center",
                fontsize=7.5, color=color, weight="bold")


def _etiquetas_separadas(ax, x, items):
    """items = [(y, texto, color)]; separa verticalmente para que no se superpongan."""
    if not items:
        return
    y0, y1 = ax.get_ylim()
    gap = (y1 - y0) * 0.075
    items = sorted(items)
    pos = [items[0][0]]
    for y, _, _ in items[1:]:
        pos.append(max(y, pos[-1] + gap))
    for p, (_, texto, color) in zip(pos, items):
        _etiqueta_final(ax, x, p, texto, color)


def grafico_sr_barras(diario, prom_mes, n_dia, hoy, ruta):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=160)
    color = BARRAS[SR][2]
    for d, v in sorted(diario.items()):
        parcial = d == hoy and n_dia < 48
        ax.bar(d.day, v, width=0.75, color=color, alpha=0.45 if parcial else 0.9,
               hatch="//" if parcial else None, edgecolor=color, lw=0.5)
        ax.text(d.day, v, f"{v:.0f}", ha="center", va="bottom", fontsize=6.5, rotation=90)
    ax.axhline(prom_mes, color="#c5221f", lw=1.3, ls="--")
    ndias = calendar.monthrange(hoy.year, hoy.month)[1]
    _etiqueta_final(ax, ndias + 0.3, prom_mes, f"Prom. mes\n{prom_mes:.2f}", "#c5221f")
    if ALERTA:
        ax.axhline(ALERTA, color="#5f6368", lw=1, ls=":")
    _formato(ax, fig, hoy, f"Santa Rosa 220 kV · CMg promedio diario · {MESES[hoy.month - 1]} {hoy.year}",
             " · rayado = día incompleto")
    ax.set_xlim(0.4, ndias + 2.6)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)


def grafico_lineas_barras(diario_b, prom_mes_b, hoy, ruta):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=160)
    ndias = calendar.monthrange(hoy.year, hoy.month)[1]
    etiquetas = []
    for b, (_, _, color) in BARRAS.items():
        if not diario_b.get(b):
            continue
        dias = sorted(diario_b[b])
        vals = [diario_b[b][d] for d in dias]
        ax.plot([d.day for d in dias], vals, color=color, lw=2, marker="o", ms=3.5, label=b)
        ax.axhline(prom_mes_b[b], color=color, lw=0.9, ls="--", alpha=0.8)
        etiquetas.append((prom_mes_b[b], f"{b.replace(' 220', '')}\n{prom_mes_b[b]:.2f}", color))
    _formato(ax, fig, hoy, f"CMg promedio diario por barra · {MESES[hoy.month - 1]} {hoy.year}",
             " · derecha = promedio del mes")
    ax.set_xlim(0.4, ndias + 3.2)
    _etiquetas_separadas(ax, ndias + 0.3, etiquetas)
    ax.legend(fontsize=7.5, loc="upper left", frameon=False, ncol=3)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)


def grafico_sr_bloques(diario, diario_bl, prom_mes, prom_mes_bl, hoy, ruta):
    """Bloques en barras agrupadas; promedio diario en línea."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=160)
    ndias = calendar.monthrange(hoy.year, hoy.month)[1]
    activos = [bl for bl in BLOQUES if diario_bl.get(bl)]
    ancho = 0.8 / max(len(activos), 1)
    etiquetas = []
    for i, bl in enumerate(activos):
        color = BLOQUES[bl]
        off = (i - (len(activos) - 1) / 2) * ancho
        dias = sorted(diario_bl[bl])
        ax.bar([d.day + off for d in dias], [diario_bl[bl][d] for d in dias], width=ancho,
               color=color, alpha=0.55, label=bl, zorder=2)
        if prom_mes_bl[bl] is not None:
            etiquetas.append((prom_mes_bl[bl], f"{bl.split(' (')[0]}\n{prom_mes_bl[bl]:.2f}", color))
    if diario:
        dias = sorted(diario)
        import matplotlib.patheffects as pe
        ax.plot([d.day for d in dias], [diario[d] for d in dias], color="#0b57d0", lw=2.8,
                marker="o", ms=5, markeredgecolor="white", markeredgewidth=1,
                label="Promedio diario", zorder=10,
                path_effects=[pe.Stroke(linewidth=5, foreground="white"), pe.Normal()])
        etiquetas.append((prom_mes, f"Prom. diario\n{prom_mes:.2f}", "#1a73e8"))
    _formato(ax, fig, hoy, f"Santa Rosa 220 kV · bloques y promedio diario · {MESES[hoy.month - 1]} {hoy.year}",
             " · derecha = promedio del mes")
    ax.grid(axis="x", visible=False)
    ax.set_xlim(0.4, ndias + 3.2)
    _etiquetas_separadas(ax, ndias + 0.3, etiquetas)
    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.45, -0.13), frameon=False, ncol=4)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)


def grafico_30min(hist, hoy, ruta):
    """CMg cada 30 min de las 3 barras: día anterior (arriba) y día del reporte (abajo)."""
    plt = _plt()
    from matplotlib.ticker import MultipleLocator
    ayer = hoy - dt.timedelta(days=1)
    fig, axes = plt.subplots(2, 1, figsize=(8.5, 7.6), dpi=160, sharex=True, sharey=True)
    for ax, dia in zip(axes, (ayer, hoy)):
        pts = sorted((t, r) for t, r in hist.items() if dia_operativo(t) == dia)
        ax.axvspan(18, 23, color="#c5221f", alpha=0.06, lw=0)
        for b, (_, _, color) in BARRAS.items():
            xs = [((t - dt.timedelta(minutes=1)).hour * 60 + (t - dt.timedelta(minutes=1)).minute + 1) / 60
                  for t, r in pts if isinstance(r.get(b), float)]
            ys = [r[b] / TC for t, r in pts if isinstance(r.get(b), float)]
            if xs:
                ax.plot(xs, ys, color=color, lw=1.8, marker="o", ms=2.5, label=b)
                ax.annotate(f"{ys[-1]:.0f}", (xs[-1], ys[-1]), xytext=(4, 0), textcoords="offset points",
                            va="center", fontsize=7, color=color, weight="bold")
        n = len(pts)
        ultimo = f" · hasta {pts[-1][0]:%H:%M}" if pts and n < 48 else ""
        etiqueta = "Día anterior" if dia == ayer else "Día del reporte"
        ax.set_title(f"{etiqueta}: {dia:%d/%m/%Y} ({n}/48){ultimo}", fontsize=9, loc="left")
        ax.grid(alpha=0.3)
        ax.set_ylabel("USD/MWh", fontsize=8)
        ax.tick_params(labelsize=7)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[0].text(20.5, axes[0].get_ylim()[1], "Punta", ha="center", va="top", fontsize=7, color="#c5221f")
    axes[1].set_xlim(0, 24.8)
    axes[1].xaxis.set_major_locator(MultipleLocator(2))
    axes[1].xaxis.set_minor_locator(MultipleLocator(0.5))
    axes[1].set_xticks(range(0, 25, 2), [f"{h:02d}:00" for h in range(0, 25, 2)])
    axes[1].set_xlabel("Hora (fin del intervalo de 30 min)", fontsize=8)
    axes[0].legend(fontsize=7.5, loc="upper left", frameon=False, ncol=3)
    fig.suptitle("CMg tiempo real cada 30 min · USD/MWh", fontsize=10)
    fig.text(0.99, 0.005, f"Fuente: COES (CMg tiempo real preliminar, PR-07) · TC {TC:.2f} S/ por USD · "
             "franja roja = punta 18-23 h", ha="right", fontsize=6, color="#5f6368")
    fig.tight_layout(rect=(0, 0.015, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)


# --------------------------------------------------------------------------- telegram
def tg(metodo, **kw):
    r = requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/{metodo}",
                      timeout=60, **kw)
    if not r.ok:
        print("Telegram:", r.status_code, r.text, file=sys.stderr)
    r.raise_for_status()


def pidio_actualizar(chat):
    """Revisa si en el chat escribiste 'actualiza'. Confirma los mensajes leídos para no repetirlos."""
    r = requests.get(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/getUpdates",
                     params={"timeout": 0}, timeout=30).json()
    updates = r.get("result", [])
    if not updates:
        return False
    pedido = any(str(u.get("message", {}).get("chat", {}).get("id")) == str(chat)
                 and "ACTUALIZA" in norm(u.get("message", {}).get("text", ""))
                 for u in updates)
    ultimo = max(u["update_id"] for u in updates)
    requests.get(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/getUpdates",
                 params={"offset": ultimo + 1, "timeout": 0}, timeout=30)
    return pedido


def main():
    chat = os.environ["TELEGRAM_CHAT_ID"]
    if os.getenv("MODO") == "escucha":
        if not pidio_actualizar(chat):
            print("Sin pedidos de actualización")
            return
        tg("sendMessage", data={"chat_id": chat, "text": "⏳ Actualizando CMg… en unos minutos te llegan los gráficos."})
    ahora = dt.datetime.now(LIMA)
    hoy = dia_operativo(ahora - dt.timedelta(minutes=30))   # a las 00:20 reporta el día que cerró
    hist = leer_hist()
    try:
        nombres, muestra, nuevos, faltan = actualizar(hist, hoy)
    except Exception as e:
        guardar_hist(hist)
        tg("sendMessage", data={"chat_id": chat, "text": f"⚠️ CMg: error consultando COES: {e}"})
        raise
    guardar_hist(hist)

    mes = {t: r for t, r in hist.items()
           if (dia_operativo(t).year, dia_operativo(t).month) == (hoy.year, hoy.month)}
    if not mes:
        tg("sendMessage", data={"chat_id": chat, "text": "⚠️ CMg: no hay datos del mes en el COES."})
        sys.exit(1)

    # promedios por barra (USD/MWh)
    diario_b, prom_mes_b = {}, {}
    for b in BARRAS:
        por_dia = {}
        for t, r in mes.items():
            if isinstance(r.get(b), float):
                por_dia.setdefault(dia_operativo(t), []).append(r[b] / TC)
        diario_b[b] = {d: promedio(v) for d, v in por_dia.items()}
        prom_mes_b[b] = promedio([x for v in por_dia.values() for x in v])

    # Santa Rosa por bloques
    diario_bl, prom_mes_bl = {}, {}
    for bl in BLOQUES:
        por_dia = {}
        for t, r in mes.items():
            if isinstance(r.get(SR), float) and bloque(t) == bl:
                por_dia.setdefault(dia_operativo(t), []).append(r[SR] / TC)
        diario_bl[bl] = {d: promedio(v) for d, v in por_dia.items()}
        prom_mes_bl[bl] = promedio([x for v in por_dia.values() for x in v])

    n_dia = sum(1 for t in mes if dia_operativo(t) == hoy)
    rutas = [Path("g1_santarosa.png"), Path("g2_barras.png"), Path("g3_bloques.png"),
             Path("g4_30min.png")]
    if prom_mes_b[SR] is not None:
        grafico_sr_barras(diario_b[SR], prom_mes_b[SR], n_dia, hoy, rutas[0])
        grafico_sr_bloques(diario_b[SR], diario_bl, prom_mes_b[SR], prom_mes_bl, hoy, rutas[2])
    grafico_lineas_barras(diario_b, prom_mes_b, hoy, rutas[1])
    grafico_30min(hist, hoy, rutas[3])
    rutas = [p for p in rutas if p.exists()]

    def f2(v):
        return f"{v:.2f}" if v is not None else "–"

    alerta = bool(ALERTA and any((diario_b[b].get(hoy) or 0) >= ALERTA for b in BARRAS))
    lineas = [f"{'🚨 ' if alerta else ''}*CMg promedio · USD/MWh* (TC {TC:.2f})",
              f"Día {hoy:%d/%m} ({n_dia}/48) | Mes a la fecha"]
    for b in BARRAS:
        if prom_mes_b[b] is None:
            sugeridos = [n for n in muestra if BARRAS[b][1] in n][:6]
            lineas.append(f"• {b}: no encontrada. Nombres en COES: {', '.join(sugeridos) or 'ninguno'}")
        else:
            lineas.append(f"• {b}: {f2(diario_b[b].get(hoy))} | *{f2(prom_mes_b[b])}*")
    lineas.append("*Santa Rosa por bloque* (día | mes)")
    for bl in BLOQUES:
        lineas.append(f"• {bl}: {f2(diario_bl[bl].get(hoy))} | *{f2(prom_mes_bl[bl])}*")
    if faltan:
        lineas.append(f"⏳ Completando histórico: faltan {faltan} intervalos")

    media = [{"type": "photo", "media": f"attach://g{i}"} for i in range(len(rutas))]
    media[0].update(caption="\n".join(lineas), parse_mode="Markdown")
    archivos = {f"g{i}": p.open("rb") for i, p in enumerate(rutas)}
    try:
        tg("sendMediaGroup", data={"chat_id": chat, "media": json.dumps(media),
                                   "disable_notification": "false" if alerta else "true"},
           files=archivos)
    finally:
        for f in archivos.values():
            f.close()
    print(f"OK nombres={nombres} nuevos={nuevos} faltan={faltan}")


if __name__ == "__main__":
    main()
