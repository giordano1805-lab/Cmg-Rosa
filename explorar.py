#!/usr/bin/env python3
"""
Explorador de fuentes COES · segunda pasada (modo=explora).

Guarda en data/explora2/ la estructura real de:
  - Repositorio de archivos del portal (mantenimientos, indisponibilidad, IEOD, programa diario, hidrología)
    vía /Portal/browser/vistadatos: lista carpetas, baja a la más reciente y analiza los últimos archivos
  - Eventos relevantes vía /Portal/eventos/relevantes/lista y /detalle
  - Generación (SCADA) y demanda del Portal de Información, pidiendo ayer y hoy por separado
"""
import datetime as dt
import html as htmlmod
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

LIMA = ZoneInfo("America/Lima")
RAIZ = "https://www.coes.org.pe/Portal/"
OUT = Path("data") / "explora2"

CARPETAS = {
    "mant_diario": ("Operación/Programa de Mantenimiento/Programa Diario/", "Programa de Mantenimiento Diario"),
    "mant_actualizacion": ("Operación/Programa de Mantenimiento/Actualización del Programa Diario/",
                           "Actualización del Programa Diario"),
    "mant_semanal": ("Operación/Programa de Mantenimiento/Programa Semanal/", "Programa semanal"),
    "indisponibilidad": ("Post Operación/Reportes/Reporte de Indisponibilidad/", "Reporte de Indisponibilidad"),
    "ieod": ("Post Operación/Reportes/IEOD/", "IEOD"),
    "prog_operacion": ("Operación/Programa de Operación/Programa Diario/", "Programa de Operación Diario"),
    "hidrologia": ("Operación/Estudios/Hidrologia/", "Hidrología"),
}

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                  "X-Requested-With": "XMLHttpRequest"})


def instalar():
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl", "xlrd", "pypdf"], check=False)


def limpio(t):
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"(?s)<[^>]+>", " ", t))).strip()


# --------------------------------------------------------------------------- repositorio de archivos
def listar(base, url, nombre):
    r = S.post(RAIZ + "browser/vistadatos", data={"baseDirectory": base, "url": url, "indicador": "S",
                                                  "initialLink": nombre, "orderFolder": "D"}, timeout=90)
    h = r.text
    carpetas, archivos = [], []
    for m in re.finditer(r"openDirectory\('([^']+)'\)", h):
        if m.group(1) not in carpetas and m.group(1) not in ("Empty",):
            carpetas.append(htmlmod.unescape(m.group(1)))
    for m in re.finditer(r'class="[^"]*selector-file-contextual[^"]*"[^>]*id="([^"]+)"', h):
        archivos.append(htmlmod.unescape(m.group(1)))
    for m in re.finditer(r'id="([^"]+)"[^>]*class="[^"]*selector-file-contextual', h):
        archivos.append(htmlmod.unescape(m.group(1)))
    for m in re.finditer(r"(?:download|descargar\w*)\(\s*'([^']+\.(?:xlsx?|xlsm|pdf|zip|csv|txt|docx?))'", h, re.I):
        archivos.append(htmlmod.unescape(m.group(1)))
    archivos = list(dict.fromkeys(archivos))
    filas = [limpio(f)[:200] for f in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", h)][:60]
    return {"status": r.status_code, "carpetas": carpetas[:80], "archivos": archivos[:80], "filas": filas,
            "html": h[:20000]}


def analizar_archivo(ruta):
    r = S.get(RAIZ + "browser/download?url=" + quote(ruta, safe="/"), timeout=180)
    b = r.content
    info = {"ruta": ruta, "status": r.status_code, "bytes": len(b),
            "content_type": r.headers.get("content-type", "")}
    ext = ruta.lower().rsplit(".", 1)[-1]
    try:
        if ext in ("xlsx", "xlsm") or b[:2] == b"PK" and ext not in ("zip", "docx"):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
            info["hojas"] = {}
            for ws in wb.worksheets[:40]:
                filas = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 40:
                        break
                    vals = [str(v)[:40] for v in row[:25] if v is not None]
                    if vals:
                        filas.append(vals)
                info["hojas"][ws.title] = {"dim": ws.max_row and f"{ws.max_row}x{ws.max_column}", "filas": filas}
        elif ext == "xls":
            import xlrd
            wb = xlrd.open_workbook(file_contents=b)
            info["hojas"] = {}
            for sh in wb.sheets()[:40]:
                filas = []
                for i in range(min(sh.nrows, 40)):
                    vals = [str(v)[:40] for v in sh.row_values(i)[:25] if str(v).strip()]
                    if vals:
                        filas.append(vals)
                info["hojas"][sh.name] = {"dim": f"{sh.nrows}x{sh.ncols}", "filas": filas}
        elif ext == "pdf":
            from pypdf import PdfReader
            pdf = PdfReader(io.BytesIO(b))
            info["paginas"] = len(pdf.pages)
            info["texto"] = "\n".join((p.extract_text() or "") for p in pdf.pages[:4])[:6000]
        elif ext == "zip":
            z = zipfile.ZipFile(io.BytesIO(b))
            info["contenido"] = z.namelist()[:100]
        else:
            info["inicio"] = b[:1500].decode("latin-1", "replace")
    except Exception as e:
        info["error_analisis"] = repr(e)
    return info


def explorar_carpeta(clave, base, nombre):
    res = {"niveles": []}
    url = base
    for nivel in range(4):
        lst = listar(base, url, nombre)
        res["niveles"].append({"url": url, **{k: v for k, v in lst.items() if k != "html"}})
        (OUT / "listados").mkdir(parents=True, exist_ok=True)
        (OUT / "listados" / f"{clave}_{nivel}.html").write_text(lst["html"], encoding="utf-8")
        if lst["archivos"]:
            res["archivos_analizados"] = [analizar_archivo(a) for a in lst["archivos"][:2]]
            break
        if not lst["carpetas"]:
            break
        hijas = [c for c in lst["carpetas"] if c.startswith(url) and c != url] or lst["carpetas"]
        # carpeta más reciente: mayor por nombre (años/meses/días suelen ordenarse así)
        url = sorted(hijas, key=lambda c: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", c)])[-1]
    return res


# --------------------------------------------------------------------------- eventos
def explorar_eventos():
    hoy = dt.datetime.now(LIMA).date()
    ayer = hoy - dt.timedelta(days=1)
    datos = {"FechaInicio": ayer.strftime("%d/%m/%Y"), "FechaFin": hoy.strftime("%d/%m/%Y"),
             "IdTipoEvento": 0, "Version": "N", "Turno": "", "IdTipoEmpresa": 0, "IdEmpresa": 0,
             "IdFamilia": 0, "IndInterrupcion": -1, "NroPagina": 1}
    r = S.post(RAIZ + "eventos/relevantes/lista", data=datos, timeout=90)
    h = r.text
    (OUT / "eventos_lista.html").write_text(h[:200000], encoding="utf-8")
    cab = [limpio(c) for c in re.findall(r"(?is)<th[^>]*>(.*?)</th>", h)]
    filas = [[limpio(c)[:160] for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", f)]
             for f in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", h)]
    ids = re.findall(r"verEvento\((\d+)\)", h)
    det = {}
    if ids:
        d = S.post(RAIZ + "eventos/relevantes/detalle", data={"idEvento": ids[0]}, timeout=90).text
        (OUT / "evento_detalle.html").write_text(d[:100000], encoding="utf-8")
        det = {"id": ids[0], "texto": limpio(d)[:3000]}
    return {"status": r.status_code, "cabecera": cab, "n_filas": len(filas), "filas": filas[:25],
            "ids": ids[:30], "detalle": det}


# --------------------------------------------------------------------------- generación y demanda
def explorar_portal_info():
    hoy = dt.datetime.now(LIMA).date()
    out = {}
    for etiqueta, d0, d1 in (("ayer", hoy - dt.timedelta(days=1), hoy - dt.timedelta(days=1)),
                             ("hoy", hoy, hoy), ("ayer_hoy", hoy - dt.timedelta(days=1), hoy)):
        try:
            j = S.post(RAIZ + "portalinformacion/generacion",
                       data={"fechaInicial": d0.strftime("%d/%m/%Y"), "fechaFinal": d1.strftime("%d/%m/%Y"),
                             "indicador": 0}, timeout=120).json()
            ser = j["GraficoTipoCombustible"]["Series"] or []
            emp = j.get("ListadoPorEmpresa") or []
            out[f"gen_{etiqueta}"] = {
                "series": {s["Name"]: {"n": len(s["Data"]), "primero": s["Data"][0]["Nombre"] if s["Data"] else None,
                                       "ultimo": s["Data"][-1]["Nombre"] if s["Data"] else None}
                           for s in ser},
                "n_empresas": len(emp),
                "empresa_ejemplo": {k: v for k, v in (emp[0] if emp else {}).items()
                                    if v not in (None, 0, [], "") or k.startswith("Lista")},
                "central_ejemplo": (emp[0].get("ListaCentral") or [None])[0] if emp else None,
                "grafico_empresa_keys": list((j.get("GraficoPorEmpresa") or {}).keys())
                if isinstance(j.get("GraficoPorEmpresa"), dict) else str(type(j.get("GraficoPorEmpresa"))),
            }
        except Exception as e:
            out[f"gen_{etiqueta}"] = {"error": repr(e)}
    try:
        j = S.post(RAIZ + "portalinformacion/demanda",
                   data={"fechaInicial": (hoy - dt.timedelta(days=1)).strftime("%d/%m/%Y"),
                         "fechaFinal": hoy.strftime("%d/%m/%Y")}, timeout=120).json()
        out["demanda"] = {"claves": list(j.keys()),
                          "series": {s["Name"]: {"n": len(s["Data"]),
                                                 "ultimo": s["Data"][-1] if s["Data"] else None}
                                     for s in (j.get("Chart") or {}).get("Series", [])},
                          "LastDate": j.get("LastDate"), "LastTime": j.get("LastTime"),
                          "LastValue": j.get("LastValue")}
    except Exception as e:
        out["demanda"] = {"error": repr(e)}
    return out


def main():
    instalar()
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"fecha": dt.datetime.now(LIMA).isoformat(), "carpetas": {}}
    for clave, (base, nombre) in CARPETAS.items():
        print("carpeta", clave, file=sys.stderr)
        try:
            res["carpetas"][clave] = explorar_carpeta(clave, base, nombre)
        except Exception as e:
            res["carpetas"][clave] = {"error": repr(e)}
    try:
        res["eventos"] = explorar_eventos()
    except Exception as e:
        res["eventos"] = {"error": repr(e)}
    res["portal_info"] = explorar_portal_info()
    (OUT / "resultado.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str),
                                        encoding="utf-8")
    ok = sum(1 for c in res["carpetas"].values() if c.get("archivos_analizados"))
    print("OK exploración 2 guardada")
    return {"paginas": {k: {"status": 200 if v.get("archivos_analizados") else 0}
                        for k, v in res["carpetas"].items()}}


if __name__ == "__main__":
    main()
