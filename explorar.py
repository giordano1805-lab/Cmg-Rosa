#!/usr/bin/env python3
"""Explorador (modo=explora): hojas y cabeceras de los Excel de Osinergmin (Mercado Libre) de may–jul 2025."""
import json
from pathlib import Path
from urllib.parse import quote

import fuentes_coes as fc

OUT = Path("data") / "explora16"
BASE = "https://www2.osinergmin.gob.pe/publicacionesgrt/pdf/MerLibElectricidad/"
ARCH = ["Año 25-Nro 07-Julio 2025.xlsx", "Año 25-Nro 08-Agosto 2025.xlsx", "Año 25-Nro 09-Setiembre 2025.xlsx"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"paginas": {}}
    for a in ARCH:
        info = {}
        for u in (BASE + a, BASE + quote(a)):
            try:
                r = fc.S.get(u, timeout=180)
                info[u] = {"status": r.status_code, "bytes": len(r.content), "tipo": r.headers.get("content-type")}
                if r.ok and len(r.content) > 1000:
                    hojas = fc.libro(r.content)
                    info["hojas"] = {h: len(f) for h, f in hojas.items()}
                    for h, f in hojas.items():
                        if "FACTURA" in fc.norm(h) or "CLIENTE" in fc.norm(h):
                            info.setdefault("cabeceras", {})[h] = [[fc.texto(x) for x in fila[:30]] for fila in f[:4]]
                    break
            except Exception as e:
                info[u] = {"error": str(e)[:200]}
        res["paginas"][a] = info
    (OUT / "resumen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res
