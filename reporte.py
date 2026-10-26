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
    diario_b, prom_mes_b = {}, {}
    for b in m.BARRAS:
        por_dia = {}
        for t, r in mes.items():
            if isinstance(r.get(b), float):
                por_dia.setdefault(m.dia_operativo(t), []).append(r[b] / m.TC)
        diario_b[b] = {d: m.promedio(v) for d, v in por_dia.items()}
        prom_mes_b[b] = m.promedio([x for v in por_dia.values() for x in v])
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
            "prom_mes_bl": prom_mes_bl, "prev": prev, "n_dia": n_dia}


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
        b.append(f"Indisponibilidad de generación (sin diésel): <b>{mw:,.0f} MW</b> en {len(sin)} registros "
                 f"({sum(1 for r in sin if not r['programado'])} forzados); diésel aparte: "
                 f"{sum(r['mw'] for r in dsl):,.0f} MW. Mayores: " +
                 ", ".join(f"{r['ubicacion'].title()} {r['equipo']} ({r['mw']:.0f} MW)" for r in top) + ".")
    lin = fc.filtrar_lineas_220(ieod.get("mantenimientos") or [])
    ev = ieod.get("eventos") or []
    ev_l = fc.filtrar_lineas_220(ev)
    if ev:
        b.append(f"Eventos: {len(ev)} registrados ({sum(1 for e in ev if e['tipo'].upper() == 'FALLA')} fallas)"
                 + (f"; líneas ≥220 kV afectadas: {', '.join(e['equipo'] for e in ev_l)}." if ev_l else "."))
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
        b.append(f"Programado para hoy: <b>{sum(r['mw'] for r in g):,.0f} MW</b> indisponibles sin diésel en "
                 f"{len(g)} intervenciones y {len({r['equipo'] for r in lp})} líneas ≥220 kV intervenidas.")
    return b


# --------------------------------------------------------------------------- PDF
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
        t = Table([[P(f"<b>{c}</b>") for c in cab]] + [[P(x) for x in f] for f in filas],
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
    el.append(Paragraph("Resumen ejecutivo", h1))
    for t in bullets:
        el.append(Paragraph(t, bul, bulletText="•"))
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
        kpi = Table([[P(f"<font size=8 color='{GRIS}'>Indisponible sin diésel</font><br/><font size=16 color='{AZUL}'>"
                        f"<b>{mw_p + mw_f:,.0f} MW</b></font>", txt),
                      P(f"<font size=8 color='{GRIS}'>Programado</font><br/><font size=13><b>{mw_p:,.0f} MW</b></font>", txt),
                      P(f"<font size=8 color='{GRIS}'>Forzado</font><br/><font size=13 color='#c5221f'><b>{mw_f:,.0f} MW</b></font>", txt),
                      P(f"<font size=8 color='{GRIS}'>Diésel (excluido)</font><br/><font size=13 color='{GRIS}'><b>"
                        f"{sum(r['mw'] for r in dsl):,.0f} MW</b></font>", txt)]],
                    colWidths=[0.31 * ancho, 0.23 * ancho, 0.23 * ancho, 0.23 * ancho])
        kpi.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d9dce6")),
                                 ("LINEBEFORE", (1, 0), (-1, 0), 0.4, colors.HexColor("#d9dce6")),
                                 ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#fff3ec")),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        el.append(kpi)
        el.append(Spacer(1, 3))
        el.append(P("Por tecnología (sin diésel): " + " · ".join(f"{k} {v:,.0f} MW" for k, v in
                                                                sorted(por_tec.items(), key=lambda x: -x[1])), nota))
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
            if c.get("solo_diario"):
                return [f"{c['cuenca']} (prom. diario)", f"{dt.date.fromisoformat(di['fecha']):%d/%m}",
                        f"{di['total']:,.2f}", f"{di['anterior']:,.2f}" if di.get("anterior") is not None else "–",
                        pct(di.get("var_pct")), "–",
                        f"{c['mw_total']:,.1f} MW" if c["mw_total"] else "–"]
            diario = (f"{di['total']:,.1f} ({dt.date.fromisoformat(di['fecha']):%d/%m}) {pct(di.get('var_pct'))}"
                      if di.get("representativo") and di.get("total") is not None else "solo semanal")
            return [c["cuenca"], f"sem. {c['semana']}", f"{c['actual']:,.1f}",
                    f"{c['anterior']:,.1f}" if c["anterior"] is not None else "–", pct(c["var_pct"]), diario,
                    f"{c['mw_total']:,.1f} MW" if c["mw_total"] else "–"]

        el.append(tabla(["Cuenca", "Fecha", "Volumen (Hm3)", "Mismo período año ant.", "Var.",
                         "Dato diario IEOD (Hm3)", "Potencia instalada"],
                        [fila(c) for c in cu], [0.17, 0.08, 0.12, 0.15, 0.08, 0.24, 0.16]))
        el.append(Spacer(1, 4))
        el.append(img(graficos.get("embalses"), 20))
    else:
        el.append(P("No se pudo leer el Informe de Evaluación Semanal.", nota))
    el.append(PageBreak())
    el.append(Paragraph(f"Programado para hoy · {fecha_larga(hoy)}", h1))
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
        "barras": list(m.BARRAS), "colores": {b: c for b, (_, _, c) in m.BARRAS.items()},
        "cmg_diario": {b: {d.isoformat(): round(v, 2) for d, v in sorted(ind["diario_b"][b].items())}
                       for b in m.BARRAS},
        "cmg_mes": {b: (round(v, 2) if v is not None else None) for b, v in ind["prom_mes_b"].items()},
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
        "enlaces": extra.get("enlaces") or {},
        "congestion": extra.get("congestion") or {"columnas": [], "registros": []},
        "eolica": extra.get("eolica"),
        "embalses_semanal": {"semana": extra.get("semana_embalses"), "cuencas": extra.get("cuencas") or []},
    }


def m_hist_rango(m, ind, dia):
    """Intervalos del día evaluado y del anterior (para la curva de 30 min)."""
    return [(t, r) for t, r in ind["_hist"].items() if m.dia_operativo(t) in (dia, dia - dt.timedelta(days=1))]


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
        extra["eolica"] = hi.resumen_hidro(h, dia, "eolica")
    except Exception as e:
        print("Hidro de pasada no disponible:", e, file=sys.stderr)
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
        extra["semana_embalses"] = emb.get("semana")
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

    bullets = resumen(ind, ieod, prog, dia, m, extra)
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
