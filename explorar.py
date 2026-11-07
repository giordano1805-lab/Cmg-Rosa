#!/usr/bin/env python3
"""Explorador (modo=explora): Osinergmin VisorGRT · Mercado Libre de Electricidad (API PublicadorGRTBackEnd).
Guarda en data/explora14/: nodos de esa rama, documentos y un extracto del Excel más reciente."""
import json
import re
from pathlib import Path

import fuentes_coes as fc

OUT = Path("data") / "explora14"
API = "https://www.osinergmin.gob.pe/PublicadorGRTBackEnd"
S = fc.S


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"paginas": {}}
    nodos = docs = []
    for k in ("nodo", "documento"):
        try:
            r = S.get(f"{API}/{k}/all", timeout=120)
            res["paginas"][k] = {"status": r.status_code, "bytes": len(r.content)}
            if r.ok:
                if k == "nodo":
                    nodos = r.json()
                else:
                    docs = r.json()
        except Exception as e:
            res["paginas"][k] = {"status": None, "error": str(e)[:200]}
    if isinstance(nodos, dict):
        nodos = next((v for v in nodos.values() if isinstance(v, list)), [])
    if isinstance(docs, dict):
        docs = next((v for v in docs.values() if isinstance(v, list)), [])
    res["n_nodos"], res["n_docs"] = len(nodos), len(docs)
    res["ejemplo_nodo"] = nodos[:3]
    res["ejemplo_doc"] = docs[:2]
    txt = lambda x: json.dumps(x, ensure_ascii=False)
    ml = [n for n in nodos if re.search(r"MERCADO LIBRE", fc.norm(txt(n)))]
    res["nodos_mercado_libre"] = ml[:40]
    ids = {str(n.get("id_identificador_nodo") or n.get("code") or n.get("id")) for n in ml}
    # hijos (años) de la rama
    hijos = [n for n in nodos if str(n.get("id_identificador_nodo_padre") or n.get("parent") or "") in ids]
    res["hijos"] = hijos[:40]
    ids |= {str(n.get("id_identificador_nodo") or n.get("id")) for n in hijos}
    dml = [d for d in docs if str(d.get("id_identificador_nodo")) in ids]
    res["docs_mercado_libre"] = sorted(dml, key=lambda d: str(d.get("fe_publicacion") or d.get("id_documento")), reverse=True)[:60]
    ruta = {str(n.get("id_identificador_nodo")): n.get("de_ruta_de_repositorio") for n in nodos}
    xls = [d for d in res["docs_mercado_libre"] if re.search(r"\.xls", str(d.get("de_nombre_fisico")), re.I)]
    if xls:
        d = xls[0]
        url = (ruta.get(str(d.get("id_identificador_nodo"))) or "") + d["de_nombre_fisico"]
        res["descarga"] = {"url": url}
        try:
            b = S.get(url, timeout=180).content
            res["descarga"]["bytes"] = len(b)
            hojas = fc.libro(b)
            res["descarga"]["hojas"] = {h: len(f) for h, f in hojas.items()}
            fc.volcar_hojas(hojas, OUT / "xls", nombres=list(hojas)[:30], filas=70, cols=30)
        except Exception as e:
            res["descarga"]["error"] = str(e)[:300]
    (OUT / "resumen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res
