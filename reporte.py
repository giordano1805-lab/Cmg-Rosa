#!/usr/bin/env python3
"""
Reporte diario del SEIN: PDF + datos del dashboard web.

Día evaluado = día anterior a la ejecución (CMg completo e IEOD publicado).
"Programado" = intervenciones del día de la ejecución.

Uso desde el script principal:  reporte.generar(m)  donde m es el módulo "cmg santarosa.py".
"""
import calendar
import datetime as dt
import json
import sys
from pathlib import Path

import fuentes_coes as fc
import historicos as hi

SALIDA = Path("reportes")
DOCS = Path("docs")
LOGO = Path("logo.png")

AZUL = "#001a6f"
NARANJA = "#ff5716"
AMARILLO = "#ffb210"
GRIS = "#5f6368"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre",
         "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def fecha_larga(d):
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def hm(t):
    if not t:
        return ""
    if t.hour == 0 and t.minute == 0:
        return "24:00" if t.second == 0 else "00:00"
    return f"{t:%H:%M}"


def periodo(r, dia):
    """Texto de inicio–fin; muestra la fecha solo si sale del día."""
    i, f = r.get("inicio"), r.get("final")
    ti = f"{i:%d/%m} {i:%H:%M}" if i and i.date() != dia else (f"{i:%H:%M}" if i else "")
    if f and f.date() == dia + dt.timedelta(days=1) and f.hour == 0 and f.minute == 0:
        tf = "24:00"
    else:
        tf = f"{f:%d/%m} {f:%H:%M}" if f and f.date() != dia else (f"{f:%H:%M}" if f else "")
    return f"{ti}–{tf}"


# --------------------------------------------------------------------------- cálculo de indicadores CMg
def indicadores_cmg(m, hist, dia):
    mes = {t: r for t, r in hist.items()
           if (m.dia_operativo(t).year, m.dia_operativo(t).month) == (dia.year, dia.month)
           and m.dia_operativo(t) <= dia}
    diario_b, prom_mes_b, n_b = {}, {}, {}
    for b in m.BARRAS:
        por_dia = {}
        for t, r in mes.items():
            if isinstance(r.get(b), float):
                por_dia.setdefault(m.dia_operativo(t), []).append(r[b] / m.TC)
        diario_b[b] = {d: m.promedio(v) for d, v in por_dia.items()}
        prom_mes_b[b] = m.promedio([x for v in por_dia.values() for x in v])
        n_b.setdefault(b, {d: len(v) for d, v in por_dia.items()})
    diario_bl, prom_mes_bl = {}, {}
    for bl in m.BLOQUES:
        por_dia = {}
        for t, r in mes.items():
            if isinstance(r.get(m.SR), float) and m.bloque(t) == bl:
                por_dia.setdefault(m.dia_operativo(t), []).append(r[m.SR] / m.TC)
        diario_bl[bl] = {d: m.promedio(v) for d, v in por_dia.items()}
        prom_mes_bl[bl] = m.promedio([x for v in por_dia.values() for x in v])
    # día anterior al evaluado (puede ser del mes previo)
    ayer = dia - dt.timedelta(days=1)
    prev = {}
    for b in m.BARRAS:
        vals = [r[b] / m.TC for t, r in hist.items() if m.dia_operativo(t) == ayer and isinstance(r.get(b), float)]
        prev[b] = m.promedio(vals)
    n_dia = sum(1 for t in mes if m.dia_operativo(t) == dia)
    return {"mes": mes, "diario_b": diario_b, "prom_mes_b": prom_mes_b, "diario_bl": diario_bl,
            "prom_mes_bl": prom_mes_bl, "prev": prev, "n_dia": n_dia, "n_b": n_b}


def grafico_demanda(dem_areas, dia, ruta, plt):
    if not dem_areas:
        return None
    from matplotlib.ticker import MultipleLocator
    xs = [(int(r["hora"][:2]) + int(r["hora"][3:]) / 60) or 24.0 for r in dem_areas]
    orden = sorted(range(len(xs)), key=xs.__getitem__)
    xs = [xs[i] for i in orden]
    dem_areas = [dem_areas[i] for i in orden]
    fig, ax = plt.subplots(figsize=(8.5, 4.2), dpi=160)
    zonas = [("norte", "Norte", "#e9a300"), ("centro", "Centro", "#2b4fd1"), ("sur", "Sur", "#f0590f")]
    ax.stackplot(xs, [[r[z] or 0 for r in dem_areas] for z, _, _ in zonas], labels=[n for _, n, _ in zonas],
                 colors=[c for _, _, c in zonas], alpha=0.85, lw=0)
    tot = [r["sein"] or 0 for r in dem_areas]
    ax.plot(xs, tot, color="#001a6f", lw=1.2, label="SEIN")
    i = max(range(len(tot)), key=tot.__getitem__)
    ax.annotate(f"Máx {tot[i]:,.0f} MW · {dem_areas[i]['hora']}", (xs[i], tot[i]), xytext=(0, 6),
                textcoords="offset points", ha="center", fontsize=7.5, weight="bold")
    ax.axvspan(18, 23, color="#ff861d", alpha=0.08, lw=0)
    ax.set_xlim(0, 24)
    ax.set_ylim(bottom=0)
    ax.set_xticks(range(0, 25, 2), [f"{h:02d}:00" for h in range(0, 25, 2)], fontsize=7)
    ax.xaxis.set_minor_locator(MultipleLocator(0.5))
    ax.tick_params(axis="y", labelsize=7)
    ax.set_ylabel("MW", fontsize=8)
    ax.set_title(f"Demanda ejecutada por área · {dia:%d/%m/%Y}", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7.5, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.28))
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.text(0.99, 0.01, "Fuente: COES – IEOD (Anexo A)", ha="right", fontsize=6, color=GRIS)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def romanos(s):
    """'San Gaban Iii' → 'San Gaban III' (números romanos en mayúsculas tras .title())."""
    import re
    return re.sub(r"\b(ii|iii|iv|vi|vii|viii|ix|xi|xii)\b", lambda m: m.group(0).upper(), str(s),
                  flags=re.I) if s is not None else s


# --------------------------------------------------------------------------- resumen ejecutivo
DESACOPLE_MIN = 15.0      # USD/MWh entre barras para hablar de desacople (diferencia nodal por transmisión)


def resumen(ind, ieod, prog, dia, m, extra=None):
    extra = extra or {}
    b = []
    # El CMg, los bloques y la demanda ya se ven en los indicadores y gráficos: aquí solo lo que alerta.
    vals = {k.replace(" 220", ""): v.get(dia) for k, v in ind["diario_b"].items() if v.get(dia) is not None}
    if len(vals) >= 2:
        hi = max(vals, key=vals.get)
        lo = min(vals, key=vals.get)
        if vals[hi] - vals[lo] >= DESACOPLE_MIN:
            b.append(f"<b>Desacople de precios por congestión de transmisión</b>: {hi} {vals[hi]:.2f} vs. {lo} "
                     f"{vals[lo]:.2f} USD/MWh (diferencia {vals[hi] - vals[lo]:.2f} USD/MWh).")
    da = ieod.get("demanda_areas") or []
    if da:
        mx = max(da, key=lambda r: r["sein"] or 0)
        b.append(f"Máxima demanda del SEIN: <b>{mx['sein']:,.0f} MW</b> a las {mx['hora']} h.")
    rh = extra.get("hidro")
    if rh and rh["mtd"].get(rh["act"]) and rh["mtd"].get(rh["ant"]):
        m1, m0 = rh["mtd"][rh["act"]], rh["mtd"][rh["ant"]]
        b.append(f"Hidro de pasada: promedio del mes {m1:,.0f} MW vs. {m0:,.0f} MW en {rh['ant']} "
                 f"(<b>{(m1 / m0 - 1) * 100:+.0f}%</b>).")
    hc = extra.get("hidro_centrales")
    if hc and hc["centrales"]:
        baj = [c for c in hc["centrales"] if c["delta"] < 0][:4]
        if baj:
            b.append(f"Centrales hidro con mayor caída vs. {hc['ant']} (días {hc['desde']}–{hc['hasta']}): " +
                     ", ".join(f"{c['central']} {c['delta']:+,.1f} GWh"
                               + (f" ({c['var_pct']:+.0f}%)" if c["var_pct"] is not None else "") for c in baj) + ".")
    for k, nom in (("regulacion", "Hidro de embalse"), ("eolica", "Eólica")):
        rr = extra.get(k)
        if rr and rr["mtd"].get(rr["act"]) and rr["mtd"].get(rr["ant"]):
            m1, m0 = rr["mtd"][rr["act"]], rr["mtd"][rr["ant"]]
            b.append(f"{nom}: promedio del mes {m1:,.0f} MW vs. {m0:,.0f} MW en {rr['ant']} "
                     f"(<b>{(m1 / m0 - 1) * 100:+.0f}%</b>).")
    dd = extra.get("diesel")
    if dd and dd["unidades"]:
        grupos = {}
        for u in dd["unidades"]:
            k = ("D2 Reserva Fría" if u["rf"] else "D2 otras") if u["tipo_comb"] == "Diésel D2" else u["tipo_comb"]
            grupos.setdefault(k, []).append(f"{u['nombre']}" + (f" ({u['mwh']:,.0f} MWh)" if u.get("mwh") else ""))
        b.append("Térmicas con diésel, residual o gas de refinería: " +
                 "; ".join(f"{k}: {', '.join(v)}" for k, v in grupos.items()) + ".")
    ind_g = ieod.get("indisponibilidades") or []
    if ind_g:
        sin = [r for r in ind_g if not r.get("diesel")]
        dsl = [r for r in ind_g if r.get("diesel")]
        mw = sum(r["mw"] for r in sin)
        top = sorted(sin, key=lambda r: -r["mw"])[:3]
        st = extra.get("indisp_stats")
        if st:
            b.append(f"Indisponibilidad sin diésel: máximo simultáneo <b>{st['max']:,.0f} MW</b> ({st['hora_max']} h), "
                     f"promedio {st['prom']:,.0f} MW ({st['mwh']:,.0f} MWh de capacidad indisponible); forzado "
                     f"promedio {st['forzado']['prom']:,.0f} MW. Mayores: " +
                     ", ".join(f"{r['ubicacion'].title()} {r['equipo']} ({r['mw']:.0f} MW)" for r in top) + ".")
    ev = ieod.get("eventos") or []
    ev_l = fc.filtrar_lineas_220(ev)
    if ev:
        b.append(f"Eventos: {len(ev)} registrados ({sum(1 for e in ev if e['tipo'].upper() == 'FALLA')} fallas)"
                 + (f"; líneas ≥220 kV afectadas: {', '.join(lin(e['equipo']) for e in ev_l)}." if ev_l else "."))
    cu = [c for c in extra.get("cuencas") or [] if c["var_pct"] is not None and not c.get("solo_diario")]
    if cu:
        b.append("Embalses vs. año anterior (misma semana): " +
                 ", ".join(f"{c['cuenca']} {c['actual']:,.0f} Hm3 ({c['var_pct']:+.0f}%)" for c in cu) + ".")
    ch = next((c["diario"] for c in extra.get("cuencas") or [] if c.get("solo_diario")), None)
    if ch and ch.get("total") is not None:
        b.append(f"Embalse Chaglla (promedio del {dt.date.fromisoformat(ch['fecha']):%d/%m}): {ch['total']:,.2f} Hm3"
                 + (f" ({ch['var_pct']:+.0f}% vs. año anterior)." if ch.get("var_pct") is not None else "."))
    if prog is not None:
        g = [r for r in fc.solo_generacion(prog) if r["mw"] > 0 and not r.get("diesel")]
        lp = fc.filtrar_lineas_220(prog)
        sp = fc.perfil_indisponible(g, dia + dt.timedelta(days=1)) if g else {"max": 0, "hora_max": "", "prom": 0}
        b.append(f"Programación de hoy: máximo simultáneo <b>{sp['max']:,.0f} MW</b> sin diésel ({sp['hora_max']} h), "
                 f"promedio {sp['prom']:,.0f} MW, en {len(g)} intervenciones; {len({r['equipo'] for r in lp})} líneas "
                 f"≥220 kV intervenidas.")
    return [romanos(x) for x in b]


# --------------------------------------------------------------------------- PDF
# --------------------------------------------------------------------------- resumen en 3 bloques y alertas
import os as _os

UMBRALES = {      # configurables con variables de entorno del workflow (mismo nombre en mayúsculas)
    "cmg_alto": float(_os.getenv("CMG_ALTO") or 150),            # USD/MWh, CMg diario de Santa Rosa
    "cmg_bajo": float(_os.getenv("CMG_BAJO") or 20),
    "desacople": float(_os.getenv("DESACOPLE") or DESACOPLE_MIN),  # USD/MWh entre barras
    "forzado": float(_os.getenv("FORZADO_MW") or 300),           # MW forzados simultáneos
    "huanchor_caida": float(_os.getenv("HUANCHOR_CAIDA") or 20),  # % de caída diaria vs año anterior
    "caudal_caida": float(_os.getenv("CAUDAL_CAIDA") or 20),      # % caudal natural Rímac vs año anterior
}


def _pct(a, b):
    return (a / b - 1) * 100 if a is not None and b else None


def _unidad(r):
    u = r["ubicacion"].title()
    return u if fc.norm(r.get("equipo")) in ("CENTRAL", "") else f"{u} {r['equipo']}"


def _unicos(regs):
    vistos, out = set(), []
    for r in regs:
        k = (fc.norm(r["ubicacion"]), fc.norm(r["equipo"]))
        if k not in vistos:
            vistos.add(k)
            out.append(r)
    return out


def resumen_bloques(ind, ieod, prog, dia, hoy, m, extra):
    """Resumen ejecutivo: qué pasó, qué implica para Huanchor y qué vigilar (máx. 4 puntos por bloque)."""
    paso, hu_b, vig = [], [], []
    sr, sr_m = ind["diario_b"][m.SR].get(dia), ind["prom_mes_b"][m.SR]
    if sr is not None and sr_m:
        paso.append(f"CMg {m.SR}: <b>{sr:.2f} USD/MWh</b>, {abs(_pct(sr, sr_m)):.0f}% "
                    f"{'por debajo' if sr < sr_m else 'por encima'} del promedio del mes ({sr_m:.2f}).")
    vals = {k: v.get(dia) for k, v in ind["diario_b"].items() if v.get(dia) is not None}
    if len(vals) >= 2:
        a, b = max(vals, key=vals.get), min(vals, key=vals.get)
        if vals[a] - vals[b] >= UMBRALES["desacople"]:
            paso.append(f"<b>Desacople por transmisión</b>: {a} {vals[a]:.2f} vs {b} {vals[b]:.2f} USD/MWh "
                        f"({vals[a] - vals[b]:.2f}).")
    rh = extra.get("hidro")
    if rh and rh["mtd"].get(rh["act"]) and rh["mtd"].get(rh["ant"]):
        paso.append(f"Hidro de pasada del mes {rh['mtd'][rh['act']]:,.0f} MW medios, "
                    f"{_pct(rh['mtd'][rh['act']], rh['mtd'][rh['ant']]):+.0f}% vs {rh['ant']}.")
    st = extra.get("indisp_stats")
    if st:
        paso.append(f"Indisponibilidad sin diésel: máximo simultáneo {st['max']:,.0f} MW, forzado hasta "
                    f"{st['forzado']['max']:,.0f} MW.")
    hu = extra.get("huanchor")
    if hu:
        if hu.get("dia_mwh") is not None:
            v = _pct(hu["dia_mwh"], hu.get("dia_mwh_ant"))
            hu_b.append(f"Huanchor generó <b>{hu['dia_mwh']:,.1f} MWh</b>" +
                        (f" ({v:+.0f}% vs mismo día {hu['ant']})" if v is not None else "") +
                        (f"; en el mes {hu['mes_mwh']:,.0f} MWh ({_pct(hu['mes_mwh'], hu['mes_mwh_ant']):+.1f}%)."
                         if hu.get("mes_mwh_ant") else "."))
        d = hu["diario"][-1] if hu["diario"] else {}
        if d.get("capturado") is not None:
            hu_b.append(f"Precio capturado del día {d['capturado']:.2f} USD/MWh (barra Huanchor 50 kV; Matucana solo si falta); "
                        f"ingreso spot referencial {d['ingreso']:,.0f} USD" +
                        (f", cobertura {d['cobertura']:.0f}% de la energía." if d.get("cobertura") is not None and d["cobertura"] < 100 else "."))
        if hu.get("capturado_mes") is not None:
            hu_b.append(f"{hu['titulo_precio']} del mes: {hu['capturado_mes']:.2f} USD/MWh "
                        f"(Huanchor {hu['pct_h'] or 0:.0f}% · Matucana {hu['pct_m'] or 0:.0f}% de la energía; "
                        f"cobertura {hu['cobertura'] or 0:.0f}%). Promedio de la misma referencia: {hu['cmg_ref_mes']:.2f}.")
        elif hu.get("energia_perfil"):
            hu_b.append("Precio capturado de Huanchor: sin dato disponible (no se publicó CMg en Huanchor 50 kV ni en Matucana).")
    rim = next((c for c in extra.get("cuencas") or [] if c["cuenca"] == "Rímac"), None)
    if rim:
        q = rim.get("caudal") or {}
        hu_b.append("Cuenca del Rímac (semana): " +
                    (f"caudal natural {q['actual']:,.1f} m3/s ({q['var_pct']:+.0f}%), " if q.get("var_pct") is not None else "") +
                    (f"volumen {rim['actual']:,.0f} Hm3 ({rim['var_pct']:+.0f}%) vs año anterior."
                     if rim.get("var_pct") is not None else "."))
    if prog is not None:
        g = [r for r in fc.solo_generacion(prog) if r["mw"] > 0 and not r.get("diesel")]
        if g:
            sp = fc.perfil_indisponible(g, hoy)
            top = _unicos(sorted(g, key=lambda r: -r["mw"]))[:3]
            vig.append(f"Hoy: hasta <b>{sp['max']:,.0f} MW</b> fuera por programa ({sp['hora_max']} h). Mayores: " +
                       ", ".join(f"{_unidad(r)} ({r['mw']:.0f} MW)" for r in top) + ".")
        own = [r for r in prog if "HUANCHOR" in fc.norm(r.get("ubicacion"))]
        if own:
            vig.append("Huanchor tiene intervenciones programadas hoy: " +
                       "; ".join(f"{r['equipo']} {r['descripcion'][:60]}" for r in own) + ".")
    pm = extra.get("prog_mensual") or {}
    prox = []
    for r in pm.get("regs") or []:
        try:
            i = dt.datetime.fromisoformat(r["inicio"]).date()
        except Exception:
            continue
        if hoy < i <= hoy + dt.timedelta(days=7) and not r.get("diesel") and r["mw"] >= 20:
            prox.append((i, r))
    if prox:
        prox.sort(key=lambda x: (-x[1]["mw"], x[0]))
        vistos, sel = set(), []
        for i, r in prox:
            k = (r["ubicacion"], r["equipo"])
            if k not in vistos:
                vistos.add(k)
                sel.append((i, r))
        vig.append("Próximos 7 días (programa mensual): " + ", ".join(
            f"{_unidad(r)} {r['mw']:.0f} MW desde {i:%d/%m}" for i, r in sel[:4]) + ".")
    cg = extra.get("congestion") or {}
    if cg.get("registros"):
        vig.append(f"Hubo {len(cg['registros'])} congestiones de transmisión el día evaluado (ver Transmisión).")
    ev_l = fc.filtrar_lineas_220([e for e in ieod.get("eventos") or [] if fc.norm(e.get("tipo")) == "FALLA"])
    if ev_l:
        vig.append("Fallas en líneas ≥220 kV: " + ", ".join(lin(x) for x in sorted({e['equipo'] for e in ev_l})) + ".")
    f = lambda xs: [romanos(x) for x in xs][:4]
    return {"paso": f(paso), "huanchor": f(hu_b), "vigilar": f(vig)}


MESES_TXT = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre", "octubre",
             "noviembre", "diciembre"]


def _fecha_txt(d):
    return f"{d.day} de {MESES_TXT[d.month - 1]}"


def _hora(r, dia):
    i, f = r.get("inicio"), r.get("final")
    if isinstance(i, str):
        i = dt.datetime.fromisoformat(i)
    if isinstance(f, str):
        f = dt.datetime.fromisoformat(f)
    if not i:
        return ""
    fin = "24:00" if f and f.date() > dia and f.hour == 0 and f.minute == 0 else (f"{f:%H:%M}" if f else "")
    return f"{max(i, dt.datetime(dia.year, dia.month, dia.day)):%H:%M}–{fin}"


def _corto(t, n=70):
    t = " ".join(str(t or "").split()).lower()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


TRAMOS = {}       # código de línea → "A – B" (se llena en generar() y se acumula en data/tramos_lineas.json)


def lin(cod):
    """'L-2051' → 'L-2051 (Campo Armiño – Cotaruse)' si se conoce el tramo."""
    t = TRAMOS.get(fc.codigo_linea(cod) or cod)
    return f"{cod} ({t})" if t else cod


def _max_dem(rd):
    """Máxima demanda del día y del mes vs año anterior (Portal COES, misma fuente en ambos años)."""
    if not rd or not rd.get("max_dia"):
        return {}
    a, b = rd["act"], rd["ant"]
    d1, d0 = rd["max_dia"].get(a), rd["max_dia"].get(b)
    m1, m0 = (rd.get("max_mes") or {}).get(a), (rd.get("max_mes") or {}).get(b)
    return {"portal": d1, "portal_ant": d0, "delta_dia": round(d1 - d0, 1) if d1 and d0 else None,
            "mes": m1, "mes_ant": m0, "delta_mes": round(m1["mw"] - m0["mw"], 1) if m1 and m0 else None}


def resumen_tablero(ind, ieod, prog, dia, hoy, m, extra):
    """Resumen para leer en 30 segundos: conclusión, 4 indicadores, 3 mensajes y hasta 3 asuntos a vigilar.
    Solo hechos medidos; no se atribuyen causas."""
    out = {"dia": dia.isoformat(), "hoy": hoy.isoformat()}
    sr, sr_p, sr_m = ind["diario_b"][m.SR].get(dia), ind["prev"].get(m.SR), ind["prom_mes_b"][m.SR]
    v_d, v_m = _pct(sr, sr_p), _pct(sr, sr_m)
    hc, rh = extra.get("hidro_centrales"), extra.get("hidro")
    if hc and hc.get("total_ant"):
        hid_v, hid_txt = _pct(hc["total_act"], hc["total_ant"]), "generación hidroeléctrica acumulada del mes"
    elif rh and rh["mtd"].get(rh["ant"]):
        hid_v, hid_txt = _pct(rh["mtd"][rh["act"]], rh["mtd"][rh["ant"]]), "hidro de pasada del mes"
    else:
        hid_v, hid_txt = None, ""
    g = [r for r in fc.solo_generacion(prog or []) if r["mw"] > 0 and not r.get("diesel")]
    sp = fc.perfil_indisponible(g, hoy) if g else None
    principal = max(g, key=lambda r: r["mw"]) if g else None
    # 1. conclusión
    partes = []
    if sr is not None:
        partes.append(f"El {_fecha_txt(dia)}, {m.SR.replace(' 220', '')} promedió {sr:.2f} USD/MWh" +
                      (f", {abs(v_d):.1f}% {'menos' if v_d < 0 else 'más'} que el día anterior" if v_d is not None else "") + ".")
    if hid_v is not None:
        partes.append(f"La {hid_txt} va {hid_v:+.0f}% frente al mismo período de {dia.year - 1}.")
    if sp and sp["max"] > 0:
        partes.append(f"Para el {_fecha_txt(hoy)} se programan hasta {sp['max']:,.0f} MW indisponibles a la vez "
                      f"(sin diésel, {sp['hora_max']} h).")
    out["conclusion"] = " ".join(partes)
    # 2. indicadores
    da = ieod.get("demanda_areas") or []
    mx = max(da, key=lambda r: r["sein"] or 0) if da else None
    st = extra.get("indisp_stats")
    out["kpis"] = {
        "precio": {"valor": sr, "var_dia": v_d, "var_mes": v_m, "prom_mes": sr_m, "barra": m.SR,
                   "otras": {b: ind["diario_b"][b].get(dia) for b in m.BARRAS if b != m.SR}},
        "demanda": {"valor": mx["sein"] if mx else None, "hora": mx["hora"] if mx else None,
                    "var_mes": (_pct(extra["demanda"]["mtd_gwh"][extra["demanda"]["act"]],
                                     extra["demanda"]["mtd_gwh"][extra["demanda"]["ant"]])
                                if extra.get("demanda") and extra["demanda"]["mtd_gwh"].get(extra["demanda"]["ant"]) else None),
                    "ant": extra["demanda"]["ant"] if extra.get("demanda") else None,
                    **_max_dem(extra.get("demanda"))},
        "indisp": {"max": st["max"], "hora": st["hora_max"], "prog": st["programado"]["prom"],
                   "forz": st["forzado"]["prom"], "forz_max": st["forzado"]["max"]} if st else None,
        "proxima": {"fecha": hoy.isoformat(), "max": sp["max"] if sp else None, "hora": sp["hora_max"] if sp else None,
                    "principal": (f"{_unidad(principal)} · {principal['mw']:.0f} MW · {_hora(principal, hoy)}"
                                  if principal else None)},
    }
    # 3. lo que debes saber (dato + significado)
    saber = []
    if sr is not None:
        saber.append({"tema": "Precio", "seccion": "precios", "texto":
                      f"{m.SR.replace(' 220', '')} {sr:.2f} USD/MWh: " +
                      (f"{v_d:+.1f}% frente a ayer" if v_d is not None else "") +
                      (f" y {abs(v_m):.0f}% {'bajo' if v_m < 0 else 'sobre'} el promedio del mes ({sr_m:.2f})."
                       if v_m is not None else ".")})
    rd = extra.get("demanda")
    if rd and rd["mtd_gwh"].get(rd["ant"]):
        a1, a0 = rd["mtd_gwh"][rd["act"]], rd["mtd_gwh"][rd["ant"]]
        t = f"Energía del mes {a1:,.0f} GWh, {_pct(a1, a0):+.1f}% frente a los mismos {rd['dias']} días de {rd['ant']}"
        md = _max_dem(rd)
        if md.get("delta_dia") is not None:
            t += (f"; máxima del {_fecha_txt(dia)} {md['portal']:,.0f} MW, {md['delta_dia']:+,.0f} MW frente al mismo día "
                  f"de {rd['ant']}")
        elif mx:
            t += f"; máxima del {_fecha_txt(dia)} {mx['sein']:,.0f} MW a las {mx['hora']} h"
        if md.get("delta_mes") is not None:
            t += f". Máxima del mes {md['mes']['mw']:,.0f} MW ({md['delta_mes']:+,.0f} MW vs {rd['ant']})"
        saber.append({"tema": "Demanda", "seccion": "oferta", "texto": t + "."})
    if hid_v is not None:
        txt = f"La {hid_txt} va {hid_v:+.0f}% frente al mismo período de {dia.year - 1}"
        if hc and hc.get("centrales"):
            baj = [c for c in hc["centrales"] if c["delta"] < 0][:2]
            if baj:
                txt += "; las mayores caídas: " + ", ".join(f"{c['central']} ({c['delta']:+.1f} GWh)" for c in baj)
        saber.append({"tema": "Oferta hídrica", "seccion": "oferta", "texto": txt + "."})
    eo = extra.get("eolica")
    if eo and eo["mtd"].get(eo["act"]) and eo["mtd"].get(eo["ant"]):
        e1, e0 = eo["mtd"][eo["act"]], eo["mtd"][eo["ant"]]
        hoy_e = (eo["diario"].get(eo["act"]) or {}).get(dia.day)
        saber.append({"tema": "Eólica", "seccion": "oferta", "texto":
                      f"Promedio del mes {e1:,.0f} MW, {_pct(e1, e0):+.0f}% frente a {eo['ant']}"
                      + (f"; el {_fecha_txt(dia)} promedió {hoy_e:,.0f} MW" if hoy_e is not None else "") + "."})
    oper = None
    vals = {k: v.get(dia) for k, v in ind["diario_b"].items() if v.get(dia) is not None}
    cg = (extra.get("congestion") or {}).get("registros") or []
    ev_f = fc.filtrar_lineas_220([e for e in ieod.get("eventos") or [] if fc.norm(e.get("tipo")) == "FALLA"])
    if len(vals) >= 2 and max(vals.values()) - min(vals.values()) >= UMBRALES["desacople"]:
        a, b = max(vals, key=vals.get), min(vals, key=vals.get)
        oper = {"tema": "Operación", "seccion": "trans", "texto":
                f"Desacople entre {a} y {b}: {vals[a] - vals[b]:.2f} USD/MWh de diferencia; revisar transmisión."}
    elif cg:
        oper = {"tema": "Operación", "seccion": "trans",
                "texto": f"Se registraron {len(cg)} congestiones de transmisión; pueden separar los precios entre barras."}
    elif st and st["forzado"]["max"] >= UMBRALES["forzado"]:
        oper = {"tema": "Operación", "seccion": "indisp",
                "texto": f"Indisponibilidad forzada de hasta {st['forzado']['max']:,.0f} MW simultáneos."}
    elif ev_f:
        oper = {"tema": "Operación", "seccion": "trans", "texto":
                f"Falla en líneas ≥220 kV: {', '.join(lin(x) for x in sorted({e['equipo'] for e in ev_f}))}; sin desacople relevante de precios."}
    elif st:
        oper = {"tema": "Operación", "seccion": "indisp", "texto":
                f"Hasta {st['max']:,.0f} MW fuera de servicio a la vez ({st['hora_max']} h), "
                f"de los cuales {st['forzado']['max']:,.0f} MW forzados."}
    if oper:
        saber.append(oper)
    out["saber"] = [{**x, "texto": romanos(x["texto"])} for x in saber[:5]]
    # 4. qué vigilar (máx. 3, por relevancia)
    vig = []
    for r in _unicos(sorted(g, key=lambda r: -r["mw"]))[:2]:
        vig.append({"texto": f"{_unidad(r)} fuera de servicio ({r['mw']:.0f} MW): {_corto(r['descripcion'])}",
                    "horario": _hora(r, hoy), "seccion": "prog", "peso": r["mw"]})
    own = [r for r in prog or [] if "HUANCHOR" in fc.norm(r.get("ubicacion"))]
    for r in own[:1]:
        vig.append({"texto": f"Intervención en Huanchor {r['equipo']}: {_corto(r['descripcion'])}",
                    "horario": _hora(r, hoy), "seccion": "huanchor", "peso": 1e6})
    lp = fc.filtrar_lineas_220(prog or [])
    if lp:
        r = max(lp, key=lambda r: r.get("kv") or 0)
        vig.append({"texto": f"{len({x['equipo'] for x in lp})} líneas ≥220 kV intervenidas; la de mayor tensión: "
                             f"{lin(r['equipo'])}", "horario": _hora(r, hoy), "seccion": "prog",
                    "peso": 50})
    pm = (extra.get("prog_mensual") or {}).get("regs") or []
    prox = sorted([r for r in pm if not r.get("diesel") and r["mw"] >= 50
                   and hoy < dt.datetime.fromisoformat(r["inicio"]).date() <= hoy + dt.timedelta(days=7)],
                  key=lambda r: -r["mw"])
    if prox:
        r = prox[0]
        vig.append({"texto": f"Desde el {_fecha_txt(dt.datetime.fromisoformat(r['inicio']).date())}: "
                             f"{_unidad(r)} {r['mw']:.0f} MW en mantenimiento", "horario": "", "seccion": "mes",
                    "peso": r["mw"] * 0.4})
    vig.sort(key=lambda x: -x["peso"])
    out["vigilar"] = [{k: romanos(v) if isinstance(v, str) else v for k, v in x.items() if k != "peso"} for x in vig[:3]]
    return out


def alertas(ind, ieod, dia_ieod, prog, dia, m, extra):
    """Alertas explicables: nivel, título, qué la activó y dónde ver el detalle."""
    out, U = [], UMBRALES
    sr = ind["diario_b"][m.SR].get(dia)
    if sr is not None and sr >= U["cmg_alto"]:
        out.append({"nivel": "alta", "titulo": "CMg alto", "seccion": "precios",
                    "motivo": f"CMg {m.SR} del día {sr:.2f} USD/MWh ≥ umbral {U['cmg_alto']:.0f}."})
    if sr is not None and sr <= U["cmg_bajo"]:
        out.append({"nivel": "media", "titulo": "CMg bajo", "seccion": "precios",
                    "motivo": f"CMg {m.SR} del día {sr:.2f} USD/MWh ≤ umbral {U['cmg_bajo']:.0f}."})
    vals = {k: v.get(dia) for k, v in ind["diario_b"].items() if v.get(dia) is not None}
    if len(vals) >= 2 and max(vals.values()) - min(vals.values()) >= U["desacople"]:
        a, b = max(vals, key=vals.get), min(vals, key=vals.get)
        out.append({"nivel": "alta", "titulo": "Desacople entre barras", "seccion": "precios",
                    "motivo": f"{a} − {b} = {vals[a] - vals[b]:.2f} USD/MWh ≥ {U['desacople']:.0f}."})
    st = extra.get("indisp_stats")
    if st and st["forzado"]["max"] >= U["forzado"]:
        out.append({"nivel": "alta", "titulo": "Indisponibilidad forzada", "seccion": "indisp",
                    "motivo": f"Forzado simultáneo {st['forzado']['max']:,.0f} MW ≥ {U['forzado']:.0f} MW."})
    hu = extra.get("huanchor") or {}
    v = _pct(hu.get("dia_mwh"), hu.get("dia_mwh_ant"))
    if v is not None and v <= -U["huanchor_caida"]:
        out.append({"nivel": "media", "titulo": "Menor producción de Huanchor", "seccion": "huanchor",
                    "motivo": f"{hu['dia_mwh']:,.1f} MWh, {v:+.0f}% vs mismo día {hu['ant']} (umbral −{U['huanchor_caida']:.0f}%)."})
    rim = next((c for c in extra.get("cuencas") or [] if c["cuenca"] == "Rímac"), None)
    q = (rim or {}).get("caudal") or {}
    if q.get("var_pct") is not None and q["var_pct"] <= -U["caudal_caida"]:
        out.append({"nivel": "media", "titulo": "Caudal del Rímac bajo", "seccion": "embalses",
                    "motivo": f"Caudal natural semana {q['semana']}: {q['actual']:,.1f} m3/s, {q['var_pct']:+.0f}% vs año anterior."})
    if dia_ieod != dia:
        out.append({"nivel": "info", "titulo": "IEOD pendiente", "seccion": "oferta",
                    "motivo": f"El IEOD del {dia:%d/%m} aún no está publicado" +
                              (f"; se usa el del {dia_ieod:%d/%m}." if dia_ieod else ".")})
    if prog is None:
        out.append({"nivel": "info", "titulo": "Programa diario pendiente", "seccion": "prog",
                    "motivo": "El COES aún no publica el Programa Diario de Intervenciones de hoy."})
    if ind.get("n_dia", 48) < 48:
        out.append({"nivel": "info", "titulo": "CMg incompleto", "seccion": "precios",
                    "motivo": f"Solo {ind['n_dia']} de 48 intervalos del día tienen CMg publicado."})
    return out


def construir_pdf(ruta, dia, hoy, ind, ieod, dia_ieod, prog, graficos, bullets, m, extra=None):
    extra = extra or {}
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (CondPageBreak, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    azul = colors.HexColor(AZUL)
    st = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=st["Heading1"], fontSize=13, textColor=azul, spaceBefore=8, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=st["Heading2"], fontSize=10.5, textColor=azul, spaceBefore=6, spaceAfter=4)
    txt = ParagraphStyle("t", parent=st["BodyText"], fontSize=8.5, leading=11)
    bul = ParagraphStyle("b", parent=txt, leftIndent=10, bulletIndent=2, spaceAfter=2)
    cel = ParagraphStyle("c", parent=txt, fontSize=7, leading=8.4, alignment=TA_LEFT)
    nota = ParagraphStyle("n", parent=txt, fontSize=7, textColor=colors.HexColor(GRIS))
    ancho = A4[0] - 3 * cm

    def P(t, s=cel):
        return Paragraph(str(t), s)

    def tabla(cab, filas, anchos, max_filas=None, vacio="Sin registros."):
        if not filas:
            return P(vacio, nota)
        if max_filas and len(filas) > max_filas:
            filas = filas[:max_filas] + [["…"] + [""] * (len(cab) - 1)]
        t = Table([[P(f"<b>{c}</b>") for c in cab]] + [[P(romanos(x)) for x in f] for f in filas],
                  colWidths=[a * ancho for a in anchos], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e9f2")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, azul),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fb")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return t

    def img(p, alto_cm):
        if not p or not Path(p).exists():
            return P("Gráfico no disponible.", nota)
        from PIL import Image as PI
        w, h = PI.open(p).size
        alto = alto_cm * cm
        return Image(str(p), width=min(ancho, alto * w / h), height=min(alto, ancho * h / w))

    def encabezado(canvas, doc):
        canvas.saveState()
        alto_banda = 1.9 * cm
        y0 = A4[1] - alto_banda
        canvas.setFillColor(colors.white)
        canvas.rect(0, y0, A4[0], alto_banda, fill=1, stroke=0)
        x = 1.5 * cm
        if LOGO.exists():
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(str(LOGO))
            w, h = ir.getSize()
            alto = 1.05 * cm
            canvas.drawImage(ir, x, y0 + 0.45 * cm, width=alto * w / h, height=alto, mask="auto")
        canvas.setFillColor(azul)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawRightString(A4[0] - 1.5 * cm, y0 + 1.05 * cm, "Reporte Diario del SEIN")
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor(GRIS))
        canvas.drawRightString(A4[0] - 1.5 * cm, y0 + 0.55 * cm, f"Día evaluado: {fecha_larga(dia)}")
        # franja con los colores de la marca (naranja -> amarillo)
        n = 60
        c1, c2 = colors.HexColor(NARANJA), colors.HexColor(AMARILLO)
        for k in range(n):
            t = k / (n - 1)
            canvas.setFillColorRGB(c1.red + (c2.red - c1.red) * t, c1.green + (c2.green - c1.green) * t,
                                   c1.blue + (c2.blue - c1.blue) * t)
            canvas.rect(A4[0] * k / n, y0 - 0.12 * cm, A4[0] / n + 1, 0.12 * cm, fill=1, stroke=0)
        canvas.setStrokeColor(azul)
        canvas.setLineWidth(0.6)
        canvas.line(1.5 * cm, 1.15 * cm, A4[0] - 1.5 * cm, 1.15 * cm)
        canvas.setFillColor(colors.HexColor(GRIS))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(1.5 * cm, 0.75 * cm, "Fuente: COES SINAC – información pública (CMg tiempo real preliminar,"
                                               " IEOD, Programa Diario de Intervenciones). Elaboración: Área Comercial.")
        canvas.drawRightString(A4[0] - 1.5 * cm, 0.75 * cm, f"Página {doc.page}")
        canvas.restoreState()

    el = []
    tb = extra.get("tablero")
    bl = extra.get("bloques") or {}
    if tb:
        el.append(Paragraph(f"Resumen · {_fecha_txt(dia)} {dia.year}", h1))
        el.append(Paragraph(f"<b>{tb['conclusion']}</b>", ParagraphStyle("concl", parent=txt, fontSize=10.5,
                                                                          leading=14, spaceAfter=6)))
        k = tb["kpis"]
        kp = ParagraphStyle("kpr", parent=txt, leading=16)
        cel = lambda t, v, sub: P(f"<font size=7.5 color='{GRIS}'>{t}</font><br/><font size=14 color='{AZUL}'><b>{v}</b>"
                                  f"</font><br/><font size=7 color='{GRIS}'>{sub}</font>", kp)
        pr, de, ix, px = k["precio"], k["demanda"], k["indisp"], k["proxima"]
        fila = [cel("Precio de referencia", f"{pr['valor']:.2f} USD/MWh" if pr["valor"] is not None else "–",
                    f"{pr['barra']} · {pr['var_dia']:+.1f}% diario" if pr["var_dia"] is not None else pr["barra"]),
                cel("Demanda máxima", f"{(de.get('portal') or de['valor']):,.0f} MW" if (de.get('portal') or de["valor"]) else "–",
                    (f"pico a las {de['hora']} h" if de["hora"] else "") +
                    (f" · {de['delta_dia']:+,.0f} MW vs {de['ant']}" if de.get("delta_dia") is not None else "") +
                    (f" · mes {de['var_mes']:+.1f}% vs {de['ant']}" if de.get("var_mes") is not None else "")),
                cel("Indisponibilidad", f"{ix['max']:,.0f} MW" if ix else "–",
                    f"máx. simultáneo · prog. {ix['prog']:,.0f} / forz. {ix['forz']:,.0f} MW prom." if ix else ""),
                cel(f"Próxima jornada · {_fecha_txt(hoy)}", f"{px['max']:,.0f} MW" if px["max"] else "–",
                    (px["principal"] or "sin restricciones programadas")[:60])]
        t = Table([fila], colWidths=[ancho / 4] * 4)
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d9dce6")),
                               ("LINEBEFORE", (1, 0), (-1, 0), 0.4, colors.HexColor("#d9dce6")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        el.append(t)
        el.append(Paragraph("Lo que debes saber", h2))
        for x in tb["saber"]:
            el.append(Paragraph(f"<b>{x['tema']}.</b> {x['texto']}", bul, bulletText="•"))
        if tb["vigilar"]:
            el.append(Paragraph(f"Qué vigilar · {_fecha_txt(hoy)}", h2))
            for i, x in enumerate(tb["vigilar"], 1):
                el.append(Paragraph(f"<b>{i}.</b> {x['texto']}" + (f" <font color='{GRIS}'>({x['horario']})</font>"
                                                                   if x["horario"] else ""), bul))
        for a in extra.get("alertas") or []:
            el.append(Paragraph(f"<font color='{'#c5221f' if a['nivel'] == 'alta' else GRIS}'><b>⚑ {a['titulo']}:</b></font> "
                                f"{a['motivo']}", bul))
        if bl.get("huanchor"):
            el.append(Paragraph("Huanchor", h2))
            for t_ in bl["huanchor"]:
                el.append(Paragraph(t_, bul, bulletText="•"))
    else:
        el.append(Paragraph("Resumen ejecutivo", h1))
        for t_ in bullets:
            el.append(Paragraph(t_, bul, bulletText="•"))
    el.append(Spacer(1, 6))

    # KPIs de precios
    el.append(Paragraph("Costos marginales (USD/MWh, TC {:.2f})".format(m.TC), h2))
    filas = []
    for b in m.BARRAS:
        d = ind["diario_b"][b].get(dia)
        p = ind["prev"].get(b)
        filas.append([b, f"{d:.2f}" if d is not None else "–", f"{p:.2f}" if p is not None else "–",
                      f"{(d / p - 1) * 100:+.1f}%" if d and p else "–",
                      f"{ind['prom_mes_b'][b]:.2f}" if ind["prom_mes_b"][b] is not None else "–"])
    el.append(tabla(["Barra", f"Día {dia:%d/%m}", "Día anterior", "Variación", "Promedio mes"], filas,
                    [0.32, 0.17, 0.17, 0.17, 0.17]))
    el.append(Spacer(1, 4))
    filas = [[bl, f"{ind['diario_bl'][bl].get(dia):.2f}" if ind['diario_bl'][bl].get(dia) is not None else "–",
              f"{ind['prom_mes_bl'][bl]:.2f}" if ind['prom_mes_bl'][bl] is not None else "–"]
             for bl in m.BLOQUES]
    el.append(tabla(["Santa Rosa 220 kV · bloque", f"Día {dia:%d/%m}", "Promedio mes"], filas, [0.5, 0.25, 0.25]))
    el.append(Spacer(1, 4))
    el.append(img(graficos.get("barras"), 8.2))
    el.append(PageBreak())

    el.append(Paragraph("Precios: detalle", h1))
    el.append(img(graficos.get("30min"), 11.5))
    el.append(img(graficos.get("bloques"), 9))
    el.append(PageBreak())

    el.append(Paragraph("Oferta y demanda", h1))
    el.append(img(graficos.get("generacion"), 11))
    el.append(img(graficos.get("demanda"), 7.5))
    el.append(PageBreak())
    dd = extra.get("diesel")
    if dd and dd["unidades"]:
        el.append(Paragraph(f"Térmicas con diésel, residual o gas de refinería <font size=8 color='{GRIS}'>"
                            f"(IEOD del {dia_ieod:%d/%m/%Y}: HOP y despacho ejecutado)</font>", h2))
        el.append(tabla(["Central / grupo", "Empresa", "Clasificación", "Combustible", "Horario", "MW máx.", "MWh",
                         "Tipo de operación"],
                        [[u["nombre"], u["empresa"], ("Reserva Fría" if u["rf"] else "Otra") if u["tipo_comb"] == "Diésel D2" else "–",
                          f"{u['tipo_comb']} ({u['combustible']})",
                          f"{u['inicio']:%H:%M}–{u['final']:%H:%M}" if u["inicio"] and u["final"] else "",
                          f"{u['mw_max']:,.1f}" if u.get("mw_max") else "–", f"{u['mwh']:,.0f}" if u.get("mwh") else "–",
                          u["tipo"].capitalize()] for u in dd["unidades"]],
                        [0.15, 0.2, 0.12, 0.1, 0.1, 0.07, 0.07, 0.19]))
        el.append(Spacer(1, 6))
    el.append(Paragraph("Demanda vs. año anterior", h1))
    el.append(img(graficos.get("dem_mensual"), 7.6))
    el.append(img(graficos.get("dem_acum"), 6.6))
    el.append(PageBreak())
    el.append(Paragraph("Hidro de pasada, hidro de embalse y eólica vs. año anterior", h1))
    for k in ("hidro", "regulacion", "eolica"):
        el.append(img(graficos.get(k), 7.3))
    el.append(PageBreak())
    hc = extra.get("hidro_centrales")
    if hc and hc["centrales"]:
        el.append(Paragraph(f"Centrales hidroeléctricas: producción del mes vs. {hc['ant']} "
                            f"<font size=8 color='{GRIS}'>(días {hc['desde']}–{hc['hasta']} de ambos años, IEOD)</font>", h1))
        filas = [[c["central"], c["empresa"], c["tipo"], f"{c['act']:,.2f}", f"{c['ant']:,.2f}",
                  (f"<font color='#c5221f'>{c['delta']:+,.2f}</font>" if c["delta"] < 0 else f"{c['delta']:+,.2f}"),
                  f"{c['var_pct']:+.0f}%" if c["var_pct"] is not None else "–"] for c in hc["centrales"][:25]]
        el.append(tabla(["Central", "Empresa", "Tipo", f"GWh {hc['act']}", f"GWh {hc['ant']}", "Diferencia", "Var."],
                        filas, [0.2, 0.3, 0.1, 0.1, 0.1, 0.11, 0.09]))
        el.append(P(f"Total hidro: {hc['total_act']:,.1f} GWh vs. {hc['total_ant']:,.1f} GWh. Se muestran las 25 "
                    f"centrales con mayor caída.", nota))
        el.append(PageBreak())

    fuente_ieod = f"IEOD del {dia_ieod:%d/%m/%Y}" if dia_ieod else "IEOD no disponible"
    el.append(Paragraph(f"Indisponibilidades de generación <font size=8 color='{GRIS}'>({fuente_ieod})</font>", h1))
    ind_g = sorted(ieod.get("indisponibilidades") or [], key=lambda r: (bool(r.get("diesel")), -r["mw"], r["empresa"]))
    if ind_g:
        sin = [r for r in ind_g if not r.get("diesel")]
        dsl = [r for r in ind_g if r.get("diesel")]
        mw_p = sum(r["mw"] for r in sin if r["programado"])
        mw_f = sum(r["mw"] for r in sin if not r["programado"])
        por_tec = {}
        for r in sin:
            por_tec[r.get("tecnologia", "Otra")] = por_tec.get(r.get("tecnologia", "Otra"), 0) + r["mw"]
        st = extra.get("indisp_stats") or {"max": mw_p + mw_f, "hora_max": "", "prom": 0, "mwh": 0,
                                           "programado": {"prom": mw_p}, "forzado": {"prom": mw_f}, "diesel_max": 0}
        kp = ParagraphStyle("kp", parent=txt, leading=18)
        kpi = Table([[P(f"<font size=8 color='{GRIS}'>Máximo simultáneo sin diésel</font><br/><font size=16 color='{AZUL}'>"
                        f"<b>{st['max']:,.0f} MW</b></font><br/><font size=7 color='{GRIS}'>a las {st['hora_max']} h</font>", kp),
                      P(f"<font size=8 color='{GRIS}'>Promedio del día</font><br/><font size=13><b>{st['prom']:,.0f} MW</b></font>"
                        f"<br/><font size=7 color='{GRIS}'>{st['mwh']:,.0f} MWh de capacidad</font>", kp),
                      P(f"<font size=8 color='{GRIS}'>Programado / forzado (prom.)</font><br/><font size=13><b>"
                        f"{st['programado']['prom']:,.0f}</b> / <font color='#c5221f'><b>{st['forzado']['prom']:,.0f}</b></font> MW</font>", kp),
                      P(f"<font size=8 color='{GRIS}'>Diésel (excluido, máx.)</font><br/><font size=13 color='{GRIS}'><b>"
                        f"{st['diesel_max']:,.0f} MW</b></font>", kp)]],
                    colWidths=[0.31 * ancho, 0.23 * ancho, 0.23 * ancho, 0.23 * ancho])
        kpi.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d9dce6")),
                                 ("LINEBEFORE", (1, 0), (-1, 0), 0.4, colors.HexColor("#d9dce6")),
                                 ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#fff3ec")),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        el.append(kpi)
        el.append(Spacer(1, 3))
        el.append(P("Máximo simultáneo: capacidad fuera de servicio al mismo tiempo, contando una sola vez cada unidad "
                    "(si hay registro de central completa y de sus unidades se toma el mayor). La suma de registros "
                    f"({sum(r['mw'] for r in sin):,.0f} MW) no es potencia simultánea. Los MWh son capacidad indisponible, "
                    "no generación perdida. Suma de registros por tecnología: " + " · ".join(
                        f"{k} {v:,.0f} MW" for k, v in sorted(por_tec.items(), key=lambda x: -x[1])), nota))
        el.append(Spacer(1, 4))
    el.append(tabla(["Empresa", "Central", "Unidad", "Tecnología", "Horario", "MW", "Tipo", "Descripción"],
                    [[r["empresa"].title(), r["ubicacion"].title(), r["equipo"],
                      (f"<font color='{GRIS}'>Diésel · excluido</font>" if r.get("diesel") else r.get("tecnologia", "")),
                      periodo(r, dia_ieod or dia),
                      (f"<font color='{GRIS}'>{r['mw']:.1f}</font>" if r.get("diesel") else f"<b>{r['mw']:.1f}</b>"),
                      "Prog." if r["programado"] else "<font color='#c5221f'>Forzado</font>",
                      r["descripcion"][:120]] for r in ind_g],
                    [0.14, 0.12, 0.08, 0.1, 0.1, 0.06, 0.07, 0.33]))
    el.append(PageBreak())

    el.append(Paragraph("Transmisión ≥220 kV y eventos", h1))
    el.append(Paragraph("Líneas de transmisión ≥220 kV con intervenciones ejecutadas", h2))
    lin = sorted(fc.filtrar_lineas_220(ieod.get("mantenimientos") or []), key=lambda r: (-r["kv"], r["equipo"]))
    el.append(tabla(["Línea", "kV", "Empresa", "Tramo", "Horario", "Estado", "Descripción"],
                    [[r["equipo"], f"{r['kv']:.0f}", r["empresa"].title(), r["ubicacion"].title(),
                      periodo(r, dia_ieod or dia), r["estado"], r["descripcion"][:120]] for r in lin],
                    [0.08, 0.05, 0.16, 0.17, 0.11, 0.06, 0.37]))
    el.append(CondPageBreak(4 * cm)); el.append(Paragraph("Eventos relevantes del día", h2))
    ev = ieod.get("eventos") or []
    el.append(tabla(["Tipo", "Empresa", "Equipo", "Horario", "kV", "MW", "Descripción"],
                    [[e["tipo"].title(), e["empresa"].title(), f"{e['equipo']} · {e['ubicacion'].title()}",
                      periodo(e, dia_ieod or dia), f"{e['kv']:.0f}" if e["kv"] else "", f"{e['mw']:.1f}" if e["mw"] else "",
                      e["descripcion"][:160]] for e in ev],
                    [0.07, 0.14, 0.17, 0.1, 0.05, 0.05, 0.42]))
    el.append(CondPageBreak(4 * cm)); el.append(Paragraph("Restricciones operativas vigentes", h2))
    el.append(tabla(["Empresa", "Ubicación", "Equipo", "Horario", "Descripción"],
                    [[r["empresa"].title(), r["ubicacion"].title(), r["equipo"], f"{r['inicio']}–{r['final']}",
                      r["descripcion"][:110]] for r in ieod.get("restricciones") or []],
                    [0.16, 0.16, 0.1, 0.09, 0.49], max_filas=25))
    el.append(PageBreak())

    sem = extra.get("semana_embalses")
    el.append(Paragraph(f"Embalses por cuenca vs. años anteriores <font size=8 color='{GRIS}'>"
                        f"({sem or 'Evaluación Semanal no disponible'} · dato diario: IEOD)</font>", h1))
    cu = extra.get("cuencas") or []
    if cu:
        def pct(x):
            if x is None:
                return "–"
            return f"<font color='#c5221f'>{x:+.0f}%</font>" if x < 0 else f"{x:+.0f}%"

        def fila(c):
            di = c.get("diario") or {}
            diario = (f"{di['total']:,.1f} ({dt.date.fromisoformat(di['fecha']):%d/%m}) {pct(di.get('var_pct'))}"
                      if di.get("representativo") and di.get("total") is not None else "solo semanal")
            q = c.get("caudal") or {}
            caudal = f"{q['actual']:,.1f} {pct(q.get('var_pct'))}" if q.get("actual") is not None else "–"
            return [c["cuenca"], f"sem. {c['semana']}", caudal, f"{c['actual']:,.1f}",
                    f"{c['anterior']:,.1f}" if c["anterior"] is not None else "–", pct(c["var_pct"]), diario,
                    f"{c['mw_total']:,.1f} MW" if c["mw_total"] else "–"]

        el.append(tabla(["Cuenca", "Semana", "Caudal natural (m3/s) y var.", "Volumen (Hm3)", "Año ant.", "Var.",
                         "Dato diario IEOD (Hm3)", "Potencia instalada"],
                        [fila(c) for c in cu], [0.12, 0.08, 0.17, 0.11, 0.09, 0.07, 0.22, 0.14]))
        el.append(Spacer(1, 4))
        el.append(img(graficos.get("embalses"), 20))
    else:
        el.append(P("No se pudo leer el Informe de Evaluación Semanal.", nota))
    el.append(PageBreak())
    el.append(Paragraph(f"Programación · {fecha_larga(hoy)}", h1))
    if prog is None:
        el.append(P("El Programa Diario de Intervenciones de hoy aún no está publicado.", nota))
    else:
        todas = fc.solo_generacion(prog)
        g = sorted([r for r in todas if r["mw"] > 0], key=lambda r: (-r["mw"], r["empresa"]))
        el.append(CondPageBreak(4 * cm))
        el.append(Paragraph(f"Generación · intervenciones con MW indisponibles <font size=8 color='{GRIS}'>"
                            f"({len(todas) - len(g)} sin MW no se muestran)</font>", h2))
        el.append(tabla(["Empresa", "Central", "Unidad", "Horario", "MW", "Descripción"],
                        [[r["empresa"].title(), r["ubicacion"].title(), r["equipo"], periodo(r, hoy), f"{r['mw']:.1f}",
                          r["descripcion"][:150]] for r in g],
                        [0.17, 0.15, 0.1, 0.11, 0.06, 0.41]))
        lp = sorted(fc.filtrar_lineas_220(prog), key=lambda r: (-r["kv"], r["equipo"]))
        el.append(CondPageBreak(4 * cm)); el.append(Paragraph("Líneas de transmisión ≥220 kV", h2))
        el.append(tabla(["Línea", "kV", "Empresa", "Tramo", "Horario", "Estado", "Descripción"],
                        [[r["equipo"], f"{r['kv']:.0f}", r["empresa"].title(), r["ubicacion"].title(), periodo(r, hoy),
                          r["estado"], r["descripcion"][:120]] for r in lp],
                        [0.08, 0.05, 0.16, 0.17, 0.11, 0.06, 0.37]))

    doc = SimpleDocTemplate(str(ruta), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=2.5 * cm, bottomMargin=1.6 * cm,
                            title=f"Reporte Diario del SEIN {dia:%d-%m-%Y}", author="Hidroeléctrica Huanchor – Área Comercial")
    doc.build(el, onFirstPage=encabezado, onLaterPages=encabezado)
    return ruta


# --------------------------------------------------------------------------- dashboard
def _iso(v):
    return v.isoformat() if isinstance(v, (dt.datetime, dt.date)) else v


def _limpio(regs):
    return [{k: _iso(v) for k, v in r.items()} for r in regs]


def datos_dashboard(dia, hoy, ind, ieod, dia_ieod, prog, gen, bullets, m, extra=None):
    extra = extra or {}
    cmg30 = {}
    for b in m.BARRAS:
        cmg30[b] = [[_iso(t), round(r[b] / m.TC, 2)] for t, r in sorted(m_hist_rango(m, ind, dia))
                    if isinstance(r.get(b), float)]
    gen_dia = []
    dd = extra.get("diesel")
    sd = dd["serie"] if dd and dia_ieod == dia else None
    for t, r in sorted(gen.items()):
        if m.dia_operativo(t) == dia:
            g = m.agrupar(r, sd.get(m.min_dia(t), {}) if sd is not None else None)
            gen_dia.append({"t": _iso(t), **{k: round(v, 1) for k, v in g.items()}})
    return {
        "generado": dt.datetime.now(fc.LIMA).isoformat(timespec="minutes"),
        "dia": dia.isoformat(), "hoy": hoy.isoformat(), "dia_ieod": _iso(dia_ieod), "tc": m.TC,
        "resumen": bullets,
        "bloques": extra.get("bloques"),
        "tablero": extra.get("tablero"),
        "tramos": dict(TRAMOS),
        "alertas": extra.get("alertas") or [],
        "umbrales": UMBRALES,
        "barras": list(m.BARRAS), "colores": {b: c for b, (_, _, c) in m.BARRAS.items()},
        "cmg_diario": {b: {d.isoformat(): round(v, 2) for d, v in sorted(ind["diario_b"][b].items())}
                       for b in m.BARRAS},
        "cmg_mes": {b: (round(v, 2) if v is not None else None) for b, v in ind["prom_mes_b"].items()},
        "cmg_n": {b: {d.isoformat(): n for d, n in sorted(ind["n_b"].get(b, {}).items())} for b in m.BARRAS},
        "cmg_prev": {b: (round(v, 2) if v is not None else None) for b, v in ind["prev"].items()},
        "bloques_diario": {bl: {d.isoformat(): round(v, 2) for d, v in sorted(ind["diario_bl"][bl].items())}
                           for bl in m.BLOQUES},
        "bloques_mes": {bl: (round(v, 2) if v is not None else None) for bl, v in ind["prom_mes_bl"].items()},
        "cmg_30min": cmg30,
        "generacion": gen_dia, "grupos_gen": {g: m.color_grupo(g) for g in (gen_dia[0] if gen_dia else m.GRUPOS_GEN)
                                              if g != "t"},
        "diesel_unidades": _limpio((dd or {}).get("unidades") or []),
        "gen_fuente": "IEOD" if extra.get("gen_ieod") == dia else "Portal",
        "demanda_areas": ieod.get("demanda_areas") or [],
        "indisponibilidades": _limpio(ieod.get("indisponibilidades") or []),
        "lineas_220": _limpio(fc.filtrar_lineas_220(ieod.get("mantenimientos") or [])),
        "eventos": _limpio(ieod.get("eventos") or []),
        "restricciones": ieod.get("restricciones") or [],
        "embalses": ieod.get("embalses") or [],
        "gas": ieod.get("gas") or [],
        "programado_gen": _limpio(fc.solo_generacion(prog or [])),
        "programado_lineas": _limpio(fc.filtrar_lineas_220(prog or [])),
        "programado_publicado": prog is not None,
        "demanda_hist": extra.get("demanda"),
        "hidro_pasada": extra.get("hidro"),
        "hidro_regulacion": extra.get("regulacion"),
        "flujos": extra.get("flujos") or {},
        "prog_mensual": extra.get("prog_mensual") or {"mes": None, "regs": []},
        "indisp_stats": extra.get("indisp_stats"),
        "prog_stats": stats_indisp(fc.solo_generacion(prog or []), hoy) if prog else None,
        "enlaces": extra.get("enlaces") or {},
        "congestion": extra.get("congestion") or {"columnas": [], "registros": []},
        "eolica": extra.get("eolica"),
        "hidro_centrales": extra.get("hidro_centrales"),
        "huanchor": extra.get("huanchor"),
        "cmg_proy": extra.get("cmg_proy"),
        "embalses_semanal": {"semana": extra.get("semana_embalses"), "cuencas": extra.get("cuencas") or []},
    }


def m_hist_rango(m, ind, dia):
    """Intervalos del día evaluado y del anterior (para la curva de 30 min)."""
    return [(t, r) for t, r in ind["_hist"].items() if m.dia_operativo(t) in (dia, dia - dt.timedelta(days=1))]


# --------------------------------------------------------------------------- indisponibilidad sin doble conteo
def stats_indisp(regs, dia):
    """Máximo simultáneo, promedio, MWh y cierre (sin diésel), total y separado en programado/forzado."""
    if not dia:
        return None
    sin = [r for r in regs if not r.get("diesel") and (r.get("mw") or 0) > 0]
    tot = fc.perfil_indisponible(sin, dia)
    tot["programado"] = fc.perfil_indisponible([r for r in sin if r.get("programado")], dia)
    tot["forzado"] = fc.perfil_indisponible([r for r in sin if not r.get("programado")], dia)
    for k in ("programado", "forzado"):
        tot[k].pop("perfil")
    tot["registros"], tot["unidades"] = len(sin), len({(fc.norm(r["ubicacion"]), fc.norm(r["equipo"])) for r in sin})
    tot["suma_registros"] = round(sum(r["mw"] for r in sin), 1)
    tot["diesel_max"] = fc.perfil_indisponible([r for r in regs if r.get("diesel")], dia)["max"]
    return tot


# --------------------------------------------------------------------------- programa mensual
F_PM = Path("data") / "programa_mensual.json"


def _unir_tramos(regs):
    """El programa mensual trae una fila por día: une los días seguidos de la misma intervención en un solo tramo."""
    clave = lambda r: (r["empresa"], r["ubicacion"], r["equipo"], round(r["mw"], 2), r["descripcion"])
    out = []
    for r in sorted(regs, key=lambda r: (clave(r), r["inicio"])):
        u = out[-1] if out else None
        if u and clave(u) == clave(r) and u["final"] and r["inicio"] <= u["final"] + dt.timedelta(minutes=1):
            u["final"] = max(u["final"], r["final"] or r["inicio"])
        else:
            out.append(dict(r))
    return sorted(out, key=lambda r: (r["inicio"], -r["mw"]))


def programa_mensual(hoy, hojas_ieod=None):
    """Intervenciones de generación con MW indisponibles del Programa Mensual de Mantenimiento (cache 2 días)."""
    mes = f"{hoy:%Y-%m}"
    previo = json.loads(F_PM.read_text(encoding="utf-8")) if F_PM.exists() else None
    if previo and previo.get("mes") == mes and (hoy - dt.date.fromisoformat(previo["consultado"])).days < 2 \
            and previo.get("regs") and previo.get("v") == 2:
        regs = previo["regs"]
    else:
        crudos, diag = fc.programa_mensual(hoy)
        (Path("data") / "explora6").mkdir(parents=True, exist_ok=True)
        (Path("data") / "explora6" / "programa_mensual_diag.json").write_text(
            json.dumps(diag, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        if not crudos:
            return previo if previo and previo.get("mes") == mes else {"mes": mes, "regs": [], "fuente": None}
        mh, hs = (fc.combustibles_hop(hojas_ieod), fc.centrales_hidro(hojas_ieod)) if hojas_ieod else ({}, set())
        regs = []
        for r in fc.solo_generacion(crudos):
            if r["mw"] <= 0 or not r["inicio"]:
                continue
            r["tecnologia"] = fc.tecnologia(r, mh, hs)
            r["diesel"] = r["tecnologia"] == "Diésel"
            regs.append(r)
        regs = [{k: _iso(v) for k, v in r.items()} for r in _unir_tramos(regs)]
        previo = {"v": 2, "mes": mes, "consultado": hoy.isoformat(), "fuente": diag.get("usado"), "regs": regs}
        F_PM.write_text(json.dumps(previo, ensure_ascii=False), encoding="utf-8")
    return previo



def cmg_proyectado(m, hist, dia, hoy):
    """CMg proyectado del Programa Semanal (YUPANA) en USD/MWh por día y barra, con la unidad verificada."""
    serie, meta = fc.cmg_programa_semanal(hoy)
    try:
        (Path("data") / "explora6").mkdir(parents=True, exist_ok=True)
        (Path("data") / "explora6" / "programa_semanal_cmg_diag.json").write_text(
            json.dumps({**meta, "intervalos": len(serie)}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except Exception:
        pass
    if not serie:
        return None
    # unidad: la declarada en el archivo o, si no la declara, contrastando con el CMg ejecutado de los mismos intervalos
    unidad, metodo = meta.get("unidad"), "declarada en el archivo"
    if not unidad:
        ratios = []
        for t, v in serie.items():
            ej = (hist.get(t.replace(tzinfo=fc.LIMA)) or {}).get(m.SR)
            if isinstance(v.get(m.SR), float) and v[m.SR] > 0 and isinstance(ej, float) and ej > 0:
                ratios.append(v[m.SR] / (ej / m.TC))
        ratios.sort()
        r = ratios[len(ratios) // 2] if ratios else None
        if r and 2.4 <= r <= 4.8:
            unidad, metodo = "S/.", f"inferida: proyectado/ejecutado ≈ {r:.2f} (≈ TC)"
        elif r and 0.55 <= r <= 1.8:
            unidad, metodo = "USD", f"inferida: proyectado/ejecutado ≈ {r:.2f}"
        else:
            return {"error": "No se pudo verificar la unidad del CMg proyectado; no se publica.", "archivos": meta["archivos"]}
    k = 1 / m.TC if unidad == "S/." else 1.0
    diario, n = {}, {}
    for t, v in serie.items():
        d = (t - dt.timedelta(minutes=1)).date().isoformat()
        for b, x in v.items():
            diario.setdefault(b, {}).setdefault(d, []).append(x * k)
    out_d = {b: {d: round(sum(x) / len(x), 2) for d, x in sorted(dd.items())} for b, dd in diario.items()}
    out_n = {b: {d: len(x) for d, x in sorted(dd.items())} for b, dd in diario.items()}
    sem = meta["semanas"]
    return {"diario": out_d, "n": out_n, "unidad_origen": unidad, "metodo_unidad": metodo,
            "archivos": [a.split("/")[-1] for a in meta["archivos"]],
            "version": "Final" if any("/FINAL/" in fc.norm(a) + "/" for a in meta["archivos"]) else "Preliminar",
            "semanas": [f"{s_['desde']} a {s_['hasta']}" for s_ in sem], "nombres": meta.get("nombres"),
            "consultado": hoy.isoformat()}

# --------------------------------------------------------------------------- orquestación
def generar(m, hist=None):
    """Genera PDF y datos del dashboard. Devuelve (ruta_pdf, texto_resumen)."""
    plt = m._plt()
    ahora = dt.datetime.now(fc.LIMA)
    hoy = ahora.date()
    dia = hoy - dt.timedelta(days=1)
    SALIDA.mkdir(exist_ok=True)
    tmp = SALIDA / "tmp"
    tmp.mkdir(exist_ok=True)

    if hist is None:
        hist = m.leer_hist()
        m.actualizar(hist, dia)
        m.guardar_hist(hist)
    ind = indicadores_cmg(m, hist, dia)
    ind["_hist"] = hist

    try:
        dia_ieod, hojas = fc.descargar_ieod(dia)
        ieod = fc.parsear_ieod(hojas) if hojas else {}
        mapa_hop, hidro_set = fc.combustibles_hop(hojas), fc.centrales_hidro(hojas)
        for r in ieod.get("indisponibilidades") or []:
            r["tecnologia"] = fc.tecnologia(r, mapa_hop, hidro_set)
            r["diesel"] = r["tecnologia"] == "Diésel"
    except Exception as e:
        print("IEOD no disponible:", e, file=sys.stderr)
        dia_ieod, ieod, hojas = None, {}, {}

    extra = {}
    try:
        extra["indisp_stats"] = stats_indisp(ieod.get("indisponibilidades") or [], dia_ieod)
    except Exception as e:
        print("stats indisponibilidad:", e, file=sys.stderr)
    try:
        if hojas:
            fc.volcar_hojas(hojas, Path("data") / "explora6")
            extra["flujos"] = fc.flujos_lineas(hojas)
            extra["congestion"] = fc.congestiones(hojas)
            extra["enlaces"] = fc.interconexiones(hojas)
    except Exception as e:
        print("Flujos/congestión no disponibles:", e, file=sys.stderr)
    try:
        if hojas and dia_ieod:
            extra["diesel"] = fc.diesel_despacho(hojas, dia_ieod)
    except Exception as e:
        print("Despacho diésel no disponible:", e, file=sys.stderr)
    try:
        extra["demanda"] = hi.resumen_demanda(hi.actualizar_demanda(dia), dia)
    except Exception as e:
        print("Demanda histórica no disponible:", e, file=sys.stderr)
    try:
        h, pend = hi.actualizar_hidro(dia, hojas if dia_ieod == dia else None)
        extra["hidro"] = hi.resumen_hidro(h, dia)
        extra["hidro"]["pendientes"] = len(pend)
        extra["regulacion"] = hi.resumen_hidro(h, dia, "regulacion")
        extra["hidro_centrales"] = hi.resumen_centrales(dia)
        extra["huanchor"] = hi.resumen_huanchor(dia, ind["_hist"], m.TC, m.leer_diag_hu())
        extra["eolica"] = hi.resumen_hidro(h, dia, "eolica")
    except Exception as e:
        print("Hidro de pasada no disponible:", e, file=sys.stderr)
    try:
        extra["cmg_proy"] = cmg_proyectado(m, ind["_hist"], dia, hoy)
    except Exception as e:
        print("CMg proyectado (programa semanal) no disponible:", e, file=sys.stderr)
    try:
        lis = fc.listados_ieod()
        if lis:
            (Path("data") / "explora6").mkdir(parents=True, exist_ok=True)
            (Path("data") / "explora6" / "listados_ieod.json").write_text(
                json.dumps(lis, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print("listados IEOD:", e, file=sys.stderr)
    try:
        emb = hi.actualizar_embalses(hoy)
        try:
            vol = hi.resumen_vol(dia)
        except Exception as e:
            print("Volúmenes diarios no disponibles:", e, file=sys.stderr)
            vol = {}
        extra["cuencas"] = hi.cuencas_seleccionadas(emb, vol)
        extra["semana_embalses"] = hi.etiqueta_semana(emb.get("semana"))
    except Exception as e:
        print("Embalses semanales no disponibles:", e, file=sys.stderr)
    try:
        prog = fc.intervenciones_programadas(hoy)
        prog = prog if prog else None
        if prog:
            mh, hs = (fc.combustibles_hop(hojas), fc.centrales_hidro(hojas)) if hojas else ({}, set())
            for r in prog:
                r["tecnologia"] = fc.tecnologia(r, mh, hs)
                r["diesel"] = r["tecnologia"] == "Diésel"
    except Exception as e:
        print("Intervenciones no disponibles:", e, file=sys.stderr)
        prog = None
    try:
        extra["prog_mensual"] = programa_mensual(hoy, hojas)
    except Exception as e:
        print("Programa mensual no disponible:", e, file=sys.stderr)
    try:
        gen, _ = m.generacion(dia - dt.timedelta(days=1), dia)
    except Exception as e:
        print("Generación no disponible:", e, file=sys.stderr)
        gen = {}
    try:
        # El día con IEOD se toma de la hoja TIPO_RECURSO (clasificación oficial del COES): el portal SCADA
        # a veces asigna a "diésel/residual" centrales que en realidad operan con gas.
        gi = fc.generacion_ieod(hojas, dia_ieod) if hojas and dia_ieod else {}
        if gi:
            gen = {t: r for t, r in gen.items() if m.dia_operativo(t) != dia_ieod}
            gen.update(gi)
            extra["gen_ieod"] = dia_ieod
    except Exception as e:
        print("Generación IEOD no disponible:", e, file=sys.stderr)

    g = {}
    g["barras"] = tmp / "barras.png"
    m.grafico_lineas_barras(ind["diario_b"], ind["prom_mes_b"], dia, g["barras"])
    g["bloques"] = tmp / "bloques.png"
    m.grafico_sr_bloques(ind["diario_b"][m.SR], ind["diario_bl"], ind["prom_mes_b"][m.SR], ind["prom_mes_bl"],
                         dia, g["bloques"])
    g["30min"] = tmp / "30min.png"
    m.grafico_30min(hist, dia, g["30min"])
    if gen:
        g["generacion"] = tmp / "generacion.png"
        sd = {dia_ieod: extra["diesel"]["serie"]} if extra.get("diesel") and dia_ieod else None
        m.grafico_generacion(gen, dia, g["generacion"], sd,
                             fuente=f"Fuente: COES – IEOD, producción por tipo de recurso ({dia_ieod:%d/%m}); "
                                    f"Portal de Información (resto)" if extra.get("gen_ieod") else None)
    g["demanda"] = grafico_demanda(ieod.get("demanda_areas"), dia_ieod or dia, tmp / "demanda.png", plt)
    if extra.get("demanda"):
        g["dem_mensual"] = hi.grafico_demanda_mensual(extra["demanda"], tmp / "dem_mensual.png", plt)
        g["dem_acum"] = hi.grafico_demanda_acum(extra["demanda"], tmp / "dem_acum.png", plt)
    if extra.get("hidro"):
        g["hidro"] = hi.grafico_hidro(extra["hidro"], tmp / "hidro.png", plt)
    for k in ("regulacion", "eolica"):
        if extra.get(k) and any(extra[k]["diario"].values()):
            g[k] = hi.grafico_hidro(extra[k], tmp / f"{k}.png", plt)
    if extra.get("cuencas"):
        g["embalses"] = hi.grafico_embalses(extra["cuencas"], tmp / "embalses.png", plt)

    try:
        f_tr = Path("data") / "tramos_lineas.json"
        previo = json.loads(f_tr.read_text(encoding="utf-8")) if f_tr.exists() else {}
        nuevos = fc.tramos_lineas(prog or [], ieod.get("eventos"), ieod.get("mantenimientos"),
                                  (extra.get("prog_mensual") or {}).get("regs"))
        TRAMOS.clear()
        TRAMOS.update({**fc.tramos_de_flujos(extra.get("flujos")), **previo, **nuevos})
        f_tr.write_text(json.dumps(dict(sorted(TRAMOS.items())), ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception as e:
        print("tramos de líneas:", e, file=sys.stderr)
    bullets = resumen(ind, ieod, prog, dia, m, extra)
    try:
        extra["bloques"] = resumen_bloques(ind, ieod, prog, dia, hoy, m, extra)
        extra["tablero"] = resumen_tablero(ind, ieod, prog, dia, hoy, m, extra)
    except Exception as e:
        print("resumen en bloques:", e, file=sys.stderr)
    try:
        extra["alertas"] = alertas(ind, ieod, dia_ieod, prog, dia, m, extra)
    except Exception as e:
        print("alertas:", e, file=sys.stderr)
    ruta = SALIDA / f"Reporte_SEIN_{dia:%Y-%m-%d}.pdf"
    construir_pdf(ruta, dia, hoy, ind, ieod, dia_ieod, prog, g, bullets, m, extra)

    DOCS.mkdir(exist_ok=True)
    if Path("dashboard.html").exists():
        (DOCS / "index.html").write_text(Path("dashboard.html").read_text(encoding="utf-8"), encoding="utf-8")
    if LOGO.exists():
        (DOCS / "logo.png").write_bytes(LOGO.read_bytes())
    (DOCS / ".nojekyll").write_text("")
    datos = datos_dashboard(dia, hoy, ind, ieod, dia_ieod, prog, gen, bullets, m, extra)
    (DOCS / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, default=str), encoding="utf-8")
    (DOCS / "reportes").mkdir(exist_ok=True)
    (DOCS / "reportes" / ruta.name).write_bytes(ruta.read_bytes())
    indice = sorted((p.name for p in (DOCS / "reportes").glob("Reporte_SEIN_*.pdf")), reverse=True)
    (DOCS / "reportes.json").write_text(json.dumps(indice[:120]), encoding="utf-8")
    return ruta, bullets
