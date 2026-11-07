#!/usr/bin/env python3
"""Explorador (modo=explora): Osinergmin VisorGRT · Mercado Libre de Electricidad (API PublicadorGRTBackEnd).
Guarda en data/explora14/: nodos de esa rama, documentos y un extracto del Excel más reciente."""
import json
import re
from pathlib import Path

import fuentes_coes as fc

OUT = Path("data") / "explora15"
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
    base = [n for n in nodos if fc.norm(n.get("de_descripcion") or "") == "MERCADO LIBRE DE ELECTRICIDAD"]
    res["bases"] = [(n["co_nodo"], n["id_identificador_nodo"]) for n in base]
    cods = [n["co_nodo"] for n in base]
    rama = [n for n in nodos if any(str(n.get("co_nodo") or "").startswith(c + ".") for c in cods)]
    res["rama"] = [(n["co_nodo"], n["id_identificador_nodo"], n["de_descripcion"], n.get("de_ruta_de_repositorio")) for n in rama]
    ids = {n["id_identificador_nodo"] for n in rama}
    ruta = {n["id_identificador_nodo"]: n.get("de_ruta_de_repositorio") or "" for n in nodos}
    desc = {n["id_identificador_nodo"]: n.get("de_descripcion") for n in nodos}
    dml = [d for d in docs if d.get("id_identificador_nodo") in ids and d.get("in_estado") == "A"]
    res["docs"] = [{"anio": desc.get(d["id_identificador_nodo"]), "nombre": d.get("de_nombre_logico"),
                    "desc": d.get("de_descripcion_documento"), "fisico": d.get("de_nombre_fisico"), "orden": d.get("nu_orden"),
                    "url": ruta.get(d["id_identificador_nodo"], "") + str(d.get("de_nombre_fisico"))} for d in dml]
    x26 = [d for d in res["docs"] if str(d["anio"]) == "2026" and re.search(r"\.xls", str(d["fisico"]), re.I)]
    x26.sort(key=lambda d: str(d["nombre"]))
    if x26:
        d = x26[-1]
        res["descarga"] = {"url": d["url"], "doc": d}
        try:
            b = S.get(d["url"], timeout=180).content
            res["descarga"]["bytes"] = len(b)
            hojas = fc.libro(b)
            res["descarga"]["hojas"] = {h: len(f) for h, f in hojas.items()}
            fc.volcar_hojas(hojas, OUT / "xls", nombres=list(hojas)[:80], filas=60, cols=30)
        except Exception as e:
            res["descarga"]["error"] = str(e)[:300]
    (OUT / "resumen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res
