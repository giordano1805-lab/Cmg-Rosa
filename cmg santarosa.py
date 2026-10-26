#!/usr/bin/env python3
"""
CMg en tiempo real (preliminar) del COES - Barra Santa Rosa 220 kV -> Telegram.

Cada ejecución:
  1. Abre la página de CMg en tiempo real del COES con Chromium headless.
  2. Captura las respuestas de datos (XHR/fetch) y el HTML ya renderizado.
  3. Extrae el CMg de la barra Santa Rosa (regex configurable).
  4. Lo agrega al histórico data/cmg.csv (sin duplicar intervalos).
  5. Grafica hoy vs. ayer y envía la imagen a Telegram.
Si no encuentra la barra, envía un archivo de diagnóstico a Telegram.

Variables de entorno:
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID  (obligatorias)
  BARRA_REGEX   regex del nombre de barra (default: Santa Rosa 220)
  ALERTA_CMG    umbral en S/ / MWh; si se supera, la notificación suena
  FORZAR_DIAG   "1" para enviar siempre el diagnóstico
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

LIMA = ZoneInfo("America/Lima")
URL = "https://www.coes.org.pe/Portal/mercadomayorista/costosmarginales/index"
BARRA_RE = re.compile(os.getenv("BARRA_REGEX") or r"S(AN)?TA\.?\s*ROSA\D*220", re.I)
ALERTA = float(os.getenv("ALERTA_CMG") or 0)
FORZAR_DIAG = os.getenv("FORZAR_DIAG") == "1"
DATA = Path("data")
CSV_PATH = DATA / "cmg.csv"
PNG_PATH = Path("cmg.png")
DIAG_PATH = Path("diagnostico.txt")

EXCLUIR = ("cod", "id", "anio", "año", "mes", "dia", "hora", "fecha", "periodo",
           "interval", "nro", "num", "tension", "kv", "lat", "lon", "orden")


# --------------------------------------------------------------------------- utilidades
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def a_float(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip().replace(" ", "")
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})*,\d+", t):      # 1.234,56
            t = t.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"-?\d+,\d+", t):                  # 123,45
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
        try:
            return float(t)
        except ValueError:
            return None
    return None


def parse_ts(v, fecha_base=None):
    """Interpreta fechas/horas típicas de ASP.NET y formatos peruanos."""
    if v is None:
        return None
    s = str(v).strip()
    m = re.search(r"/Date\((-?\d+)", s)
    if m:
        return dt.datetime.fromtimestamp(int(m.group(1)) / 1000, tz=dt.timezone.utc).astimezone(LIMA)
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", s)
    if m:
        d, mo, y, h, mi = m.groups()
        base = dt.datetime(int(y), int(mo), int(d), tzinfo=LIMA)
        return base + dt.timedelta(hours=int(h or 0), minutes=int(mi or 0))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2}))?", s)
    if m:
        y, mo, d, h, mi = m.groups()
        base = dt.datetime(int(y), int(mo), int(d), tzinfo=LIMA)
        return base + dt.timedelta(hours=int(h or 0), minutes=int(mi or 0))
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(:\d{2})?", s)
    if m and fecha_base is not None:
        return fecha_base + dt.timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
    return None


def piso_30min(t: dt.datetime) -> dt.datetime:
    return t.replace(minute=(t.minute // 30) * 30, second=0, microsecond=0)


# --------------------------------------------------------------------------- captura
def capturar():
    from playwright.sync_api import sync_playwright

    respuestas, capturas = [], []
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page(locale="es-PE", timezone_id="America/Lima",
                          viewport={"width": 1400, "height": 1000})
        pg.on("response", lambda r: respuestas.append(r)
              if r.request.resource_type in ("xhr", "fetch") else None)
        pg.goto(URL, wait_until="networkidle", timeout=120_000)
        for texto in ("Datos", "Barras mayores a 138 KV"):
            try:
                pg.get_by_text(texto, exact=True).first.click(timeout=5_000)
                pg.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
        pg.wait_for_timeout(3_000)
        controles = pg.evaluate(
            "() => Array.from(document.querySelectorAll('input,select'))"
            ".map(e => [e.id || e.name || '', e.value || ''])")
        html = pg.content()
        for r in respuestas:
            try:
                capturas.append({"url": r.url, "post": r.request.post_data,
                                 "status": r.status, "texto": r.text()})
            except Exception as e:
                capturas.append({"url": r.url, "post": r.request.post_data,
                                 "status": r.status, "texto": f"<no legible: {e}>"})
        nav.close()
    return capturas, html, controles


def instante_pagina(controles):
    """Fecha y hora mostradas en los filtros de la página."""
    fecha = hora = None
    for _id, val in controles:
        if fecha is None and re.fullmatch(r"\d{2}/\d{2}/\d{4}", val.strip()):
            fecha = parse_ts(val)
        if hora is None and re.fullmatch(r"\d{1,2}:\d{2}", val.strip()):
            hora = val.strip()
    if fecha and hora:
        return parse_ts(hora, fecha)
    return None


# --------------------------------------------------------------------------- extracción
def recorrer(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from recorrer(v)
    elif isinstance(o, list):
        for v in o:
            yield from recorrer(v)


def valor_cmg(reg: dict):
    nums = {}
    for k, v in reg.items():
        f = a_float(v)
        if f is None:
            continue
        kl = norm(k).lower()
        if any(x in kl for x in EXCLUIR) or kl in ("x", "y"):
            continue
        nums[kl] = f
    if not nums:
        return None, None
    for pref in (lambda k: "total" in k,
                 lambda k: "cmg" in k and "cong" not in k and "perd" not in k and "ener" not in k,
                 lambda k: "ener" in k,
                 lambda k: "cmg" in k or "costo" in k or "valor" in k):
        for k, f in nums.items():
            if pref(k):
                return f, k
    if len(nums) == 1:
        return next(iter(nums.items()))[::-1]
    return None, None


def ts_registro(reg: dict):
    fecha_base = None
    for k, v in reg.items():
        if "fecha" in norm(k).lower():
            t = parse_ts(v)
            if t:
                if t.hour or t.minute:
                    return t
                fecha_base = t
    for k, v in reg.items():
        kl = norm(k).lower()
        if "hora" in kl or "interval" in kl or "periodo" in kl:
            t = parse_ts(v, fecha_base)
            if t:
                return t
    return None


def desde_json(capturas):
    hallados = []
    for c in capturas:
        try:
            obj = json.loads(c["texto"])
        except Exception:
            continue
        for reg in recorrer(obj):
            nombre = next((v for v in reg.values()
                           if isinstance(v, str) and BARRA_RE.search(norm(v))), None)
            if not nombre:
                continue
            val, campo = valor_cmg(reg)
            if val is not None:
                hallados.append({"barra": norm(nombre), "cmg": val, "campo": campo,
                                 "ts": ts_registro(reg), "fuente": c["url"]})
    return hallados


def desde_html(textos):
    from bs4 import BeautifulSoup

    hallados = []
    for fuente, html in textos:
        if "ROSA" not in norm(html):
            continue
        sopa = BeautifulSoup(html, "html.parser")
        for tabla in sopa.find_all("table"):
            cab = [norm(th.get_text()) for th in tabla.find_all("th")]
            for tr in tabla.find_all("tr"):
                celdas = [norm(td.get_text()) for td in tr.find_all("td")]
                if not celdas:
                    continue
                nombre = next((c for c in celdas if BARRA_RE.search(c)), None)
                if not nombre:
                    continue
                idx = None
                for pref in ("TOTAL", "CMG", "ENERG"):
                    idx = next((i for i, h in enumerate(cab) if pref in h), None)
                    if idx is not None:
                        break
                val = a_float(celdas[idx]) if idx is not None and idx < len(celdas) else None
                if val is None:
                    nums = [a_float(c) for c in celdas if a_float(c) is not None]
                    val = nums[-1] if nums else None
                if val is not None:
                    hallados.append({"barra": nombre, "cmg": val, "campo": "tabla html",
                                     "ts": None, "fuente": fuente})
    return hallados


def elegir(hallados):
    """Si hay varias barras que calzan, se queda con el nombre más corto."""
    if not hallados:
        return []
    barra = min({h["barra"] for h in hallados}, key=len)
    return [h for h in hallados if h["barra"] == barra]


# --------------------------------------------------------------------------- histórico
def leer_hist():
    if not CSV_PATH.exists():
        return {}
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return {dt.datetime.fromisoformat(r["ts"]): float(r["cmg"]) for r in csv.DictReader(f)}


def guardar_hist(hist, barra):
    DATA.mkdir(exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "barra", "cmg"])
        for t in sorted(hist):
            w.writerow([t.isoformat(), barra, f"{hist[t]:.2f}"])


# --------------------------------------------------------------------------- gráfico
def graficar(hist, barra, hoy):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MultipleLocator

    def serie(dia):
        pts = sorted((t, v) for t, v in hist.items() if t.astimezone(LIMA).date() == dia)
        return ([t.hour + t.minute / 60 for t, _ in pts], [v for _, v in pts])

    xh, yh = serie(hoy)
    xa, ya = serie(hoy - dt.timedelta(days=1))

    fig, ax = plt.subplots(figsize=(7.5, 5.2), dpi=160)
    if xa:
        ax.plot(xa, ya, color="#9aa0a6", lw=1.4, ls="--", label="Ayer")
    ax.plot(xh, yh, color="#1a73e8", lw=2.2, marker="o", ms=3, label="Hoy")
    ax.fill_between(xh, yh, color="#1a73e8", alpha=0.08)

    if yh:
        i_max = max(range(len(yh)), key=yh.__getitem__)
        i_min = min(range(len(yh)), key=yh.__getitem__)
        prom = sum(yh) / len(yh)
        ax.axhline(prom, color="#1a73e8", lw=0.8, ls=":")
        ax.annotate(f"máx {yh[i_max]:.1f}", (xh[i_max], yh[i_max]), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8, color="#c5221f")
        ax.annotate(f"mín {yh[i_min]:.1f}", (xh[i_min], yh[i_min]), textcoords="offset points",
                    xytext=(0, -14), ha="center", fontsize=8, color="#137333")
        ax.annotate(f"{yh[-1]:.1f}", (xh[-1], yh[-1]), textcoords="offset points",
                    xytext=(6, 0), va="center", fontsize=10, weight="bold", color="#1a73e8")
        if ALERTA:
            ax.axhline(ALERTA, color="#c5221f", lw=1, ls="-.", label=f"Alerta {ALERTA:.0f}")

    ax.set_xlim(0, 24)
    ax.xaxis.set_major_locator(MultipleLocator(3))
    ax.xaxis.set_minor_locator(MultipleLocator(1))
    ax.set_xticks(range(0, 25, 3), [f"{h:02d}:00" for h in range(0, 25, 3)], fontsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.set_ylabel("CMg (S/ / MWh)", fontsize=9)
    ax.set_title(f"CMg tiempo real (preliminar) · {barra.title()}\n{hoy:%d/%m/%Y}", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.text(0.99, 0.01, "Fuente: COES – datos preliminares (PR-07)", ha="right",
             fontsize=6, color="#5f6368")
    fig.tight_layout()
    fig.savefig(PNG_PATH)
    plt.close(fig)
    return yh


# --------------------------------------------------------------------------- telegram
def tg(metodo, **kw):
    token = os.environ["TELEGRAM_TOKEN"]
    r = requests.post(f"https://api.telegram.org/bot{token}/{metodo}", timeout=60, **kw)
    if not r.ok:
        print("Telegram:", r.status_code, r.text, file=sys.stderr)
    r.raise_for_status()


def enviar_diagnostico(capturas, controles, html, motivo):
    lineas = [f"MOTIVO: {motivo}", f"Hora Lima: {dt.datetime.now(LIMA):%Y-%m-%d %H:%M}",
              f"Regex barra: {BARRA_RE.pattern}", "", "CONTROLES DE LA PÁGINA:"]
    lineas += [f"  {i} = {v}" for i, v in controles]
    rosas = sorted(set(re.findall(r"[A-Z .]*ROSA[A-Z0-9 .]*", norm(html))))[:30]
    lineas += ["", f"Textos con 'ROSA' en el HTML: {rosas}", "", f"RESPUESTAS XHR ({len(capturas)}):"]
    for c in capturas:
        t = c["texto"] or ""
        lineas += [f"--- {c['status']} {c['url']}", f"    POST: {c['post']}",
                   f"    contiene ROSA: {'ROSA' in norm(t)} | largo: {len(t)}",
                   "    " + t[:1500].replace("\n", " ")]
    DIAG_PATH.write_text("\n".join(lineas), encoding="utf-8")
    with DIAG_PATH.open("rb") as f:
        tg("sendDocument", data={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                 "caption": f"⚠️ CMg Santa Rosa: {motivo}. Reenvía este archivo a Claude."},
           files={"document": f})


# --------------------------------------------------------------------------- main
def main():
    capturas, html, controles = capturar()
    ahora = dt.datetime.now(LIMA)
    t_pag = instante_pagina(controles) or piso_30min(ahora)

    hallados = elegir(desde_json(capturas)
                      or desde_html([(c["url"], c["texto"]) for c in capturas])
                      or desde_html([("DOM renderizado", html)]))
    if not hallados:
        enviar_diagnostico(capturas, controles, html, "no se encontró la barra")
        sys.exit(1)

    barra = hallados[0]["barra"]
    hist = leer_hist()
    for h in hallados:
        hist[piso_30min(h["ts"] or t_pag)] = h["cmg"]
    guardar_hist(hist, barra)

    hoy = ahora.date()
    yh = graficar(hist, barra, hoy)
    ultimo_t = max(t for t in hist if t.astimezone(LIMA).date() == hoy) if yh else t_pag
    ultimo = hist.get(ultimo_t, hallados[-1]["cmg"])
    alerta = bool(ALERTA and ultimo >= ALERTA)

    texto = (f"{'🚨 ' if alerta else ''}CMg {barra.title()}: *{ultimo:.2f}* S/ / MWh "
             f"({ultimo_t:%H:%M})")
    if yh:
        texto += (f"\nProm. día: {sum(yh)/len(yh):.2f} · Máx: {max(yh):.2f} · "
                  f"Mín: {min(yh):.2f} · {len(yh)} intervalos")
    with PNG_PATH.open("rb") as f:
        tg("sendPhoto", data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": texto,
                              "parse_mode": "Markdown",
                              "disable_notification": "false" if alerta else "true"},
           files={"photo": f})

    print(f"OK {barra} {ultimo_t:%Y-%m-%d %H:%M} = {ultimo} (campo: {hallados[-1]['campo']}, "
          f"fuente: {hallados[-1]['fuente']})")
    if FORZAR_DIAG:
        enviar_diagnostico(capturas, controles, html, "diagnóstico solicitado")


if __name__ == "__main__":
    main()
