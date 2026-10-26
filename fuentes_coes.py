#!/usr/bin/env python3
"""
Lectores de fuentes públicas del COES para el reporte diario.

- IEOD Anexo A (Post Operación/Reportes/IEOD): eventos, mantenimientos ejecutados, indisponibilidades
  de generación, restricciones operativas, volúmenes de embalses, disponibilidad de gas, generación y
  demanda por áreas.
- Programa Diario de Intervenciones (Anexo 1): intervenciones programadas para el día.
- Portal de Información: demanda ejecutada cada 30 min.

Todos los lectores devuelven listas de diccionarios con claves normalizadas.
"""
import datetime as dt
import io
import re
import unicodedata
import zipfile
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

LIMA = ZoneInfo("America/Lima")
RAIZ = "https://www.coes.org.pe/Portal/"
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SETIEMBRE",
         "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                  "X-Requested-With": "XMLHttpRequest"})

# Cuencas de embalses a reportar (nombre en el IEOD -> etiqueta)
CUENCAS_EMBALSES = {"MANTARO": "Mantaro", "P.C.H CHAGLLA": "Chaglla", "CHAGLLA": "Chaglla", "RIMAC": "Rímac",
                    "SAN GABAN": "San Gabán", "SANTA": "Santa"}


# --------------------------------------------------------------------------- utilidades
def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return re.sub(r"\s+", " ", str(v)).strip()


def numero(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def fecha_hora(v):
    """Acepta datetime, número de serie de Excel o texto dd/mm/aaaa [hh:mm[:ss]]."""
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day)
    n = numero(v)
    if n is not None and 20000 < n < 80000:
        return dt.datetime(1899, 12, 30) + dt.timedelta(minutes=round(n * 1440))
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", str(v))
    if m:
        d, mo, y, h, mi = m.groups()
        base = dt.datetime(int(y), int(mo), int(d))
        return base + dt.timedelta(hours=int(h or 0), minutes=int(mi or 0))
    return None


def tabla(filas, claves_cabecera, max_filas=2000):
    """Encuentra la fila de cabecera que contiene todas las claves y devuelve registros {cabecera: valor}."""
    claves = [norm(c) for c in claves_cabecera]
    for i, fila in enumerate(filas[:40]):
        cab = [norm(c) for c in fila]
        if all(any(c == k or c.startswith(k) for c in cab) for k in claves):
            regs = []
            for f in filas[i + 1:i + 1 + max_filas]:
                if not any(texto(x) for x in f):
                    continue
                reg = {}
                for j, c in enumerate(cab):
                    if c and j < len(f) and c not in reg:
                        reg[c] = f[j]
                regs.append(reg)
            return regs
    return []


def tension_kv(equipo, descripcion=""):
    """Tensión de una línea a partir de su código COES (L-2xxx = 220 kV, L-5xxx = 500 kV...)."""
    m = re.search(r"\bL-?\s?(\d)(\d{3})\b", norm(equipo))
    if m:
        return {"1": 138, "2": 220, "5": 500, "6": 60, "3": 33}.get(m.group(1))
    m = re.search(r"(\d{2,3})\s*KV", norm(descripcion))
    return int(m.group(1)) if m else None


def clasificar_equipo(equipo, ubicacion="", descripcion=""):
    """G = unidad o central de generación, T = transmisión (cuando el archivo no trae la columna)."""
    e, u, d = norm(equipo), norm(ubicacion), norm(descripcion)
    if re.match(r"^(L|CL|T|AT|TR|SA|SB|IN|REB|R|B|SVC|CS|BC)-?\s?\d", e) or e in ("SS.EE.", "BARRA") or "BARRA" in e:
        return "T"
    if (e == "CENTRAL" or re.match(r"^(G|TG|TV|GT|ST|U|CC|MAK|INDEP_G|RF-|PFV|WTG|AG)\w*", e)
            or re.match(r"^(C\.?[HTSE]\.?|CENTRAL|PARQUE|PLANTA)\b", u)
            or any(k in d for k in ("GENERADOR", "UNIDAD", "TURBINA", "CENTRAL"))):
        return "G"
    return "T"


def es_linea(equipo, tipo=""):
    return bool(re.match(r"^L-?\s?\d{4}", norm(equipo))) or "LINEA" in norm(tipo)


# --------------------------------------------------------------------------- descarga
def bajar(ruta, timeout=180):
    r = S.get(RAIZ + "browser/download?url=" + quote(ruta, safe="/"), timeout=timeout)
    return r.content if r.ok and len(r.content) > 500 else None


def listar(ruta):
    import html as h
    r = S.post(RAIZ + "browser/vistadatos", data={"baseDirectory": ruta, "url": ruta, "indicador": "S",
                                                  "initialLink": "x", "orderFolder": "D"}, timeout=90)
    return [h.unescape(p) for p, t, e in re.findall(r"openBlob\('([^']+)',\s*'([DF])',\s*'([^']*)'\)", r.text)]


def libro(b):
    """{nombre hoja: filas} desde xlsx o xls."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
        return {ws.title.strip(): [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    except Exception:
        import xlrd
        wb = xlrd.open_workbook(file_contents=b)
        return {sh.name.strip(): [sh.row_values(i) for i in range(sh.nrows)] for sh in wb.sheets()}


# --------------------------------------------------------------------------- IEOD
def descargar_ieod(hasta: dt.date, dias_atras=4):
    """Último IEOD Anexo A disponible hasta la fecha indicada. Devuelve (fecha, hojas)."""
    for k in range(dias_atras):
        d = hasta - dt.timedelta(days=k)
        carpeta = f"Post Operación/Reportes/IEOD/{d.year}/{d.month:02d}_{MESES[d.month - 1].capitalize()}/{d.day:02d}/"
        b = bajar(carpeta + f"AnexoA_{d:%d%m}.xlsx")
        if b:
            return d, libro(b)
    return None, {}


def _reg_intervencion(r):
    return {
        "empresa": texto(r.get("EMPRESA")),
        "ubicacion": texto(r.get("UBICACION")),
        "equipo": texto(r.get("EQUIPO")),
        "inicio": fecha_hora(r.get("INICIO")),
        "final": fecha_hora(r.get("FINAL")),
        "descripcion": texto(r.get("DESCRIPCION")),
        "mw": numero(r.get("MW INDISP.")) or 0.0,
        "programado": texto(r.get("PROG.") or r.get("PROGR.")).upper().startswith("P"),
        "estado": texto(r.get("DISPON")),
        "interrupcion": texto(r.get("INTERRUPC.")).upper().startswith(("S", "Y")),
        "tipo": texto(r.get("TIPO")),
        "clase": texto(r.get("TIPOEQ_OSINERG")).upper(),   # G = generación, T = transmisión
    }


def parsear_ieod(hojas):
    out = {}
    ev = tabla(hojas.get("EVENTOS", []), ["TIPO DE EVENTO", "EMPRESA", "EQUIPO", "INICIO"])
    out["eventos"] = [{
        "tipo": texto(r.get("TIPO DE EVENTO")), "empresa": texto(r.get("EMPRESA")),
        "ubicacion": texto(r.get("UBICACION")), "tipo_equipo": texto(r.get("TIPO DE EQUIPO")),
        "equipo": texto(r.get("EQUIPO")), "inicio": fecha_hora(r.get("INICIO")), "final": fecha_hora(r.get("FINAL")),
        "descripcion": texto(r.get("DESCRIPCION")), "mw": numero(r.get("MW INDISP.")),
        "interrupcion": texto(r.get("INTERRUPCION (SI/NO)")).upper().startswith("S"),
        "kv": numero(r.get("TENSION DE FALLA (KV)")),
    } for r in ev if texto(r.get("EMPRESA"))]

    out["indisponibilidades"] = [_reg_intervencion(r) for r in
                                 tabla(hojas.get("INDISP", []), ["EMPRESA", "EQUIPO", "INICIO", "MW INDISP."])
                                 if texto(r.get("EMPRESA"))]
    out["mantenimientos"] = [_reg_intervencion(r) for r in
                             tabla(hojas.get("MANTENIMIENTO EJECUTADOS", []), ["EMPRESA", "EQUIPO", "INICIO"])
                             if texto(r.get("EMPRESA"))]
    out["restricciones"] = [{
        "inicio": texto(r.get("HORA INICIO")), "final": texto(r.get("HORA FINAL")),
        "empresa": texto(r.get("EMPRESA")), "ubicacion": texto(r.get("UBICACION")),
        "equipo": texto(r.get("EQUIPO")), "descripcion": texto(r.get("DESCRIPCION")),
    } for r in tabla(hojas.get("RESTRIC_OPE", []), ["EMPRESA", "UBICACION", "EQUIPO", "DESCRIPCION"])
        if texto(r.get("EMPRESA"))]
    out["gas"] = [{
        "empresa": texto(r.get("EMPRESA")), "gasoducto": texto(r.get("GASEODUCTO")),
        "volumen_mm3": numero(r.get("VOLUMEN DE GAS (MM3)")), "observaciones": texto(r.get("OBSERVACIONES")),
    } for r in tabla(hojas.get("DISPONIBILIDAD_GAS", []), ["EMPRESA", "GASEODUCTO"]) if texto(r.get("EMPRESA"))]
    out["embalses"] = parsear_volumenes(hojas.get("PRINCIP_VOLÚMENES") or hojas.get("PRINCIP_VOLUMENES") or [])
    out["demanda_areas"] = parsear_demanda_areas(hojas.get("DEMANDA_AREAS", []))
    out["gen_areas"] = parsear_gen_areas(hojas.get("G_AREAS", []))
    return out


def parsear_volumenes(filas):
    """Tabla ancha: filas EMPRESA/CUENCA/INSTALACION/EQUIPO/TIPO/FECHA(unidad) y luego horas."""
    etiquetas = {}
    datos = []
    for f in filas:
        if not f:
            continue
        k = norm(f[0])
        if k in ("EMPRESA", "CUENCA", "INSTALACION", "EQUIPO", "TIPO", "FECHA"):
            etiquetas[k] = f
        elif re.fullmatch(r"\d{1,2}:\d{2}", texto(f[0])):
            datos.append(f)
    if "EQUIPO" not in etiquetas:
        return []
    datos.sort(key=lambda f: [int(x) for x in texto(f[0]).split(":")])
    out = []
    for j in range(1, len(etiquetas["EQUIPO"])):
        cuenca = norm(etiquetas.get("CUENCA", [None] * (j + 1))[j])
        if cuenca not in CUENCAS_EMBALSES:
            continue
        serie = [numero(f[j]) for f in datos if j < len(f)]
        serie = [v for v in serie if v is not None]
        if not serie:
            continue
        out.append({
            "cuenca": CUENCAS_EMBALSES[cuenca],
            "empresa": texto(etiquetas.get("EMPRESA", [""] * (j + 1))[j]),
            "embalse": texto(etiquetas["EQUIPO"][j]).replace("_", " ").title(),
            "variable": texto(etiquetas.get("TIPO", [""] * (j + 1))[j]).capitalize(),
            "unidad": texto(etiquetas.get("FECHA", [""] * (j + 1))[j]),
            "inicio": serie[0], "final": serie[-1], "variacion": serie[-1] - serie[0],
        })
    return out


def _horas(filas, col_hora=1):
    for f in filas:
        if len(f) > col_hora and re.fullmatch(r"\d{1,2}:\d{2}", texto(f[col_hora])):
            yield f


def parsear_demanda_areas(filas):
    out = []
    for f in _horas(filas):
        out.append({"hora": texto(f[1]), "sein": numero(f[3]), "norte": numero(f[4]), "centro": numero(f[5]),
                    "sur": numero(f[6])})
    return out


def parsear_gen_areas(filas):
    out = []
    for f in _horas(filas):
        out.append({"hora": texto(f[1]), "norte": numero(f[14]), "centro": numero(f[15]), "sur": numero(f[16]),
                    "total": numero(f[17])})
    return out


# --------------------------------------------------------------------------- intervenciones programadas
def intervenciones_programadas(dia: dt.date):
    mes = f"{dia.month:02d}_{MESES[dia.month - 1]}"
    for etiqueta in (f"Día {dia.day:02d}", f"Día {dia.day}"):
        base = f"Operación/Programa de Mantenimiento/Programa Diario/{dia.year}/{mes}/{etiqueta}/"
        for a in listar(base):
            if "Anexo1" in a and a.lower().endswith(".zip"):
                b = bajar(a)
                if not b:
                    continue
                z = zipfile.ZipFile(io.BytesIO(b))
                for n in z.namelist():
                    if n.lower().endswith((".xlsx", ".xls", ".xlsm")):
                        hojas = libro(z.read(n))
                        nombre = next((k for k in hojas if "PROGRAMADO" in norm(k)), None) or \
                            next((k for k in hojas if "MANTTO" in norm(k)), None) or next(iter(hojas))
                        regs = [_reg_intervencion(r) for r in
                                tabla(hojas[nombre], ["EMPRESA", "EQUIPO", "INICIO", "MW INDISP."])
                                if texto(r.get("EMPRESA"))]
                        for r in regs:
                            if not r["clase"]:
                                r["clase"] = clasificar_equipo(r["equipo"], r["ubicacion"], r["descripcion"])
                        return regs
    return []


# --------------------------------------------------------------------------- portal de información
def demanda_ejecutada(dia: dt.date):
    j = S.post(RAIZ + "portalinformacion/demanda",
               data={"fechaInicial": dia.strftime("%d/%m/%Y"), "fechaFinal": dia.strftime("%d/%m/%Y")},
               timeout=120).json()
    out = {}
    for s in (j.get("Chart") or {}).get("Series", []):
        out[s["Name"]] = [(dt.datetime.strptime(d["Nombre"], "%Y/%m/%d %H:%M:%S").replace(tzinfo=LIMA), d["Valor"])
                          for d in s["Data"] if d.get("Valor") is not None]
    return out


# --------------------------------------------------------------------------- filtros del reporte
def filtrar_lineas_220(regs):
    out = []
    for r in regs:
        if not es_linea(r["equipo"], r.get("tipo_equipo", "")):
            continue
        kv = r.get("kv") or tension_kv(r["equipo"], r.get("descripcion", ""))
        if kv and kv >= 220:
            out.append({**r, "kv": kv})
    return out


def solo_generacion(regs):
    return [r for r in regs if r.get("clase") == "G"]
