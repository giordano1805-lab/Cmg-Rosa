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


def libro(b, solo=None):
    """{nombre hoja: filas} desde xlsx o xls (solo: nombres de hojas a leer, para ahorrar tiempo)."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
        return {ws.title.strip(): [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets
                if not solo or ws.title.strip() in solo}
    except Exception:
        import xlrd
        wb = xlrd.open_workbook(file_contents=b)
        return {sh.name.strip(): [sh.row_values(i) for i in range(sh.nrows)] for sh in wb.sheets()}


# --------------------------------------------------------------------------- IEOD
_LISTADOS = {}


def _listar_c(ruta):
    if ruta not in _LISTADOS:
        try:
            _LISTADOS[ruta] = listar(ruta)
        except Exception:
            _LISTADOS[ruta] = []
    return _LISTADOS[ruta]


def _nombre(ruta):
    return ruta.rstrip("/").rsplit("/", 1)[-1]


def _buscar_anexo_a(d: dt.date):
    """Busca el Anexo A recorriendo las carpetas del COES (en años anteriores cambian nombres y formatos)."""
    base = f"Post Operación/Reportes/IEOD/{d.year}/"
    mes = next((i for i in _listar_c(base) if i.endswith("/") and re.match(rf"0?{d.month}\D", _nombre(i) + "_")), None)
    if not mes:
        return None
    dia = next((i for i in _listar_c(mes) if i.endswith("/") and re.match(rf"0?{d.day}\D", _nombre(i) + "_")), None)
    if not dia:
        return None
    archivos = [i for i in _listar_c(dia) if not i.endswith("/")]
    clave = lambda i: re.sub(r"[^A-Z]", "", norm(_nombre(i)))
    cands = [i for i in archivos if "ANEXOA" in clave(i)] or [i for i in archivos if "IEOD" in clave(i)]
    for ruta in sorted(cands, key=lambda i: (not i.lower().endswith(".xlsx"), i)):
        b = bajar(ruta)
        if not b:
            continue
        if ruta.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                inner = next((n for n in z.namelist() if "ANEXOA" in re.sub(r"[^A-Z]", "", norm(n))
                              and n.lower().endswith((".xlsx", ".xls"))), None)
                if not inner:
                    continue
                b = z.read(inner)
        return b
    return None


def descargar_ieod(hasta: dt.date, dias_atras=4, solo=None):
    """Último IEOD Anexo A disponible hasta la fecha indicada. Devuelve (fecha, hojas)."""
    for k in range(dias_atras):
        d = hasta - dt.timedelta(days=k)
        carpeta = f"Post Operación/Reportes/IEOD/{d.year}/{d.month:02d}_{MESES[d.month - 1].capitalize()}/{d.day:02d}/"
        b = bajar(carpeta + f"AnexoA_{d:%d%m}.xlsx")
        if not b and d < dt.date.today() - dt.timedelta(days=3):
            b = _buscar_anexo_a(d)
        if b:
            return d, libro(b, solo)
    return None, {}


def listados_ieod():
    """Listados de carpetas consultados (para diagnóstico)."""
    return {k: v for k, v in _LISTADOS.items()}


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
            "prom": sum(serie) / len(serie),
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


def _regs_mantenimiento(hojas):
    """Registros de intervenciones de cualquier hoja que tenga EMPRESA / EQUIPO / INICIO (formatos variables)."""
    orden = sorted(hojas, key=lambda k: (not ("PROGRAM" in norm(k) or "MANT" in norm(k)), k))
    for nombre in orden:
        filas = tabla(hojas[nombre], ["EMPRESA", "EQUIPO", "INICIO"])
        if not filas:
            continue
        regs = []
        for r in filas:
            if not texto(r.get("EMPRESA")):
                continue
            r = dict(r)
            if "MW INDISP." not in r:
                k = next((k for k in r if k.startswith("MW")), None)
                r["MW INDISP."] = r.get(k) if k else None
            if r.get("FINAL") is None:
                k = next((k for k in r if k.startswith("FIN")), None)
                r["FINAL"] = r.get(k) if k else None
            reg = _reg_intervencion(r)
            if not reg["clase"]:
                reg["clase"] = clasificar_equipo(reg["equipo"], reg["ubicacion"], reg["descripcion"])
            regs.append(reg)
        if regs:
            return nombre, regs
    return None, []


def programa_mensual(ref: dt.date):
    """Programa Mensual de Mantenimiento del COES del mes de `ref`: (registros, diagnóstico)."""
    diag = {"buscado": f"{ref:%Y-%m}", "rutas": []}
    base = "Operación/Programa de Mantenimiento/Programa Mensual/"
    anio = next((i for i in _listar_c(base) if i.endswith("/") and _nombre(i).startswith(str(ref.year))), None)
    diag["rutas"].append([base, _listar_c(base)[:40]])
    if not anio:
        return [], diag
    mes_n = MESES[ref.month - 1]
    items = _listar_c(anio)
    diag["rutas"].append([anio, items[:60]])
    mes = next((i for i in items if i.endswith("/") and (re.match(rf"0?{ref.month}\D", _nombre(i) + "_")
                                                      or mes_n in norm(_nombre(i)))), None)
    archivos = []
    if mes:
        for i in _listar_c(mes):
            if i.endswith("/"):
                archivos += [j for j in _listar_c(i) if not j.endswith("/")]
            else:
                archivos.append(i)
        diag["rutas"].append([mes, _listar_c(mes)[:60]])
    else:
        archivos = [i for i in items if not i.endswith("/") and mes_n in norm(_nombre(i))]
    cl = lambda i: re.sub(r"[^A-Z0-9]", "", norm(_nombre(i)))
    cands = [i for i in archivos if i.lower().endswith((".zip", ".xlsx", ".xls", ".xlsm"))]
    cands.sort(key=lambda i: (not ("ANEXO1" in cl(i) or "MANTENIMIENTO" in cl(i)), "ANALISIS" in cl(i), i))
    diag["candidatos"] = cands[:10]
    for ruta in cands[:6]:
        b = bajar(ruta)
        if not b:
            continue
        libros = []
        if ruta.lower().endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(b))
                libros = [(n, z.read(n)) for n in z.namelist() if n.lower().endswith((".xlsx", ".xls", ".xlsm"))]
            except Exception:
                continue
        else:
            libros = [(ruta, b)]
        for n, contenido in libros:
            try:
                hojas = libro(contenido)
            except Exception:
                continue
            hoja, regs = _regs_mantenimiento(hojas)
            diag.setdefault("libros", []).append([n, list(hojas)[:20], hoja, len(regs)])
            if regs:
                diag["usado"] = [ruta, n, hoja]
                return regs, diag
    return [], diag


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


def mw_simultaneo(regs, t):
    """MW fuera de servicio en el instante t sin contar dos veces la misma capacidad: por central se toma el
    mayor entre el registro de central completa y la suma de sus unidades (cada unidad una sola vez)."""
    por = {}
    for r in regs:
        i, f = r.get("inicio"), r.get("final") or r.get("inicio")
        if isinstance(i, str):
            i = dt.datetime.fromisoformat(i)
        if isinstance(f, str):
            f = dt.datetime.fromisoformat(f)
        if not i or not (i <= t < f):
            continue
        c = por.setdefault(norm(r.get("ubicacion")), {"cen": 0.0, "uni": {}})
        mw = r.get("mw") or 0.0
        if norm(r.get("equipo")) == "CENTRAL":
            c["cen"] = max(c["cen"], mw)
        else:
            u = norm(r.get("equipo"))
            c["uni"][u] = max(c["uni"].get(u, 0.0), mw)
    return sum(max(c["cen"], sum(c["uni"].values())) for c in por.values())


def perfil_indisponible(regs, dia: dt.date):
    """Perfil de 48 medias horas (MW) sin doble conteo + estadísticos del día."""
    t0 = dt.datetime(dia.year, dia.month, dia.day)
    perfil = [round(mw_simultaneo(regs, t0 + dt.timedelta(minutes=30 * k + 15)), 1) for k in range(48)]
    mx = max(perfil) if perfil else 0.0
    k = perfil.index(mx) if perfil else 0
    prom = sum(perfil) / 48
    return {"perfil": perfil, "max": mx, "hora_max": f"{k // 2:02d}:{30 * (k % 2):02d}", "prom": round(prom, 1),
            "mwh": round(prom * 24, 0), "cierre": perfil[-1] if perfil else 0.0}


def codigo_linea(txt):
    m = re.search(r"\bL-?\s?(\d{4}[A-Z]?)\b", norm(txt))
    return f"L-{m.group(1)}" if m else None


def tramos_lineas(*listas):
    """{código de línea: 'Subestación A – Subestación B'} a partir de los registros del COES.
    Prioriza el tramo escrito en la descripción, p. ej. 'L-2051 (CAMPO ARMIÑO - COTARUSE)'."""
    out = {}
    for regs in listas:
        for r in regs or []:
            d = texto(r.get("descripcion"))
            for m in re.finditer(r"\bL-?\s?(\d{4}[A-Z]?)\s*\(([^()]{3,60}?)\s*-\s*([^()]{3,60}?)\)", d):
                if not re.search(r"\d{3}", m.group(2) + m.group(3)):
                    out[f"L-{m.group(1)}"] = f"{m.group(2).strip()} – {m.group(3).strip()}"
            cod = codigo_linea(r.get("equipo"))
            u = texto(r.get("ubicacion"))
            if cod and cod not in out and " - " in u:
                a, b = u.split(" - ", 1)
                out[cod] = f"{a.strip()} – {b.strip()}"
    return {k: " – ".join(w.strip().title().replace("?", "ñ") for w in v.split("–")) for k, v in out.items()}


def solo_generacion(regs):
    return [r for r in regs if r.get("clase") == "G"]


# --------------------------------------------------------------------------- demanda histórica
def demanda_rango(d0: dt.date, d1: dt.date):
    """[(ts fin de intervalo, MW ejecutado)] entre d0 y d1 inclusive (el portal acepta rangos de un mes)."""
    j = S.post(RAIZ + "portalinformacion/demanda",
               data={"fechaInicial": d0.strftime("%d/%m/%Y"), "fechaFinal": d1.strftime("%d/%m/%Y")},
               timeout=240).json()
    for s in (j.get("Chart") or {}).get("Series", []):
        if norm(s["Name"]).startswith("EJECUTADO"):
            return [(dt.datetime.strptime(d["Nombre"], "%Y/%m/%d %H:%M:%S"), float(d["Valor"]))
                    for d in s["Data"] if d.get("Valor") is not None]
    return []


# --------------------------------------------------------------------------- hidro de pasada (IEOD)
def hidro_pasada(hojas):
    """[(hora 'HH:MM', MW)] de la hoja TIPO_RECURSO (columna H. PASADA)."""
    filas = hojas.get("TIPO_RECURSO") or []
    col = None
    for f in filas[:15]:
        for j, v in enumerate(f):
            if "PASADA" in norm(v) and "HIDRO" not in norm(v):
                col = j
        if col is not None:
            break
    if col is None:
        return []
    out = []
    for f in filas:
        h = texto(f[1]) if len(f) > 1 else ""
        if re.fullmatch(r"\d{1,2}:\d{2}", h) and col < len(f) and numero(f[col]) is not None:
            out.append((h, numero(f[col])))
    return out


def recursos_dia(hojas):
    """{hora 'HH:MM': {pasada, regulacion, eolica}} (MW) de la hoja TIPO_RECURSO."""
    filas = hojas.get("TIPO_RECURSO") or []
    cols = {}
    for f in filas[:15]:
        for j, v in enumerate(f):
            n = norm(v)
            if "PASADA" in n and "HIDRO" not in n:
                cols.setdefault("pasada", j)
            elif "REGULACION" in n and "HIDRO" not in n:
                cols.setdefault("regulacion", j)
            elif n == "EOLICA":
                cols.setdefault("eolica", j)
        if cols:
            break
    out = {}
    for f in filas:
        h = texto(f[1]) if len(f) > 1 else ""
        if not re.fullmatch(r"\d{1,2}:\d{2}", h):
            continue
        r = {k: numero(f[j]) for k, j in cols.items() if j < len(f) and numero(f[j]) is not None}
        if r:
            out[h] = r
    return out


# --------------------------------------------------------------------------- flujos y congestión (IEOD)
HOJAS_TRANSMISION = ("FLUJOS", "CONGESTION_SIST_TRANS", "INTERCONEXIONES", "FLUJOS_INTERCONEXIÓN")


def volcar_hojas(hojas, carpeta, nombres=HOJAS_TRANSMISION, filas=160, cols=120):
    """Guarda un extracto CSV de hojas del IEOD (para revisar su formato)."""
    import csv
    carpeta.mkdir(parents=True, exist_ok=True)
    for n in nombres:
        h = hojas.get(n)
        if h is None:
            continue
        with (carpeta / f"{n}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for r in h[:filas]:
                w.writerow([texto(x) if not isinstance(x, (int, float)) else x for x in list(r)[:cols]])


def flujos_lineas(hojas):
    """Tabla ancha de la hoja FLUJOS: columnas = líneas (código L-xxxx), filas = horas.
    Devuelve {linea: {'kv', 'nombre', 'serie': [[min_dia, MW], ...]}} solo para ≥220 kV."""
    filas = hojas.get("FLUJOS") or []
    datos = []
    for i, f in enumerate(filas):
        for j in (0, 1):
            if len(f) > j and re.fullmatch(r"\d{1,2}:\d{2}", texto(f[j])):
                datos.append((i, j))
                break
    if not datos:
        return {}
    i0, jh = datos[0]
    cab = filas[max(0, i0 - 8):i0]
    out = {}
    ncol = max(len(f) for f in filas[i0:i0 + 5])
    fila_ss = next((f for f in cab if f and norm(f[0]).startswith("SS")), [])
    ss, ultimo = {}, ""
    for j in range(ncol):
        if j < len(fila_ss) and texto(fila_ss[j]) and j > jh:
            ultimo = texto(fila_ss[j])
        ss[j] = ultimo
    for j in range(jh + 1, ncol):
        textos = [texto(f[j]) for f in cab if j < len(f) and texto(f[j])]
        cod = next((m.group(0) for t in textos for m in [re.search(r"\bL-?\s?\d{4}[A-Z]?(/\d)?\b", norm(t))] if m), None)
        if not cod:
            continue
        kv = tension_kv(cod, " ".join(textos))
        if not kv or kv < 220:
            continue
        serie = []
        for i, _ in datos:
            f = filas[i]
            v = numero(f[j]) if j < len(f) else None
            if v is not None:
                serie.append([_min_dia(texto(f[jh])), round(v, 1)])
        if serie:
            nombre = ss.get(j) or next((t for t in textos if norm(t) != norm(cod) and not re.fullmatch(r"[\d.,-]+", t)), "")
            k = cod.replace(" ", "")
            prev = out.get(k)
            ext = (prev or {}).get("extremos", [])
            if nombre and nombre not in ext:
                ext = ext + [nombre]
            out[k] = {"kv": kv, "nombre": nombre, "serie": serie, "extremos": ext}
    return out


def tramos_de_flujos(flujos):
    """Si una línea se mide en sus dos subestaciones, el tramo es 'SE A – SE B'."""
    out = {}
    for cod, x in (flujos or {}).items():
        ext = [re.sub(r"(?i)^S\.?E\.?\s+", "", e).strip().title() for e in x.get("extremos", [])]
        ext = list(dict.fromkeys(e for e in ext if e))
        if len(ext) >= 2:
            out[cod] = f"{ext[0]} – {ext[1]}"
    return out


def interconexiones(hojas):
    """Hoja INTERCONEXIONES: {enlace: {'lineas': {nombre: [[min_dia, MW]]}, 'total': [[min_dia, MW]]}}.
    Signo según el COES (p. ej. Centro-Norte negativo = flujo de centro a norte)."""
    filas = hojas.get("INTERCONEXIONES") or []
    i0 = next((i for i, f in enumerate(filas[:30]) if len(f) > 1 and norm(f[0]) == "FECHA" and norm(f[1]) == "HORA"), None)
    if i0 is None:
        return {}
    cab, grupos = filas[i0], filas[i0 - 1] if i0 else []
    out, g = {}, ""
    cols = []
    for j in range(2, len(cab)):
        if j < len(grupos) and texto(grupos[j]):
            g = re.sub(r"(?i)^interconexi[oó]n\s+", "", texto(grupos[j])).title()
        n = texto(cab[j])
        if g and n:
            cols.append((j, g, n))
    for j, g, n in cols:
        serie = []
        for f in filas[i0 + 1:]:
            if len(f) > 1 and re.fullmatch(r"\d{1,2}:\d{2}", texto(f[1])) and j < len(f) and numero(f[j]) is not None:
                serie.append([_min_dia(texto(f[1])), round(numero(f[j]), 1)])
        if not serie:
            continue
        e = out.setdefault(g, {"lineas": {}, "total": []})
        if norm(n) == "TOTAL":
            e["total"] = serie
        else:
            e["lineas"][n.title().replace("L-", "L-")] = serie
    return out


def congestiones(hojas):
    """Registros de la hoja CONGESTION_SIST_TRANS con la cabecera detectada automáticamente."""
    filas = hojas.get("CONGESTION_SIST_TRANS") or []
    for i, f in enumerate(filas[:40]):
        cab = [norm(x) for x in f]
        if sum(1 for c in cab if c) >= 3 and any(k in " ".join(cab) for k in ("INICIO", "EQUIPO", "LINEA", "HORA")):
            regs = []
            for g in filas[i + 1:i + 300]:
                if not any(texto(x) for x in g):
                    continue
                reg = {cab[j]: (fecha_hora(g[j]).isoformat() if isinstance(g[j], dt.datetime) else texto(g[j]))
                       for j in range(min(len(cab), len(g))) if cab[j] and texto(g[j])}
                if len(reg) >= 2:
                    regs.append(reg)
            return {"columnas": [c for c in cab if c], "registros": regs}
    return {"columnas": [], "registros": []}


def generacion_ieod(hojas, dia: dt.date):
    """Producción por tipo de recurso cada 30 min según la hoja TIPO_RECURSO del IEOD (clasificación oficial
    del COES). Devuelve {datetime fin de intervalo (Lima): {recurso: MW}} con nombres compatibles con el portal."""
    filas = hojas.get("TIPO_RECURSO") or []
    i0 = next((i for i, f in enumerate(filas[:15]) if any(norm(x) == "HORA" for x in f)), None)
    if i0 is None:
        return {}
    cab = [norm(x) for x in filas[i0]]
    jh = cab.index("HORA")
    nombres = {}
    for j in range(jh + 1, len(cab)):
        c = cab[j]
        if not c or c == "TOTAL" or c in ("EMPRESA", "CENTRAL"):
            if c in ("TOTAL", "EMPRESA"):
                break
            continue
        nombres[j] = {"H. PASADA": "HIDRICO PASADA", "H. REGULACION": "HIDRICO REGULACION"}.get(c, c)
    out = {}
    t0 = dt.datetime(dia.year, dia.month, dia.day, tzinfo=LIMA)
    for f in filas[i0 + 1:]:
        h = texto(f[jh]) if len(f) > jh else ""
        if not re.fullmatch(r"\d{1,2}:\d{2}", h):
            continue
        reg = {n: numero(f[j]) for j, n in nombres.items() if j < len(f) and numero(f[j]) is not None}
        if reg:
            out[t0 + dt.timedelta(minutes=_min_dia(h))] = reg
    return out


# --------------------------------------------------------------------------- despacho con diésel
COMB_DIESEL = ("D2", "DIESEL", "B5", "R500", "R6", "RESIDUAL", "NLH", "RFG", "NAFTA", "REFINER")


def tipo_combustible(comb):
    c = norm(comb)
    if any(k in c for k in ("D2", "DIESEL", "B5")):
        return "Diésel D2"
    if any(k in c for k in ("R500", "R6", "RESIDUAL")):
        return "Residual"
    return "Gas de refinería"


def _min_dia(hora):
    """'HH:MM' (fin del intervalo) → minutos desde el inicio del día operativo (30..1440)."""
    h, m = (int(x) for x in hora.split(":"))
    v = h * 60 + m
    return v if v else 1440


def es_reserva_fria(*textos):
    t = " ".join(norm(x) for x in textos)
    return bool(re.search(r"(^|[\s.])RF[\s_-]", t) or "RESERVA FRIA" in t)


def despacho_unidades(hojas):
    """{unidad: {'empresa', 'mw': {min_dia: MW}}} de la hoja DESPACHO_EJECUTADO."""
    filas = hojas.get("DESPACHO_EJECUTADO") or []
    datos = [i for i, f in enumerate(filas) if len(f) > 1 and re.fullmatch(r"\d{1,2}:\d{2}", texto(f[1]))]
    if not datos:
        return {}
    i0 = datos[0]
    nombres, empresas = filas[i0 - 1], filas[i0 - 2]
    out = {}
    for j in range(2, len(nombres)):
        n = texto(nombres[j])
        if not n:
            continue
        serie = {}
        for i in datos:
            f = filas[i]
            v = numero(f[j]) if j < len(f) else None
            if v is not None:
                serie[_min_dia(texto(f[1]))] = v
        out[n] = {"empresa": texto(empresas[j]) if j < len(empresas) else "", "mw": serie}
    return out


ABREV = (("PUERTO", "PTO"), ("BRAVO", "BRVO"), ("SANTA", "STA"), ("RESERVA FRIA", "RF"), ("LAS FLORES", "LFLORES"))


def _clave_unidad(s):
    s = norm(s)
    for a, b in ABREV:
        s = s.replace(a, b)
    return re.sub(r"[^A-Z0-9]", "", s)


UNIDAD_PROPIA = "HUANCHOR"


def despacho_unidad(hojas, nombre=UNIDAD_PROPIA):
    """{min_dia: MW} de una unidad en DESPACHO_EJECUTADO (por defecto CH Huanchor)."""
    du = despacho_unidades(hojas)
    clave = next((u for u in du if norm(u) == norm(nombre)), None) or \
        next((u for u in du if norm(nombre) in norm(u)), None)
    return dict(du[clave]["mw"]) if clave else {}


def diesel_despacho(hojas, dia: dt.date):
    """Unidades que operaron con diésel/residual según el HOP del IEOD, con su potencia (DESPACHO_EJECUTADO).
    Devuelve {'unidades': [...], 'serie': {min_dia: {'rf': MW, 'otras': MW}}}."""
    hop = [r for r in tabla(hojas.get("HOP", []), ["EMPRESA", "CENTRAL", "MODO DE OPERACION"])
           if any(k in norm(r.get("MODO DE OPERACION")).rsplit(" - ", 1)[-1] for k in COMB_DIESEL)]
    desp = despacho_unidades(hojas)
    clave = {u: _clave_unidad(u) for u in desp}
    t0 = dt.datetime(dia.year, dia.month, dia.day)
    agr, serie = {}, {}
    for r in hop:
        central = re.sub(r"^C\.?\s?T\.?\s*B?\.?\s*", "", norm(r.get("CENTRAL")))
        grupo = norm(r.get("GRUPO"))
        comb = norm(r.get("MODO DE OPERACION")).rsplit(" - ", 1)[-1]
        kc = _clave_unidad(central)
        kg = _clave_unidad(grupo)
        cand = [u for u, k in clave.items() if kc and (kc in k or k in kc)]
        if grupo and grupo != "CENTRAL":
            toks = [_clave_unidad(t) for t in re.split(r"[\s_&-]+", grupo) if re.search(r"\d", t)] or [kg]
            cand = ([u for u in cand if all(t in clave[u] for t in toks)]
                    or [u for u, k in clave.items() if kg and kg in k and kc[:4] in k])
        ini, fin = fecha_hora(r.get("INICIO")), fecha_hora(r.get("FINAL"))
        rf = es_reserva_fria(r.get("CENTRAL"), r.get("EMPRESA"), *cand)
        g_corto = " ".join(t for t in re.split(r"[\s_]+", grupo) if re.search(r"\d", t)) or grupo
        nombre = f"{central.title()}" + (f" {g_corto}" if grupo and grupo != "CENTRAL" else "")
        a = agr.setdefault(nombre, {"empresa": texto(r.get("EMPRESA")).title(), "central": central.title(),
                                     "grupo": grupo, "combustible": comb, "tipo_comb": tipo_combustible(comb), "rf": rf, "inicio": ini, "final": fin,
                                     "tipo": texto(r.get("TIPO OPERACION")), "unidades": cand, "mwh": 0.0,
                                     "mw_max": 0.0, "minutos": set()})
        if ini and (a["inicio"] is None or ini < a["inicio"]):
            a["inicio"] = ini
        if fin and (a["final"] is None or fin > a["final"]):
            a["final"] = fin
        for u in cand:
            for m, mw in desp[u]["mw"].items():
                t = t0 + dt.timedelta(minutes=m)
                if mw > 0 and ini and fin and t > ini and t - dt.timedelta(minutes=30) < fin and (u, m) not in a["minutos"]:
                    a["minutos"].add((u, m))
                    a["mwh"] += mw * 0.5
                    if a["tipo_comb"] == "Diésel D2":
                        s = serie.setdefault(m, {"rf": 0.0, "otras": 0.0})
                        s["rf" if rf else "otras"] += mw
    unidades = []
    for n, a in agr.items():
        porm = {}
        for u, m in a.pop("minutos"):
            porm[m] = porm.get(m, 0) + desp[u]["mw"][m]
        a["mw_max"] = max(porm.values()) if porm else None
        a["mwh"] = round(a["mwh"], 1) if a["unidades"] and porm else None
        unidades.append({"nombre": n, **a})
    orden_c = {"Diésel D2": 0, "Residual": 1, "Gas de refinería": 2}
    unidades.sort(key=lambda u: (orden_c[u["tipo_comb"]], not u["rf"], -(u["mwh"] or 0)))
    return {"unidades": unidades, "serie": serie}


def hidro_por_central(hojas):
    """Energía del día por central hidroeléctrica (MWh, pasada y regulación) del cuadro derecho de TIPO_RECURSO."""
    filas = hojas.get("TIPO_RECURSO") or []
    for i, f in enumerate(filas[:15]):
        cab = [norm(x) for x in f]
        if "CENTRAL" in cab and any("PASADA" in c and "HIDRO" in c for c in cab):
            jc = cab.index("CENTRAL")
            je = cab.index("EMPRESA") if "EMPRESA" in cab else jc - 1
            jp = next(j for j, c in enumerate(cab) if "PASADA" in c and "HIDRO" in c)
            jr = next((j for j, c in enumerate(cab) if "REGULACION" in c and "HIDRO" in c), None)
            out, emp = {}, ""
            for g in filas[i + 1:]:
                c = texto(g[jc]) if jc < len(g) else ""
                e = texto(g[je]) if je < len(g) else ""
                if norm(e).startswith("TOTAL") or norm(c).startswith("TOTAL"):
                    break
                emp = e or emp
                if not c:
                    continue
                vp = numero(g[jp]) if jp < len(g) else None
                vr = numero(g[jr]) if jr is not None and jr < len(g) else None
                if vp is None and vr is None:
                    continue
                nombre = re.sub(r"^(M\.?C\.?H\.?|C\.?\s?H\.?|P\.?C\.?H\.?|CH)\s*", "", norm(c)).title()
                out[nombre] = {"empresa": emp.title(), "pasada": vp or 0.0, "regulacion": vr or 0.0}
            return out
    return {}


def ieod_dia(d: dt.date):
    """Anexo A del IEOD de un día exacto (o {} si no está publicado): potencia por recurso y volúmenes."""
    fecha, hojas = descargar_ieod(d, dias_atras=1, solo={"TIPO_RECURSO", "PRINCIP_VOLÚMENES", "PRINCIP_VOLUMENES",
                                                          "DESPACHO_EJECUTADO"})
    return hojas if fecha == d else {}


def volumenes_dia(hojas):
    """Volumen útil (Hm3) de los embalses con reporte diario en el IEOD: [{cuenca, embalse, prom, final}]."""
    filas = hojas.get("PRINCIP_VOLÚMENES") or hojas.get("PRINCIP_VOLUMENES") or []
    return [{"cuenca": r["cuenca"], "embalse": r["embalse"], "prom": r["prom"], "final": r["final"]}
            for r in parsear_volumenes(filas) if norm(r["unidad"]) == "HM3"]


# --------------------------------------------------------------------------- embalses (Evaluación Semanal)
CUENCAS_SEMANAL = [("Santa", (r"RIO SANTA\b(?! EULALIA)",)), ("Mantaro", (r"MANTARO",)), ("Rímac", (r"RIMAC",)),
                   ("San Gabán", (r"SAN GABAN",)), ("Chaglla", (r"CHAGLLA", r"HUALLAGA"))]


def informe_semanal_reciente():
    """(etiqueta de semana, hojas) del último Informe de Evaluación Semanal."""
    base = "Post Operación/Informes/Evaluacion Semanal/"
    url = base
    for _ in range(3):
        items = listar(url)
        archivos = [i for i in items if i.lower().endswith((".xlsx", ".xls"))]
        if archivos:
            b = bajar(archivos[0])
            return url.rstrip("/").rsplit("/", 1)[-1], (libro(b) if b else {})
        carpetas = [i for i in items if i.endswith("/")]
        if not carpetas:
            break
        url = max(carpetas, key=lambda r: [int(x) for x in re.findall(r"\d+", r.rstrip("/").rsplit("/", 1)[-1])[:1]]
                  or [0])
    return None, {}


def _bloques_semanales(hojas, hoja, prefijo, unidad):
    """Bloques 'título / años / semanas' de las hojas 5.2 y 5.4 del Informe de Evaluación Semanal."""
    filas = next((v for k, v in hojas.items() if norm(k).startswith(hoja)), None) or []
    out = []
    for i, f in enumerate(filas[:40]):
        for j, v in enumerate(f):
            t = norm(v)
            if not t.startswith(prefijo):
                continue
            anios = {}
            sig = filas[i + 1] if i + 1 < len(filas) else []
            for k in range(j + 1, min(j + 6, len(sig))):
                n = numero(sig[k])
                if n and 2000 < n < 2100:
                    anios[int(n)] = k
            if not anios:
                continue
            serie = {a: {} for a in anios}
            for g in filas[i + 2:i + 60]:
                sem = numero(g[j]) if j < len(g) else None
                if not sem or not (1 <= sem <= 53):
                    continue
                for a, k in anios.items():
                    val = numero(g[k]) if k < len(g) else None
                    if val is not None:
                        serie[a][int(sem)] = val
            cuenca = next((c for c, claves in CUENCAS_SEMANAL if any(re.search(c2, t) for c2 in claves)), None)
            out.append({"cuenca": cuenca, "titulo": texto(v), "unidad": unidad,
                        "anios": {a: s for a, s in serie.items() if s}})
    return out


def embalses_semanales(hojas):
    """Hoja 5.2: volumen útil semanal por cuenca (Hm3)."""
    return _bloques_semanales(hojas, "5.2", "VOLUMEN UTIL", "Hm3")


def caudales_semanales(hojas):
    """Hoja 5.4: caudal natural semanal (m3/s). En Mantaro vienen por tramos (se suman después)."""
    return _bloques_semanales(hojas, "5.4", "CAUDAL NATURAL", "m3/s")


# Centrales por cuenca (MW) para acompañar los gráficos de embalses
CENTRALES_CUENCA = {
    "Santa": [("CH Pariac", 4.9), ("CH Santa Cruz I-II", 12), ("CH Manta", 19.8), ("CH Cañón del Pato", 246.6),
              ("CH Quitaracsa", 112)],
    "Mantaro": [("CH Malpaso", 48.5), ("CH Pachachaca", 10), ("CH Oroya", 9.1), ("CH Canchayllo", 5.2),
                ("CH Mantaro", 905.2), ("CH Cerro del Águila", 593.3)],
    "Rímac": [("CH Huanza", 98.3), ("CH Carhuac", 20.4), ("CH Huinco", 277.9), ("CH Huanchor", 19.8),
              ("CH Matucana", 137), ("CH Callahuanca", 84.4), ("CH Moyopampa", 69.2), ("CH Huampaní", 30.6),
              ("CH HER1", 0.7)],
    "San Gabán": [("CH Tupuri", 2), ("CH El Ángel 1", 20.1), ("CH El Ángel 2", 20), ("CH El Ángel 3", 20.1),
                  ("CH San Gabán 2", 115.7), ("CH San Gabán 3", 209.3)],
    # Empresa de Generación Huallaga: en el despacho del COES solo figuran CHAGLLA y CHAGLLA GP1
    "Chaglla": [("CH Chaglla", 450.0), ("CH Chaglla GP1 (caudal ecológico)", 6.4)],
}


# --------------------------------------------------------------------------- tecnología de las unidades
DIESEL_CLAVES = ("ILO 4", "NODO ENERGETICO", "PTO BRAVO", "PUERTO BRAVO", "RECKA", "RESERVA FRIA", "RF-", "RF ", "PUERTO MALDONADO", "PUCALLPA", "NEPI", "PUERTO BRAVO",
                 "MOLLENDO", "TUMBES", "CHILINA", "TAPARACHI", "YARINACOCHA", "SAN NICOLAS", "ELOR",
                 "BELLAVISTA", "IQUITOS", "ILO 31", "DIESEL", "D2", "B5", "RESIDUAL", "MAK")
GAS_CLAVES = ("CHILCA", "KALLPA", "FENIX", "VENTANILLA", "SANTA ROSA", "LAS FLORES", "OLLEROS", "MALACAS",
              "AGUAYTIA", "INDEPENDENCIA", "TALARA", "REFINERIA", "TERMOCHILCA", "CALANA")


def combustibles_hop(hojas):
    """{central normalizada: combustible} a partir de la hoja HOP (unidades que operaron)."""
    out = {}
    for r in tabla(hojas.get("HOP", []), ["EMPRESA", "CENTRAL", "MODO DE OPERACION"]):
        c, modo = norm(r.get("CENTRAL")), norm(r.get("MODO DE OPERACION"))
        if c and modo:
            out[re.sub(r"^C\.?\s?T\.?\s*B?\.?\s*", "", c)] = modo.rsplit(" - ", 1)[-1]
    return out


def tecnologia(r, mapa_hop=None, hidro=None):
    """Hídrica / Gas natural / Diésel / Solar / Eólica / Biomasa / Carbón / Otra."""
    u, e, d, emp = norm(r.get("ubicacion")), norm(r.get("equipo")), norm(r.get("descripcion")), norm(r.get("empresa"))
    todo = " ".join((u, e, d, emp))
    comb = (mapa_hop or {}).get(u, "")
    if any(k in comb for k in ("D2", "DIESEL", "B5", "R500", "R6", "RESIDUAL")):
        return "Diésel"
    if "GAS" in comb and "BIOGAS" not in comb:
        return "Gas natural"
    if "BAGAZO" in comb or "BIOGAS" in comb:
        return "Biomasa"
    if any(k in todo for k in ("RESERVA FRIA", "RECKA")) or any(re.search(rf"\b{re.escape(k)}\b", u) for k in DIESEL_CLAVES):
        return "Diésel"
    if any(k in todo for k in ("BAGAZO", "BIOGAS", "BIOMASA", "HUAYCOLORO", "DONA CATALINA", "PARAMONGA", "ETANOL",
                               "MAPLE", "CASA GRANDE", "SAN JACINTO", "CANA BRAVA", "AGROLMOS", "LA GRINGA")):
        return "Biomasa"
    if hidro and u in hidro or re.search(r"\bC\.?H\b|HIDRO|EMBALSE|PRESA|TURBINA PELTON|RODETE", todo):
        return "Hídrica"
    if "SOLAR" in todo or "FOTOVOLT" in todo or re.match(r"^(PFV|CS)", u):
        return "Solar"
    if "EOLIC" in todo or "WTG" in todo or "AEROGENERADOR" in todo:
        return "Eólica"
    if any(k in u for k in GAS_CLAVES) or re.search(r"\bGAS\b", todo):
        return "Gas natural"
    if "CARBON" in todo or "ILO 21" in u:
        return "Carbón"
    if any(k in todo for k in ("BAGAZO", "BIOGAS", "BIOMASA", "HUAYCOLORO", "DONA CATALINA", "PARAMONGA")) \
            or re.match(r"^C\.?T\.?B\b", u):
        return "Biomasa"
    if re.match(r"^C\.?T\b", u) or re.match(r"^(TG|TV|GT|ST|MAK)", e):
        return "Otra"
    return "Hídrica" if re.match(r"^(G\d|CENTRAL)$", e) and not any(k in u for k in GAS_CLAVES) else "Otra"


def centrales_hidro(hojas):
    """Nombres normalizados de centrales hidroeléctricas listadas en TIPO_RECURSO."""
    out = set()
    for f in hojas.get("TIPO_RECURSO", []):
        for v in f:
            t = norm(v)
            m = re.match(r"^(?:C\.?\s?H\.?|PCH)\s*(.+)$", t)
            if m:
                out.add(m.group(1).strip())
    return out
