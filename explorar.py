#!/usr/bin/env python3
"""Explorador (modo=explora): publicaciones de Osinergmin GRT · Informes mensuales · Mercado Libre de Electricidad.
Guarda HTML, scripts y respuestas en data/explora11/ para ubicar cómo se listan y descargan los archivos."""
import json
import re
from pathlib import Path
from urllib.parse import urljoin, quote

import fuentes_coes as fc

OUT = Path("data") / "explora12"
S = fc.S
CARPETA = "Publicacionesgrt/INFORMES MENSUALES/Mercado Libre de Electricidad/2026"
PAGINAS = ["https://www.osinergmin.gob.pe/VisorGRT/"]


def guardar(nombre, texto):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (re.sub(r"[^\w.]+", "_", nombre)[-90:])).write_text(texto, encoding="utf-8", errors="ignore")


def main():
    res = {"paginas": {}, "scripts": {}, "enlaces": [], "pruebas": {}}
    for u in PAGINAS:
        try:
            r = S.get(u, timeout=60)
            res["paginas"][u] = {"status": r.status_code, "bytes": len(r.content), "url_final": r.url}
            t = r.text
            guardar("pag_" + u, t)
            for m in re.findall(r"""(?:href|src)=["']([^"']+)["']""", t):
                if re.search(r"merc|libre|publicacion|\.xls|\.pdf|grt", m, re.I):
                    res["enlaces"].append(urljoin(r.url, m))
            for sc in re.findall(r"""<script[^>]+src=["']([^"']+)["']""", t, re.I):
                su = urljoin(r.url, sc)
                if su in res["scripts"] or re.search(r"jquery|bootstrap|google|analytics", su, re.I):
                    continue
                try:
                    js = S.get(su, timeout=60)
                    res["scripts"][su] = {"status": js.status_code, "bytes": len(js.content)}
                    guardar("js_" + su, js.text)
                except Exception as e:
                    res["scripts"][su] = {"error": str(e)[:150]}
        except Exception as e:
            res["paginas"][u] = {"status": None, "error": str(e)[:200]}
    # endpoints que aparecen en el HTML/JS del visor
    eps = set()
    for f in OUT.glob("*"):
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.findall(r"""["'`](/?(?:api|VisorGRT|Services?|Handlers?|ws)[^"'`\s]{2,120})["'`]""", t, re.I):
            eps.add(m)
        for m in re.findall(r"""["'`](https?://[^"'`\s]{5,160})["'`]""", t):
            if "osinergmin" in m:
                eps.add(m)
    res["endpoints"] = sorted(eps)[:200]
    # pruebas de rutas directas de archivos (patrones habituales de publicacionesgrt)
    for u in [f"https://www2.osinergmin.gob.pe/publicacionesgrt/{quote(CARPETA)}/",
              "https://www2.osinergmin.gob.pe/publicacionesgrt/xls/BolMerLibElectricidad/",
              "https://www2.osinergmin.gob.pe/publicacionesgrt/pdf/BolMerLibElectricidad/MERCLIB2000.pdf"]:
        try:
            r = S.get(u, timeout=60)
            res["pruebas"][u] = {"status": r.status_code, "bytes": len(r.content), "tipo": r.headers.get("content-type")}
            if r.ok and "html" in (r.headers.get("content-type") or ""):
                guardar("prueba_" + u, r.text)
        except Exception as e:
            res["pruebas"][u] = {"error": str(e)[:200]}
    res["enlaces"] = list(dict.fromkeys(res["enlaces"]))[:300]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "resumen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
