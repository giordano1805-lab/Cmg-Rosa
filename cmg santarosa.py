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
    "Santa Rosa 220": (r"^S(AN)?TA\.?\s*ROSA\s*220$", "ROSA", "#2b4fd1"),
    "Socabaya 220": (r"^SOCABAYA\s*220$", "SOCABAYA", "#f0590f"),
    "Piura 220": (r"^PIURA(\s*OESTE)?\s*220$", "PIURA", "#e9a300"),
}
SIN_DATO = "nd"                    # intervalo consultado, barra no publicada

# Barras para valorizar CH Huanchor (no son referencias de mercado; no se mezclan con BARRAS).
# Prioridad por intervalo: Huanchor 50 kV -> Matucana -> sin dato. Nunca Santa Rosa.
# El nombre exacto publicado por el COES se guarda en data/barras_huanchor.json (con todas las
# candidatas) para verificar identificador y tensión; MATUCANA_BARRA fija una barra concreta.
BARRAS_HU = {
    "Huanchor 50": (r"^(C\.?H\.?\s*)?HUANCHOR\s*50(\s*KV)?$", "HUANCHOR", "#ff5716"),
    "Matucana": (os.getenv("MATUCANA_BARRA") or r"^MATUCANA\s*\d+(\s*KV)?$", "MATUCANA", "#6b7a99"),
}
TODAS = {**BARRAS, **BARRAS_HU}
DIAG_HU = Path("data") / "barras_huanchor.json"

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
            for b in TODAS:
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
        w.writerow(["ts", "correlativo", *TODAS])
        for ts in sorted(hist):
            reg = hist[ts]
            fila = [ts.isoformat(), reg["corr"]]
            for b in TODAS:
                v = reg.get(b)
                fila.append("" if v is None else v if v == SIN_DATO else f"{v:.2f}")
            w.writerow(fila)


def dia_operativo(ts):
    """El intervalo que termina a las 00:00 pertenece al día anterior (24:00)."""
    return (ts - dt.timedelta(minutes=1)).date()


def incompleto(reg):
    return any(b not in reg for b in TODAS)


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
                for b, (rx, _, _) in TODAS.items():
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
    if muestra:
        guardar_diag_hu(muestra, nombres)
    return nombres, muestra, nuevos, faltan


def guardar_diag_hu(muestra, nombres):
    """Deja constancia de qué barra exacta se usó para Huanchor/Matucana y qué candidatas publica el COES."""
    try:
        DIAG_HU.parent.mkdir(exist_ok=True)
        DIAG_HU.write_text(json.dumps({
            "actualizado": dt.datetime.now(LIMA).isoformat(timespec="minutes"),
            "usadas": {b: nombres.get(b) for b in BARRAS_HU},
            "regex": {b: rx for b, (rx, _, _) in BARRAS_HU.items()},
            "candidatas": {b: sorted(n for n in muestra if kw in n) for b, (_, kw, _) in BARRAS_HU.items()},
            "total_barras_mapa": len(muestra),
            "barras_mapa": sorted(muestra),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print("diag barras Huanchor:", e, file=sys.stderr)


def leer_diag_hu():
    try:
        return json.loads(DIAG_HU.read_text(encoding="utf-8"))
    except Exception:
        return {}


# --------------------------------------------------------------------------- bloques horarios
# Intervalo de 30 min identificado por su hora de FIN; se clasifica por su hora de INICIO.
BLOQUES = {"Punta (18-23 h)": "#f0590f", "Media (6-18 h)": "#e9a300", "Base (23-6 h)": "#6f8bf5"}


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
    ax.axhline(prom_mes, color="#001a6f", lw=1.3, ls="--")
    ndias = calendar.monthrange(hoy.year, hoy.month)[1]
    _etiqueta_final(ax, ndias + 0.3, prom_mes, f"Prom. mes\n{prom_mes:.2f}", "#001a6f")
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
        ax.plot([d.day for d in dias], [diario[d] for d in dias], color="#001a6f", lw=2.8,
                marker="o", ms=5, markeredgecolor="white", markeredgewidth=1,
                label="Promedio diario", zorder=10,
                path_effects=[pe.Stroke(linewidth=5, foreground="white"), pe.Normal()])
        etiquetas.append((prom_mes, f"Prom. diario\n{prom_mes:.2f}", "#001a6f"))
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
        ax.axvspan(18, 23, color="#ff861d", alpha=0.08, lw=0)
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
    axes[0].text(20.5, axes[0].get_ylim()[1], "Punta", ha="center", va="top", fontsize=7, color="#f0590f")
    axes[1].set_xlim(0, 24.8)
    axes[1].xaxis.set_major_locator(MultipleLocator(2))
    axes[1].xaxis.set_minor_locator(MultipleLocator(0.5))
    axes[1].set_xticks(range(0, 25, 2), [f"{h:02d}:00" for h in range(0, 25, 2)])
    axes[1].set_xlabel("Hora (fin del intervalo de 30 min)", fontsize=8)
    axes[0].legend(fontsize=7.5, loc="upper left", frameon=False, ncol=3)
    fig.suptitle("CMg tiempo real cada 30 min · USD/MWh", fontsize=10)
    fig.text(0.99, 0.005, f"Fuente: COES (CMg tiempo real preliminar, PR-07) · TC {TC:.2f} S/ por USD · "
             "franja naranja = punta 18-23 h", ha="right", fontsize=6, color="#5f6368")
    fig.tight_layout(rect=(0, 0.015, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)


# --------------------------------------------------------------------------- generación por recurso
GEN_URL = "https://www.coes.org.pe/Portal/portalinformacion/generacion"
# grupo -> (color, nombres COES normalizados que lo componen; la asignación real la hace grupo_de())
GRUPOS_GEN = {
    "Hídrica": ("#2b4fd1", ("HIDRICO", "HIDROELECTRICA")),
    "Gas natural": ("#f0590f", ("GAS", "GAS DE CAMISEA", "GAS DE MALACAS", "NAFTA & GAS REFINERIA")),
    "Solar": ("#e9a300", ("SOLAR",)),
    "Eólica": ("#1baf7a", ("EOLICA",)),
    "Carbón": ("#5f6368", ("CARBON",)),
    "Biomasa": ("#6250d6", ("BAGAZO", "BIOGAS")),
    "Diésel/Residual": ("#e34948", ("DIESEL", "RESIDUAL")),
    "Otros": ("#9aa0a6", ()),
}


def grupo_de(nombre):
    n = nombre.upper()
    if "HIDR" in n:
        return "Hídrica"
    if "SOLAR" in n:
        return "Solar"
    if "EOLIC" in n:
        return "Eólica"
    if "CARBON" in n:
        return "Carbón"
    if "BAGAZO" in n or "BIOGAS" in n or "BIOMASA" in n:
        return "Biomasa"
    if "RESIDUAL" in n or "DIESEL" in n:
        return "Diésel/Residual"
    if "GAS" in n or "REFINER" in n or "NAFTA" in n:      # el gas de refinería cuenta como gas
        return "Gas natural"
    return "Otros"


def _consulta_gen(desde, hasta, indicador):
    r = post(GEN_URL, {"fechaInicial": desde.strftime("%d/%m/%Y"),
                       "fechaFinal": hasta.strftime("%d/%m/%Y"),
                       "indicador": indicador})
    try:
        series = r.json()["GraficoTipoCombustible"]["Series"] or []
    except Exception:
        return {}
    out = {}
    for sr in series:
        nombre = norm(sr["Name"])
        for d in sr.get("Data") or []:
            try:
                ts = dt.datetime.strptime(d["Nombre"], "%Y/%m/%d %H:%M:%S").replace(tzinfo=LIMA)
            except Exception:
                continue
            if d.get("Valor") is not None:
                out.setdefault(ts, {})[nombre] = float(d["Valor"])
    return out


def generacion(ayer: dt.date, hoy: dt.date):
    """({ts: {recurso: MW}}, nota). Ayer y hoy se piden por separado; si hoy viene vacío
    con la fuente normal (indicador 0), se prueban las otras fuentes del portal."""
    gen, nota = {}, ""
    for dia in (ayer, hoy):
        datos = {}
        for ind in ((0,) if dia == ayer else (0, 1, 2, 3)):
            try:
                datos = {t: r for t, r in _consulta_gen(dia, dia + dt.timedelta(days=1), ind).items()
                         if dia_operativo(t) == dia and sum(r.values()) > 0}
            except Exception as e:
                print(f"generación {dia} indicador {ind}: {e}", file=sys.stderr)
                datos = {}
            print(f"generación {dia} indicador {ind}: {len(datos)} intervalos")
            if datos:
                if dia == hoy and ind != 0:
                    nota = f"hoy con fuente alternativa del portal (indicador {ind})"
                break
        if dia == hoy and not datos:
            nota = "el COES aún no publica la generación de hoy"
        gen.update(datos)
    _corregir_bagazo_solar(gen)
    return gen, nota


def _corregir_bagazo_solar(gen):
    """El COES a veces publica BAGAZO y SOLAR intercambiados: el solar debe ser ~0 de noche."""
    def amplitud(nombre):
        dia = [r.get(nombre, 0) for t, r in gen.items() if 11 <= t.hour <= 13]
        noche = [r.get(nombre, 0) for t, r in gen.items() if t.hour <= 4]
        return (promedio(dia) or 0) - (promedio(noche) or 0)
    if "BAGAZO" in str(gen) and amplitud("BAGAZO") > amplitud("SOLAR"):
        for r in gen.values():
            r["BAGAZO"], r["SOLAR"] = r.get("SOLAR", 0), r.get("BAGAZO", 0)


# Cuando el IEOD (HOP + despacho por unidad) permite separar el diésel:
GRUPOS_DIESEL = {"D2 Reserva Fría": "#8f1d2c", "Diésel/Residual otras": "#e34948"}


def agrupar(reg, split=None):
    """MW por grupo. split = {'rf': MW, 'otras': MW} separa el diésel (D2 de Reserva Fría / otras centrales)."""
    out = {g: 0.0 for g in GRUPOS_GEN}
    for nombre, mw in reg.items():
        out[grupo_de(nombre)] += mw
    if split is not None:
        dr = out.pop("Diésel/Residual")
        rf = min(split.get("rf", 0.0), dr)       # nunca más que lo que el COES reporta como diésel/residual
        res = {}
        for g, v in out.items():
            res[g] = v
            if g == "Biomasa":
                res["D2 Reserva Fría"] = rf
                res["Diésel/Residual otras"] = max(0.0, dr - rf)
        out = res
    return out


def min_dia(t):
    """Minutos desde el inicio del día operativo al fin del intervalo (30..1440)."""
    u = t - dt.timedelta(minutes=1)
    return u.hour * 60 + u.minute + 1


def color_grupo(g):
    return GRUPOS_GEN[g][0] if g in GRUPOS_GEN else GRUPOS_DIESEL.get(g, "#9aa0a6")


def grafico_generacion(gen, hoy, ruta, diesel=None, fuente=None):
    """diesel = {fecha: {min_dia: {'rf', 'otras'}}} para separar el D2 en los días con IEOD."""
    diesel = diesel or {}
    plt = _plt()
    from matplotlib.ticker import MultipleLocator
    ayer = hoy - dt.timedelta(days=1)
    fig, axes = plt.subplots(2, 1, figsize=(8.5, 7.6), dpi=160, sharex=True, sharey=True)
    for ax, dia in zip(axes, (ayer, hoy)):
        sd = diesel.get(dia)
        pts = sorted((t, agrupar(r, (sd.get(min_dia(t), {}) if sd is not None else None)))
                     for t, r in gen.items() if dia_operativo(t) == dia)
        if pts:
            xs = [min_dia(t) / 60 for t, _ in pts]
            orden = list(pts[0][1])
            grupos = [g for g in orden if any(r[g] > 0.5 for _, r in pts)]
            ax.stackplot(xs, [[r[g] for _, r in pts] for g in grupos],
                         colors=[color_grupo(g) for g in grupos], labels=grupos, alpha=0.9, lw=0)
            tot = [sum(r.values()) for _, r in pts]
            ax.plot(xs, tot, color="#001a6f", lw=1)
            i = max(range(len(tot)), key=tot.__getitem__)
            ax.annotate(f"máx {tot[i]:,.0f} MW · {pts[i][0]:%H:%M}", (xs[i], tot[i]), xytext=(0, 6),
                        textcoords="offset points", ha="center", fontsize=7, weight="bold")
        n = len(pts)
        ultimo = f" · hasta {pts[-1][0]:%H:%M}" if pts and n < 48 else ""
        etiqueta = "Día anterior" if dia == ayer else "Día del reporte"
        ax.set_title(f"{etiqueta}: {dia:%d/%m/%Y} ({n}/48){ultimo}", fontsize=9, loc="left")
        ax.grid(alpha=0.3)
        ax.set_ylabel("MW", fontsize=8)
        ax.tick_params(labelsize=7)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[1].set_xlim(0, 24)
    axes[1].set_ylim(bottom=0)
    axes[1].xaxis.set_minor_locator(MultipleLocator(0.5))
    axes[1].set_xticks(range(0, 25, 2), [f"{h:02d}:00" for h in range(0, 25, 2)])
    axes[1].set_xlabel("Hora (fin del intervalo de 30 min)", fontsize=8)
    vistos = {}
    for ax in axes:
        for hh, ll in zip(*ax.get_legend_handles_labels()):
            vistos.setdefault(ll, hh)
    h, l = list(vistos.values()), list(vistos)
    fig.legend(h[::-1], l[::-1], fontsize=7.5, loc="lower center", ncol=4, frameon=False,
               bbox_to_anchor=(0.5, 0.012))
    fig.suptitle("Producción del SEIN por tipo de recurso cada 30 min · MW", fontsize=10)
    fig.text(0.99, 0.003, fuente or "Fuente: COES (Portal de Información – Generación)", ha="right", fontsize=6,
             color="#5f6368")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)


def mix_del_dia(gen, dia):
    """Participación % en energía del día por grupo."""
    tot = {g: 0.0 for g in GRUPOS_GEN}
    for t, r in gen.items():
        if dia_operativo(t) == dia:
            for g, v in agrupar(r).items():
                tot[g] += v * 0.5                      # MW x 0.5 h = MWh
    suma = sum(tot.values())
    return (suma, {g: 100 * v / suma for g, v in tot.items()}) if suma else (0, {})


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
    MODO = (os.getenv("MODO") or "reporte").strip().lower()
    if MODO == "explora":
        import explorar
        res = explorar.main()
        ok = sum(1 for p in res["paginas"].values() if p.get("status") == 200)
        tg("sendMessage", data={"chat_id": chat,
                                "text": f"🔎 Exploración COES lista: {ok}/{len(res['paginas'])} páginas leídas. "
                                        "Avísale a Claude."})
        return
    if MODO in ("pdf", "dashboard"):
        # Actualiza el dashboard (y deja el PDF descargable desde ahí); a Telegram solo va el enlace
        import reporte
        ruta, bullets = reporte.generar(sys.modules[__name__])
        repo = os.getenv("GITHUB_REPOSITORY", "")
        url = (f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/" if "/" in repo else "")
        if url:
            tg("sendMessage", data={"chat_id": chat, "disable_web_page_preview": "true",
                                    "text": f"📊 Dashboard del SEIN actualizado ({ruta.stem[-10:]}):\n{url}"})
        print("OK dashboard", ruta)
        return
    if MODO == "escucha":
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
    lineas_gen = []
    try:
        gen, nota_gen = generacion(hoy - dt.timedelta(days=1), hoy)
        if gen:
            rutas.append(Path("g5_generacion.png"))
            grafico_generacion(gen, hoy, rutas[-1])
            mwh, mix = mix_del_dia(gen, hoy)
            if mix:
                top = sorted(((v, g) for g, v in mix.items() if v >= 0.5), reverse=True)
                lineas_gen = [f"*Mix de producción {hoy:%d/%m}* ({mwh / 1000:,.1f} GWh)",
                              " · ".join(f"{g} {v:.0f}%" for v, g in top)]
        if nota_gen:
            lineas_gen.append(f"ℹ️ Generación: {nota_gen}")
    except Exception as e:
        print("Generación no disponible:", e, file=sys.stderr)
        lineas_gen = ["(Generación por recurso no disponible en este momento)"]
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
    lineas += lineas_gen
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
