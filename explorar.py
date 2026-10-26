#!/usr/bin/env python3
"""
Explorador de fuentes COES · quinta pasada (modo=explora).

1) Demanda: ¿el Portal de Información devuelve rangos de varios días? ¿hay histórico 2025?
2) Hidrología semanal (volúmenes de embalses estacionales por cuenca): Programa Semanal de Operación
   y Evaluación Semanal.
3) IEOD: hojas que permiten identificar el combustible de cada unidad (HOP, ENERGÍA_PRIMARIA, RESERVA_FRÍA).
Resultado en data/explora5/.
"""
import csv
import datetime as dt
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import fuentes_coes as fc

LIMA = ZoneInfo("America/Lima")
OUT = Path("data") / "explora5"
res = {}


def volcar(b, carpeta, max_filas=80, max_cols=45, hojas=None):
    destino = OUT / carpeta
    destino.mkdir(parents=True, exist_ok=True)
    try:
        lib = fc.libro(b)
    except Exception as e:
        return {"error": repr(e)}
    info = {}
    for nombre, filas in lib.items():
        info[nombre] = len(filas)
        if hojas and not any(h in fc.norm(nombre) for h in hojas):
            continue
        with (destino / (re.sub(r"[^\w]+", "_", nombre)[:60] + ".csv")).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for row in filas[:max_filas]:
                w.writerow(["" if v is None else str(v)[:80] for v in list(row)[:max_cols]])
    return info


def mas_reciente(rutas):
    return max(rutas, key=lambda r: [int(x) for x in re.findall(r"\d+", r.rstrip("/").rsplit("/", 1)[-1])] or [0])


def bajar_carpeta(base, etiqueta, niveles=5, max_archivos=6):
    url, rastro = base, []
    for _ in range(niveles):
        items = fc.listar(url)
        carpetas = [i for i in items if i.endswith("/")]
        archivos = [i for i in items if not i.endswith("/")]
        rastro.append({"url": url, "carpetas": carpetas[:30], "archivos": archivos[:40]})
        if archivos or not carpetas:
            break
        url = mas_reciente(carpetas)
    out = {"rastro": rastro, "volcados": {}}
    archivos = rastro[-1]["archivos"]
    elegidos = [a for a in archivos if re.search(r"hidr|embal|volum|lagun|caudal", a, re.I)] or archivos
    for a in elegidos[:max_archivos]:
        if not a.lower().endswith((".xlsx", ".xls", ".xlsm", ".zip")):
            continue
        b = fc.bajar(a)
        if not b:
            continue
        nombre = re.sub(r"[^\w]+", "_", a.rsplit("/", 1)[-1])[:50]
        if a.lower().endswith(".zip"):
            z = zipfile.ZipFile(io.BytesIO(b))
            out["volcados"][nombre] = {"zip": z.namelist()[:80]}
            for n in z.namelist():
                if re.search(r"hidr|embal|volum|lagun", n, re.I) and n.lower().endswith((".xlsx", ".xls", ".xlsm")):
                    out["volcados"][nombre + "/" + n] = volcar(z.read(n), f"{etiqueta}/{nombre}_{re.sub(r'[^\w]+', '_', n)[:40]}")
        else:
            out["volcados"][nombre] = volcar(b, f"{etiqueta}/{nombre}")
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # 1) demanda
    for etiqueta, d0, d1 in (("rango_mes_2025", dt.date(2025, 9, 1), dt.date(2025, 9, 30)),
                             ("dia_2025", dt.date(2025, 10, 25), dt.date(2025, 10, 25)),
                             ("rango_semana_2026", dt.date(2026, 10, 18), dt.date(2026, 10, 24))):
        try:
            j = fc.S.post(fc.RAIZ + "portalinformacion/demanda",
                          data={"fechaInicial": d0.strftime("%d/%m/%Y"), "fechaFinal": d1.strftime("%d/%m/%Y")},
                          timeout=180).json()
            series = {s["Name"]: {"n": len(s["Data"]), "primero": s["Data"][0]["Nombre"] if s["Data"] else None,
                                  "ultimo": s["Data"][-1]["Nombre"] if s["Data"] else None}
                      for s in (j.get("Chart") or {}).get("Series", [])}
            res["demanda_" + etiqueta] = {"series": series, "claves": list(j.keys()),
                                          "Data": str(j.get("Data"))[:1500]}
        except Exception as e:
            res["demanda_" + etiqueta] = {"error": repr(e)}
    # 2) hidrología semanal
    import html as h
    for etiqueta, pagina in (("prog_semanal_op", "Operacion/ProgOperacion/ProgSemanalOp"),
                             ("eval_semanal", "PostOperacion/Informes/EvaluacionSemanal"),
                             ("eval_mensual", "PostOperacion/Informes/EvaluacionMensual"),
                             ("prog_mediano", "Operacion/ProgOperacion/ProgMedianoPO")):
        try:
            t = fc.S.get(fc.RAIZ + pagina, timeout=90).text
            m = re.search(r'id="hfBaseDirectory"[^>]*value="([^"]+)"', t)
            base = h.unescape(m.group(1)) if m else ""
            res[etiqueta] = {"base": base, **bajar_carpeta(base, etiqueta)} if base else {"error": "sin base"}
        except Exception as e:
            res[etiqueta] = {"error": repr(e)}
    # 3) IEOD: combustible por unidad
    try:
        d, hojas = fc.descargar_ieod(dt.datetime.now(LIMA).date() - dt.timedelta(days=1))
        destino = OUT / "ieod"
        destino.mkdir(parents=True, exist_ok=True)
        for nombre in ("HOP", "ENERGÍA_PRIMARIA", "RESERVA_FRÍA", "EVO_PRO_ENE", "DESPACHO_EJECUTADO"):
            filas = hojas.get(nombre) or []
            with (destino / (re.sub(r"[^\w]+", "_", nombre) + ".csv")).open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                for row in filas[:300]:
                    w.writerow(["" if v is None else str(v)[:80] for v in list(row)[:240]])
        res["ieod"] = {"dia": str(d)}
    except Exception as e:
        res["ieod"] = {"error": repr(e)}
    # 4) IEOD histórico 2025: ¿existe y trae TIPO_RECURSO (hidro de pasada)?
    try:
        hoy = dt.datetime.now(LIMA).date()
        d25 = hoy.replace(year=hoy.year - 1) - dt.timedelta(days=1)
        d, hojas = fc.descargar_ieod(d25, dias_atras=3)
        filas = hojas.get("TIPO_RECURSO") or []
        res["ieod_2025"] = {"dia": str(d), "hojas": list(hojas)[:60],
                            "tipo_recurso": [[str(v)[:30] for v in list(f)[:16]] for f in filas[:10]]}
    except Exception as e:
        res["ieod_2025"] = {"error": repr(e)}
    (OUT / "resultado.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("OK exploración 5")
    return {"paginas": {k: {"status": 0 if isinstance(v, dict) and "error" in v else 200} for k, v in res.items()}}


if __name__ == "__main__":
    main()
