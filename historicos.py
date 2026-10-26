#!/usr/bin/env python3
"""
Series históricas para comparar contra el año anterior (cacheadas en data/):

- data/demanda_diaria.csv   fecha, energia_mwh, intervalos, max_mw     (Portal de Información, desde ene del año previo)
- data/recursos.csv         fecha, hora, pasada, regulacion, eolica     (IEOD · TIPO_RECURSO, MW)
- data/embalses_semanal.json                                            (Evaluación Semanal · hoja 5.2)
- data/volumenes_diarios.csv  fecha, cuenca, embalse, prom, final       (IEOD · PRINCIP_VOLÚMENES, Hm3)

Más los gráficos (matplotlib) para el PDF.
"""
import calendar
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

import fuentes_coes as fc

DATA = Path("data")
F_DEM = DATA / "demanda_diaria.csv"
F_HID = DATA / "hidro_pasada.csv"     # formato anterior (solo pasada); se migra a recursos.csv
F_REC = DATA / "recursos.csv"
RECURSOS = ("pasada", "regulacion", "eolica")
F_EMB = DATA / "embalses_semanal.json"
F_VOL = DATA / "volumenes_diarios.csv"
VENTANA_VOL = 31          # días de volumen diario (año actual y mismas fechas del año anterior)

C_ACT = "#f0590f"     # año actual (naranja Huanchor)
C_ANT = "#2b4fd1"     # año anterior (azul)
C_24 = "#1baf7a"
C_23 = "#9aa0a6"
NAVY = "#001a6f"
GRIS = "#5f6368"
MESES_C = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic"]


def _hm_a_horas(h):
    hh, mm = (int(x) for x in h.split(":"))
    return (hh + mm / 60) or 24.0


# --------------------------------------------------------------------------- demanda
def leer_demanda():
    if not F_DEM.exists():
        return {}
    with F_DEM.open(encoding="utf-8") as f:
        return {dt.date.fromisoformat(r["fecha"]): {"mwh": float(r["energia_mwh"]), "n": int(r["intervalos"]),
                                                  "max": float(r["max_mw"])} for r in csv.DictReader(f)}


def guardar_demanda(dem):
    DATA.mkdir(exist_ok=True)
    with F_DEM.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "energia_mwh", "intervalos", "max_mw"])
        for d in sorted(dem):
            w.writerow([d.isoformat(), f"{dem[d]['mwh']:.1f}", dem[d]["n"], f"{dem[d]['max']:.1f}"])


def actualizar_demanda(hasta: dt.date, presupuesto_s=240):
    dem = leer_demanda()
    t0 = time.time()
    for anio in (hasta.year - 1, hasta.year):
        for mes in range(1, 13):
            d0 = dt.date(anio, mes, 1)
            if d0 > hasta:
                break
            d1 = min(dt.date(anio, mes, calendar.monthrange(anio, mes)[1]), hasta)
            dias = [d0 + dt.timedelta(days=k) for k in range((d1 - d0).days + 1)]
            if all(d in dem and dem[d]["n"] >= 48 for d in dias):
                continue
            if time.time() - t0 > presupuesto_s:
                break
            try:
                serie = fc.demanda_rango(d0, d1)
            except Exception as e:
                print("demanda", d0, e, file=sys.stderr)
                continue
            por_dia = {}
            for ts, mw in serie:
                por_dia.setdefault((ts - dt.timedelta(minutes=1)).date(), []).append(mw)
            for d, v in por_dia.items():
                if d0 <= d <= d1:
                    dem[d] = {"mwh": sum(v) * 0.5, "n": len(v), "max": max(v)}
    guardar_demanda(dem)
    return dem


def resumen_demanda(dem, dia: dt.date):
    """Energía mensual (TWh) por año, acumulado del mes día a día y comparación a la fecha."""
    act, ant = dia.year, dia.year - 1
    mensual = {act: {}, ant: {}}
    for d, v in dem.items():
        if d.year in mensual:
            mensual[d.year][d.month] = mensual[d.year].get(d.month, 0) + v["mwh"] / 1e6
    # mes en curso: comparar los mismos días del año anterior
    ndias = dia.day
    mtd = {a: sum(dem[dt.date(a, dia.month, k)]["mwh"] for k in range(1, ndias + 1)
                  if dt.date(a, dia.month, k) in dem) / 1e3 for a in (act, ant)}
    acum = {}
    for a in (act, ant):
        s, serie = 0.0, []
        for k in range(1, calendar.monthrange(a, dia.month)[1] + 1):
            d = dt.date(a, dia.month, k)
            if d in dem and (a == ant or d <= dia):
                s += dem[d]["mwh"] / 1e3
                serie.append(round(s, 2))
        acum[a] = serie
    anual = {a: sum(v for m, v in mensual[a].items() if m < dia.month) + mtd[a] / 1e3 for a in (act, ant)}
    return {"mensual": {a: {m: round(v, 4) for m, v in sorted(mensual[a].items())} for a in mensual},
            "mtd_gwh": {a: round(v, 1) for a, v in mtd.items()}, "dias": ndias, "acum_gwh": acum,
            "ytd_twh": {a: round(v, 3) for a, v in anual.items()}, "mes": dia.month, "act": act, "ant": ant}


def grafico_demanda_mensual(rd, ruta, plt):
    act, ant, mes = rd["act"], rd["ant"], rd["mes"]
    meses = list(range(1, mes + 1))
    va = [rd["mensual"][ant].get(m, 0) for m in meses]
    vb = [rd["mensual"][act].get(m, 0) for m in meses]
    va[-1] = rd["mtd_gwh"][ant] / 1e3       # mismo período del año anterior
    fig, ax = plt.subplots(figsize=(8.5, 4.2), dpi=160)
    x = range(len(meses))
    ax.bar([i - 0.2 for i in x], va, width=0.38, color=C_ANT, label=str(ant))
    ax.bar([i + 0.2 for i in x], vb, width=0.38, color=C_ACT, label=str(act))
    tope = max(va + vb) if va else 1
    for i, (a, b) in enumerate(zip(va, vb)):
        if a:
            ax.text(i, max(a, b) + tope * 0.02, f"{(b / a - 1) * 100:+.1f}%", ha="center", fontsize=7.5,
                    weight="bold", color="#202124")
    ax.set_xticks(list(x), [MESES_C[m - 1] + ("*" if m == mes else "") for m in meses], fontsize=8)
    ax.set_ylim(0, tope * 1.15)
    ax.set_ylabel("TWh", fontsize=8)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_title(f"Demanda de energía del SEIN · {act} vs {ant}", fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=7.5, frameon=False, loc="upper left", ncol=2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.text(0.99, 0.01, f"* {MESES_C[mes - 1]}: primeros {rd['dias']} días de cada año · Fuente: COES (demanda ejecutada)",
             ha="right", fontsize=6, color=GRIS)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


def grafico_demanda_acum(rd, ruta, plt):
    act, ant = rd["act"], rd["ant"]
    fig, ax = plt.subplots(figsize=(8.5, 3.8), dpi=160)
    for a, c, lw in ((ant, C_ANT, 1.8), (act, C_ACT, 2.6)):
        s = rd["acum_gwh"][a]
        if s:
            ax.plot(range(1, len(s) + 1), s, color=c, lw=lw, label=str(a), marker="o" if a == act else None, ms=3)
    a1, a0 = rd["mtd_gwh"][act], rd["mtd_gwh"][ant]
    if a0:
        ax.annotate(f"{a1:,.0f} GWh vs {a0:,.0f} GWh ({(a1 / a0 - 1) * 100:+.1f}%)", (rd["dias"], a1),
                    xytext=(-10, 12), textcoords="offset points", ha="right", fontsize=8, weight="bold", color=NAVY)
    ax.set_xlim(0.5, 31.5)
    ax.set_xlabel(f"Día de {MESES_C[rd['mes'] - 1].lower()}", fontsize=8)
    ax.set_ylabel("GWh acumulados", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title("Demanda acumulada del mes · mismo período del año anterior", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7.5, frameon=False, loc="upper left")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


# --------------------------------------------------------------------------- hidro de pasada
def leer_hidro():
    """{fecha: {hora: {pasada, regulacion, eolica}}}."""
    out = {}
    if F_REC.exists():
        with F_REC.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.setdefault(dt.date.fromisoformat(r["fecha"]), {})[r["hora"]] = {
                    k: float(r[k]) for k in RECURSOS if r.get(k) not in (None, "")}
    elif F_HID.exists():
        with F_HID.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.setdefault(dt.date.fromisoformat(r["fecha"]), {})[r["hora"]] = {"pasada": float(r["mw"])}
    return out


def guardar_hidro(h):
    DATA.mkdir(exist_ok=True)
    with F_REC.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "hora", *RECURSOS])
        for d in sorted(h):
            for hora in sorted(h[d], key=_hm_a_horas):
                w.writerow([d.isoformat(), hora, *(f"{h[d][hora][k]:.1f}" if k in h[d][hora] else "" for k in RECURSOS)])


def _completo(dia_h):
    return len(dia_h) >= 46 and all(all(k in r for k in RECURSOS) for r in dia_h.values())


def leer_vol():
    """{fecha: {(cuenca, embalse): (prom, final)}}; un día sin embalses queda como {} (ya consultado)."""
    out = {}
    if F_VOL.exists():
        with F_VOL.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d = out.setdefault(dt.date.fromisoformat(r["fecha"]), {})
                if r["embalse"] != "-":
                    d[(r["cuenca"], r["embalse"])] = (float(r["prom"]), float(r["final"]))
                elif r["cuenca"] != "-v2":      # marca antigua de "no publicado": se vuelve a intentar
                    out.pop(dt.date.fromisoformat(r["fecha"]), None)
    return out


def guardar_vol(v):
    DATA.mkdir(exist_ok=True)
    with F_VOL.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "cuenca", "embalse", "prom", "final"])
        for d in sorted(v):
            if not v[d]:
                w.writerow([d.isoformat(), "-v2", "-", "", ""])
            for (c, e), (pr, fi) in sorted(v[d].items()):
                w.writerow([d.isoformat(), c, e, f"{pr:.5f}", f"{fi:.5f}"])


def _un_anio_antes(d: dt.date, n=1):
    try:
        return d.replace(year=d.year - n)
    except ValueError:            # 29 de febrero
        return d.replace(year=d.year - n, day=28)


ANIOS_VOL = 3             # años anteriores a comparar en los volúmenes diarios


def _clave_emb(e):
    """Nombre de embalse comparable entre años (el COES cambia prefijos y mayúsculas)."""
    s = fc.norm(e)
    for w in ("EMBALSE", "EMBALSES", "PRESA", "RESERVORIO", "LAGO", "PULMON", "COMPENSACION"):
        s = s.replace(w, " ")
    return "".join(ch for ch in s if ch.isalnum())


def _vol_de(hojas):
    return {(r["cuenca"], r["embalse"]): (r["prom"], r["final"]) for r in fc.volumenes_dia(hojas)}


def actualizar_hidro(dia: dt.date, hojas_dia=None, presupuesto_s=600):
    """Rellena hidro de pasada (mes actual y mismo mes del año anterior) y volúmenes diarios de embalses
    (últimos VENTANA_VOL días y mismas fechas del año anterior) con una sola descarga del IEOD por día."""
    h, v = leer_hidro(), leer_vol()
    if hojas_dia:
        x = fc.recursos_dia(hojas_dia)
        if x:
            h[dia] = x
        y = _vol_de(hojas_dia)
        if y:
            v[dia] = y
    act = [dt.date(dia.year, dia.month, k) for k in range(1, dia.day + 1)]
    ant = [dt.date(dia.year - 1, dia.month, k) for k in range(1, calendar.monthrange(dia.year - 1, dia.month)[1] + 1)]
    vact = [dia - dt.timedelta(days=k) for k in range(VENTANA_VOL)]
    vant = [_un_anio_antes(d, n) for n in range(1, ANIOS_VOL + 1) for d in vact]
    falta_h = {d for d in act + ant if d not in h or not _completo(h[d])}
    falta_v = {d for d in vact + vant if d not in v}
    orden = list(dict.fromkeys(vact[:3] + act[::-1] + vact + vant + ant))
    t0 = time.time()
    for d in orden:
        if d not in falta_h and d not in falta_v:
            continue
        if time.time() - t0 > presupuesto_s:
            break
        try:
            hojas = fc.ieod_dia(d)
            if not hojas:
                if d < dia - dt.timedelta(days=5):
                    v.setdefault(d, {})      # no publicado: no reintentar en cada corrida
                continue
            x = fc.recursos_dia(hojas)
            if x:
                h[d] = x
            v[d] = _vol_de(hojas)
        except Exception as e:
            print("IEOD diario", d, e, file=sys.stderr)
    guardar_hidro(h)
    guardar_vol(v)
    pend = [d for d in act + ant if d not in h]
    return h, pend


def resumen_vol(dia: dt.date):
    """Volumen útil diario por cuenca (suma de los embalses que el IEOD reporta a diario) vs el año anterior.
    Chaglla es de regulación horaria: se usa el promedio del día; en el resto, el volumen al cierre del día."""
    v = leer_vol()
    out = {}
    for cuenca in sorted({c for d in v.values() for c, _ in d}):
        dias = sorted(d for d in v if d <= dia and any(c == cuenca for c, _ in v[d]))
        if not dias:
            continue
        ult = dias[-1]
        embs = sorted(e for c, e in v[ult] if c == cuenca)
        claves = [_clave_emb(e) for e in embs]
        k = 0 if cuenca == "Chaglla" else 1

        def valores(d):
            return {_clave_emb(e): x[k] for (c, e), x in v.get(d, {}).items() if c == cuenca}

        def total(d):
            x = valores(d)
            if not x or any(c not in x for c in claves):
                return None
            return round(sum(x[c] for c in claves), 3)

        series = {}
        for n in range(0, ANIOS_VOL + 1):
            pts = []
            for i in range(VENTANA_VOL - 1, -1, -1):
                d = ult - dt.timedelta(days=i)
                y = total(_un_anio_antes(d, n) if n else d)
                if y is not None:
                    pts.append([d.isoformat(), y])
            if pts:
                series[str(ult.year - n)] = pts
        t1, t0 = total(ult), total(_un_anio_antes(ult))
        x0 = valores(_un_anio_antes(ult))
        out[cuenca] = {
            "fecha": ult.isoformat(), "embalses": embs, "medida": "promedio del día" if k == 0 else "cierre del día",
            "total": t1, "anterior": t0, "var_pct": (t1 / t0 - 1) * 100 if t1 is not None and t0 else None,
            "detalle": [[e, round(v[ult][(cuenca, e)][k], 3),
                         round(x0[c], 3) if c in x0 else None] for e, c in zip(embs, claves)],
            "serie": series,
        }
    return out


def resumen_hidro(h, dia: dt.date, clave="pasada"):
    act, ant = dia.year, dia.year - 1
    diario = {a: {} for a in (act, ant)}
    serie = {a: [] for a in (act, ant)}
    for a in (act, ant):
        for k in range(1, calendar.monthrange(a, dia.month)[1] + 1):
            d = dt.date(a, dia.month, k)
            if d in h and (a == ant or d <= dia):
                hs = [x for x in sorted(h[d], key=_hm_a_horas) if clave in h[d][x]]
                if not hs:
                    continue
                diario[a][k] = round(sum(h[d][x][clave] for x in hs) / len(hs), 1)
                serie[a] += [[round(k - 1 + _hm_a_horas(x) / 24, 4), h[d][x][clave]] for x in hs]
    mtd = {}
    for a in (act, ant):
        vals = [v for k, v in diario[a].items() if k <= dia.day]
        mtd[a] = round(sum(vals) / len(vals), 1) if vals else None
    return {"diario": diario, "serie": serie, "mtd": mtd, "act": act, "ant": ant, "mes": dia.month, "dias": dia.day,
            "clave": clave}


NOMBRES_REC = {"pasada": "Generación hidroeléctrica de pasada", "regulacion": "Generación hidroeléctrica de embalse (regulación)",
               "eolica": "Generación eólica"}


def grafico_hidro(rh, ruta, plt):
    act, ant = rh["act"], rh["ant"]
    fig, ax = plt.subplots(figsize=(8.5, 4.2), dpi=160)
    for a, c in ((ant, C_ANT), (act, C_ACT)):
        s = rh["serie"][a]
        if s:
            ax.plot([p[0] + 1 for p in s], [p[1] for p in s], color=c, lw=0.6, alpha=0.25)
        d = rh["diario"][a]
        if d:
            ks = sorted(d)
            ax.plot([k + 0.5 for k in ks], [d[k] for k in ks], color=c, lw=2.4 if a == act else 1.8,
                    marker="o", ms=3, label=f"{a} · promedio diario")
    m1, m0 = rh["mtd"][act], rh["mtd"][ant]
    sub = ""
    if m1 and m0:
        sub = f"Promedio a la fecha: {m1:,.0f} MW ({act}) vs {m0:,.0f} MW ({ant}) · {(m1 / m0 - 1) * 100:+.0f}%"
    ax.set_xlim(1, 32)
    ax.set_xticks([k + 0.5 for k in range(1, 32, 2)], [str(k) for k in range(1, 32, 2)], fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("MW", fontsize=8)
    ax.set_xlabel(f"Día de {MESES_C[rh['mes'] - 1].lower()} (líneas tenues: cada 30 min)", fontsize=8)
    ax.set_title(f"{NOMBRES_REC.get(rh.get('clave', 'pasada'))}\n{sub}", fontsize=9.5)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7.5, frameon=False, loc="lower left", ncol=2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.text(0.99, 0.01, "Fuente: COES – IEOD (potencia por tipo de recurso)", ha="right", fontsize=6, color=GRIS)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)
    return ruta


# --------------------------------------------------------------------------- embalses semanales
def actualizar_embalses(hoy: dt.date):
    previo = json.loads(F_EMB.read_text(encoding="utf-8")) if F_EMB.exists() else None
    if previo and (hoy - dt.date.fromisoformat(previo["consultado"])).days < 2 and previo.get("bloques"):
        return previo
    try:
        semana, hojas = fc.informe_semanal_reciente()
        bloques = fc.embalses_semanales(hojas) if hojas else []
    except Exception as e:
        print("embalses semanales", e, file=sys.stderr)
        semana, bloques = None, []
    if not bloques:
        return previo or {"semana": None, "bloques": [], "consultado": hoy.isoformat()}
    datos = {"semana": semana, "consultado": hoy.isoformat(),
             "bloques": [{**b, "anios": {str(a): {str(k): v for k, v in s.items()} for a, s in b["anios"].items()}}
                         for b in bloques]}
    DATA.mkdir(exist_ok=True)
    F_EMB.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


def cuencas_seleccionadas(emb, diario=None):
    """Bloques de las cuencas de interés, en orden, con comparación de la última semana vs año anterior y,
    si el IEOD reporta a diario una parte representativa del volumen de la cuenca, el dato diario."""
    diario = diario or {}
    orden = [c for c, _ in fc.CUENCAS_SEMANAL]
    out = []
    for b in sorted([b for b in emb.get("bloques", []) if b.get("cuenca")], key=lambda b: orden.index(b["cuenca"])):
        anios = sorted(b["anios"], key=int)
        act = anios[-1]
        sem = max(int(k) for k in b["anios"][act])
        v1 = b["anios"][act].get(str(sem))
        ant = str(int(act) - 1)
        v0 = b["anios"].get(ant, {}).get(str(sem))
        centrales = fc.CENTRALES_CUENCA.get(b["cuenca"], [])
        di = diario.get(b["cuenca"])
        if di and di["total"] is not None and v1:
            di = {**di, "cobertura": di["total"] / v1}
            # Rímac/Santa: el IEOD solo trae reservorios de regulación horaria (las lagunas van en el semanal)
            if b["cuenca"] != "Chaglla" and di["cobertura"] < 0.5:
                di = {**di, "representativo": False}
            else:
                di = {**di, "representativo": True}
        out.append({**b, "semana": sem, "actual": v1, "anterior": v0,
                    "var_pct": (v1 / v0 - 1) * 100 if v1 is not None and v0 else None,
                    "centrales": centrales, "mw_total": round(sum(mw for _, mw in centrales), 1),
                    "diario": di, "solo_diario": b["cuenca"] == "Chaglla" and bool(di and di.get("serie"))})
    return out


def grafico_embalses(cuencas, ruta, plt):
    """Una fila por cuenca: gráfico de volumen útil semanal (izquierda) y centrales de la cuenca (derecha)."""
    if not cuencas:
        return None
    n = len(cuencas)
    fig = plt.figure(figsize=(8.5, 2.55 * n + 0.5), dpi=160)
    gs = fig.add_gridspec(n, 2, width_ratios=[3.1, 1], hspace=0.55, wspace=0.05)
    estilos = {0: (C_23, 1.0, "--"), 1: (C_24, 1.2, "-"), 2: (C_ANT, 1.8, "-"), 3: (C_ACT, 2.6, "-")}
    for idx, cu in enumerate(cuencas):
        ax = fig.add_subplot(gs[idx, 0])
        di = cu.get("diario") or {}
        if cu.get("solo_diario"):
            # Chaglla: embalse de regulación horaria → promedio diario del IEOD (la foto semanal no es representativa)
            anios = sorted(di["serie"], key=int)
            fechas = [dt.date.fromisoformat(f) for f, _ in di["serie"][anios[-1]]] or [dt.date.today()]
            f0 = fechas[0]
            anios = anios[-4:]
            for j, a in enumerate(anios):
                act = a == anios[-1]
                c, lw, ls = estilos[j + (4 - len(anios))]
                pts = di["serie"][a]
                ax.plot([(dt.date.fromisoformat(f) - f0).days for f, _ in pts], [y for _, y in pts],
                        color=c, lw=lw, ls=ls, marker="o" if act else None, ms=2.2, label=a)
            nd = (fechas[-1] - f0).days
            paso = max(1, nd // 10)
            ax.set_xticks(range(0, nd + 1, paso),
                          [(f0 + dt.timedelta(days=k)).strftime("%d/%m") for k in range(0, nd + 1, paso)])
            ax.set_xlim(-0.5, nd + 0.5)
            var = f" · {di['var_pct']:+.0f}% vs {int(anios[-1]) - 1}" if di.get("var_pct") is not None else ""
            ax.set_title(f"Embalse Chaglla (río Huallaga) — promedio del {dt.date.fromisoformat(di['fecha']):%d/%m}: "
                         f"{di['total']:,.2f} Hm3{var}", fontsize=8.5, color=NAVY, loc="left")
            ax.set_xlabel("Volumen útil promedio diario · IEOD", fontsize=7)
        else:
            anios = sorted(cu["anios"], key=int)[-4:]
            for j, a in enumerate(anios):
                c, lw, ls = estilos[j + (4 - len(anios))]
                s = cu["anios"][a]
                ks = sorted(int(k) for k in s)
                ax.plot(ks, [s[str(k)] for k in ks], color=c, lw=lw, ls=ls, label=a,
                        marker="o" if j == len(anios) - 1 else None, ms=2.2)
            var = f" · {cu['var_pct']:+.0f}% vs {int(anios[-1]) - 1}" if cu["var_pct"] is not None else ""
            ax.set_title(f"Cuenca del río {cu['cuenca']} — semana {cu['semana']}: {cu['actual']:,.1f} Hm3{var}",
                         fontsize=8.5, color=NAVY, loc="left")
            ax.set_xlim(1, 53)
            if di.get("representativo") and di.get("total") is not None:
                vd = f" ({di['var_pct']:+.0f}% vs año ant.)" if di.get("var_pct") is not None else ""
                ax.text(0.01, 0.04, f"Dato diario {dt.date.fromisoformat(di['fecha']):%d/%m}: {di['total']:,.1f} Hm3{vd}",
                        transform=ax.transAxes, fontsize=6.6, color=NAVY,
                        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#d0d4dc"))
            if idx == n - 1:
                ax.set_xlabel("Semana del año", fontsize=7)
        ax.set_ylim(bottom=0)
        ax.tick_params(labelsize=6.5)
        ax.grid(alpha=0.3)
        ax.set_ylabel("Hm3", fontsize=7)
        ax.legend(fontsize=6.5, frameon=False, loc="upper right", ncol=4)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        tx = fig.add_subplot(gs[idx, 1])
        tx.axis("off")
        if cu["centrales"]:
            lineas = [f"• {c} – {mw:g} MW" for c, mw in cu["centrales"]]
            tx.text(0.04, 0.98, "Centrales:", fontsize=7, weight="bold", color=NAVY, va="top")
            tx.text(0.04, 0.86, "\n".join(lineas), fontsize=6.4, color="#202124", va="top", linespacing=1.35)
            tx.text(0.04, 0.02, f"TOTAL = {cu['mw_total']:,.1f} MW", fontsize=7.2, weight="bold", color=NAVY,
                    va="bottom", bbox=dict(boxstyle="round,pad=0.3", fc="#fff3c4", ec="none"))
    fig.text(0.99, 0.005, "Fuente: COES – Informe de Evaluación Semanal (5.2) e IEOD (volúmenes diarios)", ha="right", fontsize=6, color=GRIS)
    fig.subplots_adjust(left=0.07, right=0.99, top=1 - 0.3 / (2.55 * n + 0.5), bottom=0.6 / (2.55 * n + 0.5))
    fig.savefig(ruta)
    plt.close(fig)
    return ruta
