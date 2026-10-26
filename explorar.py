#!/usr/bin/env python3
"""
Explorador de fuentes del portal COES (se ejecuta una sola vez con modo=explora).

Para cada página candidata guarda en data/explora/:
  - texto visible, formularios, scripts y llamadas AJAX encontradas en el HTML y en los .js
  - pruebas de endpoints conocidos o deducidos
El resultado queda en el repositorio para analizarlo y diseñar el reporte.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

LIMA = ZoneInfo("America/Lima")
RAIZ = "https://www.coes.org.pe"
OUT = Path("data") / "explora"

PAGINAS = {
    "eventos_relevantes": "/Portal/Eventos/Relevantes",
    "mant_prog_diario": "/Portal/Operacion/ProgManten/ProgDiario",
    "mant_actualizacion_pd": "/Portal/Operacion/ProgManten/ActualizacionPD",
    "mant_prog_semanal": "/Portal/Operacion/ProgManten/ProgSemanal",
    "indisponibilidad": "/Portal/PostOperacion/Reportes/ReporteIndisponibilidad",
    "ieod": "/Portal/PostOperacion/Reportes/Ieod",
    "idcos": "/Portal/PostOperacion/Reportes/Idcos",
    "prog_operacion_diario": "/Portal/Operacion/ProgOperacion/ProgramaDiario",
    "max_demanda": "/Portal/portalinformacion/demanda?indicador=maxima",
    "pi_generacion": "/Portal/portalinformacion/generacion",
    "pi_demanda": "/Portal/portalinformacion/demanda",
    "pi_hidrologia": "/Portal/portalinformacion/hidrologia",
    "pi_index": "/Portal/portalinformacion/index",
    "hidrologia_estudios": "/Portal/Operacion/Estudios/Hidrologia",
}

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"})

PAT_AJAX = re.compile(
    r"""(?:url\s*:\s*|\.(?:post|get|load|getJSON)\s*\(\s*|controlador\s*\+\s*|href\s*=\s*)['"]([^'"]{3,200})['"]""",
    re.I)
PAT_CONTROLADOR = re.compile(r"""(?:var|let|const)\s+(\w*(?:controlador|url|ruta)\w*)\s*=\s*['"]([^'"]+)['"]""", re.I)
PAT_DATA = re.compile(r"data\s*:\s*\{([^}]{0,400})\}", re.S)


def texto_visible(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", t).strip()


def formularios(html):
    out = []
    for m in re.finditer(r"(?is)<(input|select|textarea)\b([^>]*)>", html):
        attrs = dict(re.findall(r'(\w[\w-]*)\s*=\s*"([^"]*)"', m.group(2)))
        if attrs.get("type") in ("hidden", "text", "date", None, "checkbox", "radio") or m.group(1) != "input":
            out.append({k: attrs.get(k) for k in ("id", "name", "type", "value") if attrs.get(k)})
    for m in re.finditer(r'(?is)<select\b[^>]*id="([^"]+)"[^>]*>(.*?)</select>', html):
        ops = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', m.group(2))[:40]
        out.append({"select": m.group(1), "opciones": ops})
    return out


def analizar_js(codigo):
    hall = {"ajax": sorted(set(PAT_AJAX.findall(codigo))),
            "variables": sorted(set(f"{a} = {b}" for a, b in PAT_CONTROLADOR.findall(codigo))),
            "data": [re.sub(r"\s+", " ", d)[:300] for d in PAT_DATA.findall(codigo)][:40]}
    return hall


def explorar_pagina(nombre, ruta):
    url = urljoin(RAIZ, ruta)
    info = {"url": url}
    try:
        r = S.get(url, timeout=60)
        info["status"] = r.status_code
        html = r.text
    except Exception as e:
        info["error"] = str(e)
        return info
    info["texto"] = texto_visible(html)[:4000]
    info["formularios"] = formularios(html)
    inline = "\n".join(re.findall(r"(?is)<script[^>]*>(.*?)</script>", html))
    info["js_inline"] = analizar_js(inline)
    srcs = re.findall(r'(?i)<script[^>]+src="([^"]+)"', html)
    info["scripts"] = srcs
    info["js_externos"] = {}
    for src in srcs:
        if any(x in src.lower() for x in ("jquery", "bootstrap", "google", "highcharts", "moment", "datatables",
                                           "select2", "modernizr", "gtag", "analytics")):
            continue
        u = urljoin(url, src)
        if "coes.org.pe" not in u:
            continue
        try:
            codigo = S.get(u, timeout=60).text
            info["js_externos"][u] = analizar_js(codigo)
            (OUT / "js").mkdir(parents=True, exist_ok=True)
            (OUT / "js" / (re.sub(r"[^\w.]+", "_", u.split("coes.org.pe")[-1])[:120])).write_text(
                codigo[:300_000], encoding="utf-8")
        except Exception as e:
            info["js_externos"][u] = {"error": str(e)}
    (OUT / "html").mkdir(parents=True, exist_ok=True)
    (OUT / "html" / f"{nombre}.html").write_text(html[:600_000], encoding="utf-8")
    return info


def probar_endpoints():
    """Pruebas de endpoints AJAX deducidos de los .js (se completan en una segunda pasada)."""
    hoy = dt.datetime.now(LIMA).date()
    ayer = hoy - dt.timedelta(days=1)
    pruebas = {
        "gen_indicador0_ayer": ("POST", "/Portal/portalinformacion/generacion",
                                {"fechaInicial": ayer.strftime("%d/%m/%Y"), "fechaFinal": hoy.strftime("%d/%m/%Y"),
                                 "indicador": 0}),
        "gen_indicador0_hoy": ("POST", "/Portal/portalinformacion/generacion",
                               {"fechaInicial": hoy.strftime("%d/%m/%Y"),
                                "fechaFinal": (hoy + dt.timedelta(days=1)).strftime("%d/%m/%Y"), "indicador": 0}),
        "demanda_hoy": ("POST", "/Portal/portalinformacion/demanda",
                        {"fechaInicial": ayer.strftime("%d/%m/%Y"),
                         "fechaFinal": (hoy + dt.timedelta(days=1)).strftime("%d/%m/%Y"), "indicador": 0}),
    }
    out = {}
    for k, (met, ruta, data) in pruebas.items():
        try:
            r = S.request(met, urljoin(RAIZ, ruta), data=data, timeout=60,
                          headers={"X-Requested-With": "XMLHttpRequest"})
            cuerpo = r.text
            resumen = cuerpo[:1500]
            try:
                j = r.json()
                resumen = {"claves": list(j.keys()) if isinstance(j, dict) else type(j).__name__,
                           "muestra": json.dumps(j, ensure_ascii=False)[:2500]}
            except Exception:
                pass
            out[k] = {"status": r.status_code, "largo": len(cuerpo), "resumen": resumen}
        except Exception as e:
            out[k] = {"error": str(e)}
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    resultado = {"fecha": dt.datetime.now(LIMA).isoformat(), "paginas": {}}
    for nombre, ruta in PAGINAS.items():
        print("explorando", nombre, file=sys.stderr)
        resultado["paginas"][nombre] = explorar_pagina(nombre, ruta)
    resultado["pruebas"] = probar_endpoints()
    (OUT / "resultado.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print("OK exploración guardada en", OUT)
    return resultado


if __name__ == "__main__":
    main()
