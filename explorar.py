#!/usr/bin/env python3
"""
Explorador de fuentes COES · cuarta pasada (modo=explora).

Baja los archivos clave ya identificados y vuelca a CSV las hojas que usará el reporte,
para diseñar el lector definitivo. Resultado en data/explora4/.
"""
import csv
import datetime as dt
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
OUT = Path("data") / "explora4"
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SETIEMBRE",
         "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

HOJAS_IEOD = ["EVENTOS", "MANTENIMIENTO EJECUTADOS", "INDISP", "PRINCIP_VOLÚMENES", "PRINCIP_CAUDALES",
              "RESTRIC_OPE", "DEMANDA_AREAS", "G_AREAS", "DISPONIBILIDAD_GAS", "TIPO_RECURSO",
              "DESCARGA_LAGUNAS", "VERTIMIENTO_EMBALSES", "INGRESO OC"]

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                  "X-Requested-With": "XMLHttpRequest"})
log = {}


def instalar():
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl", "xlrd"], check=False)


def bajar(ruta):
    r = S.get(RAIZ + "browser/download?url=" + quote(ruta, safe="/"), timeout=180)
    log[ruta] = {"status": r.status_code, "bytes": len(r.content)}
    return r.content if r.ok and len(r.content) > 500 else None


def listar(ruta):
    import html as h
    r = S.post(RAIZ + "browser/vistadatos", data={"baseDirectory": ruta, "url": ruta, "indicador": "S",
                                                  "initialLink": "x", "orderFolder": "D"}, timeout=90)
    return [h.unescape(p) for p, t, e in re.findall(r"openBlob\('([^']+)',\s*'([DF])',\s*'([^']*)'\)", r.text)]


def volcar_libro(b, prefijo, hojas=None, max_filas=400):
    """Guarda cada hoja (o las indicadas) como CSV."""
    destino = OUT / prefijo
    destino.mkdir(parents=True, exist_ok=True)
    nombres = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
        for ws in wb.worksheets:
            nombres.append(ws.title)
            if hojas and ws.title.strip() not in hojas:
                continue
            with (destino / (re.sub(r"[^\w]+", "_", ws.title) + ".csv")).open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= max_filas:
                        break
                    w.writerow(["" if v is None else str(v)[:120] for v in row[:60]])
    except Exception:
        import xlrd
        wb = xlrd.open_workbook(file_contents=b)
        for sh in wb.sheets():
            nombres.append(sh.name)
            if hojas and sh.name.strip() not in hojas:
                continue
            with (destino / (re.sub(r"[^\w]+", "_", sh.name) + ".csv")).open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                for i in range(min(sh.nrows, max_filas)):
                    w.writerow([str(v)[:120] for v in sh.row_values(i)[:60]])
    return nombres


def main():
    instalar()
    OUT.mkdir(parents=True, exist_ok=True)
    hoy = dt.datetime.now(LIMA).date()
    res = {"fecha": dt.datetime.now(LIMA).isoformat()}

    # 1) IEOD Anexo A del último día publicado (ayer o antes)
    for atras in range(1, 4):
        d = hoy - dt.timedelta(days=atras)
        carpeta = f"Post Operación/Reportes/IEOD/{d.year}/{d.month:02d}_{MESES[d.month - 1].capitalize()}/{d.day:02d}/"
        b = bajar(carpeta + f"AnexoA_{d:%d%m}.xlsx")
        if b:
            res["ieod"] = {"dia": str(d), "hojas": volcar_libro(b, "ieod", HOJAS_IEOD)}
            break
    # 2) Programa diario de intervenciones de hoy: Anexo 1 (zip)
    mes = f"{hoy.month:02d}_{MESES[hoy.month - 1]}"
    base_int = f"Operación/Programa de Mantenimiento/Programa Diario/{hoy.year}/{mes}/Día {hoy.day:02d}/"
    archivos = listar(base_int) or listar(base_int.replace(f"Día {hoy.day:02d}", f"Día {hoy.day}"))
    res["intervenciones_archivos"] = archivos
    for a in archivos:
        if "Anexo1" in a and a.lower().endswith(".zip"):
            b = bajar(a)
            if b:
                z = zipfile.ZipFile(io.BytesIO(b))
                res["intervenciones_zip"] = z.namelist()
                for n in z.namelist():
                    if n.lower().endswith((".xlsx", ".xls", ".xlsm")):
                        res.setdefault("intervenciones_hojas", {})[n] = volcar_libro(
                            z.read(n), "intervenciones/" + re.sub(r"[^\w]+", "_", n)[:40], None, 300)
    # 3) Programa diario de operación de hoy: Anexo 2 hidrología y Anexo 5 restricciones
    base_po = f"Operación/Programa de Operación/Programa Diario/{hoy.year}/{mes}/Día {hoy.day:02d}/"
    for a in listar(base_po):
        if "Anexo2_Hidrologia" in a or "Anexo5_Restricciones" in a:
            b = bajar(a)
            if b:
                res.setdefault("prog_operacion", {})[a.rsplit("/", 1)[-1]] = volcar_libro(
                    b, "prog_operacion/" + ("hidrologia" if "Hidro" in a else "restricciones"), None, 200)
    # 4) Programa semanal de intervenciones (hoja MANTTOS)
    sem = listar(f"Operación/Programa de Mantenimiento/Programa Semanal/{hoy.year}/")
    if sem:
        ultima = sem[0]
        for sub in ("Final/", "Preliminar/"):
            arch = [a for a in listar(ultima + sub) if "Anexo1" in a and a.lower().endswith((".xls", ".xlsx"))]
            if arch:
                b = bajar(arch[0])
                if b:
                    res["semanal"] = {"archivo": arch[0], "hojas": volcar_libro(b, "semanal", {"MANTTOS"}, 600)}
                break
    # 5) Eventos relevantes filtrados por línea de transmisión (familia 8)
    datos = {"FechaInicio": (hoy - dt.timedelta(days=3)).strftime("%d/%m/%Y"), "FechaFin": hoy.strftime("%d/%m/%Y"),
             "IdTipoEvento": 0, "Version": "N", "Turno": "", "IdTipoEmpresa": 0, "IdEmpresa": 0, "IdFamilia": 8,
             "IndInterrupcion": -1, "NroPagina": 1}
    h = S.post(RAIZ + "eventos/relevantes/lista", data=datos, timeout=90).text
    (OUT / "eventos_lineas.html").write_text(h[:150000], encoding="utf-8")
    res["descargas"] = log
    (OUT / "resultado.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("OK exploración 4")
    return {"paginas": {k: {"status": 200 if k in res else 0}
                        for k in ("ieod", "intervenciones_zip", "prog_operacion", "semanal")}}


if __name__ == "__main__":
    main()
