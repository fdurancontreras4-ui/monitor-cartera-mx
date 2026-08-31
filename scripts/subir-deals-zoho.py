#!/usr/bin/env python3
"""
Publica el pipeline de Zoho CRM (módulo Deals) en el Monitor de Cartera MX.

No se conecta a Zoho directamente — este script no tiene ni debe tener
credenciales de Zoho, porque el repo es público. La lectura de Zoho la hace
quien invoca este script (la skill /deals-zoho o la tarea programada
deals-mx-diario, ambas corriendo con el conector MCP de Zoho ya autorizado),
que vuelca los registros crudos a un JSON y se lo pasa a este script.

Este script se limita a: validar que los registros son los que deberían ser
(dueño, territorio y KAM correctos), compararlos contra el pipeline vigente,
darle forma a deals-mx.json y publicarlo (commit + push a main).

Criterio de Zoho (módulo Deals, vía searchRecords):
    ((Owner:equals:3525045000270215054)
     and((KAM:equals:Dafne de la Rosa)
      or(KAM:equals:Raúl Campos)
      or(KAM:equals:Karla Patiño)))

Uso:
    python3 scripts/subir-deals-zoho.py /tmp/deals-zoho-raw.json
    python3 scripts/subir-deals-zoho.py /tmp/deals-zoho-raw.json --dry-run
    python3 scripts/subir-deals-zoho.py /tmp/deals-zoho-raw.json --no-push

Formato esperado del JSON de entrada: una lista plana de registros crudos de
Zoho (uno por deal, todas las páginas ya combinadas), cada uno con al menos
los campos: id, Deal_Name, Account_Name{name,id}, KAM, Owner{name,id},
Territorio, Stage, Producto_Soluci_n, Valor_del_trato_Global, Correo_KAM,
Created_Time, Modified_Time.

Solo usa la librería estándar de Python 3 — no hay que instalar nada.
"""

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESTINO = REPO / "deals-mx.json"

KAM_OWNER_ID = "3525045000270215054"
KAM_OWNER_NOMBRE = "KAM México"
TERRITORIO_ESPERADO = "México"
KAMS_VALIDOS = ["Dafne de la Rosa", "Raúl Campos", "Karla Patiño"]

# Orden real del pipeline en Zoho — los cerrados van al final.
ORDEN_ETAPAS = [
    "1. Trato Creado", "2. Primera Reunion Realizada", "3. En Levantamiento",
    "4. Propuesta Enviada / En Negociación", "5. Piloto", "6. Listo para Cierre",
    "7. Implementando", "8. Facturando", "Facturación congelada", "Cierre Perdido",
]
ETAPAS_CERRADAS = {"Cierre Perdido", "Facturación congelada"}

TOTAL_MIN, TOTAL_MAX = 150, 1200   # rango sano — hoy son ~429 deals
DELTA_MAX = 0.25                   # 25% de variación de un corrida a otra
SOLAPAMIENTO_MIN = 0.70            # 70% de los IDs deben repetirse

VERDE, ROJO, AMARILLO, GRIS, NEGRITA, FIN_COLOR = (
    "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[1m", "\033[0m"
) if sys.stdout.isatty() else ("", "", "", "", "", "")


def ok(msg):    print(f"  {VERDE}✓{FIN_COLOR} {msg}")
def aviso(msg): print(f"  {AMARILLO}⚠{FIN_COLOR}  {msg}")
def dato(msg):  print(f"    {GRIS}{msg}{FIN_COLOR}")
def titulo(msg):print(f"\n{NEGRITA}{msg}{FIN_COLOR}")


def morir(msg, sugerencia=None):
    print(f"\n{ROJO}✗ {msg}{FIN_COLOR}")
    if sugerencia:
        print(f"  {sugerencia}")
    sys.exit(1)


# ---------------------------------------------------------------- lectura y forma

def leer_crudos(path):
    try:
        crudos = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        morir(f"{path} no es JSON válido: {e}")
    if not isinstance(crudos, list):
        morir(f"{path} debería ser una lista de deals, no {type(crudos).__name__}.",
              "¿Se pasó por error la respuesta completa de searchRecords en vez de solo la lista `data`?")
    if not crudos:
        morir(f"{path} está vacío — no hay deals que publicar.")
    return crudos


def dar_forma(r):
    cuenta = r.get("Account_Name") or {}
    owner = r.get("Owner") or {}
    return {
        "id": str(r.get("id", "")),
        "trato": (r.get("Deal_Name") or "").strip(),
        "cuenta": (cuenta.get("name") or "").strip(),
        "cuenta_id": str(cuenta.get("id", "")),
        "kam": (r.get("KAM") or "").strip(),
        "correo_kam": r.get("Correo_KAM") or "",
        "etapa": (r.get("Stage") or "").strip(),
        "cerrado": (r.get("Stage") or "").strip() in ETAPAS_CERRADAS,
        "producto": (r.get("Producto_Soluci_n") or "").strip(),
        "valor": r.get("Valor_del_trato_Global"),
        "owner": (owner.get("name") or "").strip(),
        "creado": r.get("Created_Time"),
        "modificado": r.get("Modified_Time"),
    }


def orden_etapa(etapa):
    try:
        return ORDEN_ETAPAS.index(etapa)
    except ValueError:
        return len(ORDEN_ETAPAS)  # etapas desconocidas al final, no rompen el sort


# ---------------------------------------------------------------- validación

def validar(crudos):
    titulo("Validando deals de Zoho")

    dueños = {}
    territorios = {}
    kams = {}
    for r in crudos:
        o = (r.get("Owner") or {}).get("name") or "(sin owner)"
        dueños[o] = dueños.get(o, 0) + 1
        t = r.get("Territorio") or "(sin territorio)"
        territorios[t] = territorios.get(t, 0) + 1
        k = (r.get("KAM") or "").strip() or "(sin KAM)"
        kams[k] = kams.get(k, 0) + 1

    ajenos = {o: n for o, n in dueños.items() if o != KAM_OWNER_NOMBRE}
    if ajenos:
        detalle = ", ".join(f"{o}: {n}" for o, n in sorted(ajenos.items(), key=lambda x: -x[1])[:5])
        morir(f"Hay deals que no son de {KAM_OWNER_NOMBRE} ({detalle}).",
              "Revisa el criterio de búsqueda: Owner:equals:" + KAM_OWNER_ID)
    ok(f"{len(crudos)} deals, todos con Owner = {KAM_OWNER_NOMBRE}")

    ajenos_t = {t: n for t, n in territorios.items() if t != TERRITORIO_ESPERADO}
    if ajenos_t:
        detalle = ", ".join(f"{t}: {n}" for t, n in sorted(ajenos_t.items(), key=lambda x: -x[1])[:5])
        morir(f"Hay deals fuera de {TERRITORIO_ESPERADO} ({detalle}).")
    ok(f"todos con Territorio = {TERRITORIO_ESPERADO}")

    ajenos_k = {k: n for k, n in kams.items() if k not in KAMS_VALIDOS}
    if ajenos_k:
        detalle = ", ".join(f"{k}: {n}" for k, n in sorted(ajenos_k.items(), key=lambda x: -x[1])[:5])
        morir(f"Hay deals con KAM fuera de {KAMS_VALIDOS} ({detalle}).",
              "Puede ser un deal reasignado en Zoho, o un problema de codificación del nombre.")
    for k in KAMS_VALIDOS:
        ok(f"{kams.get(k, 0)} deals de {k}")

    if not (TOTAL_MIN <= len(crudos) <= TOTAL_MAX):
        morir(f"{len(crudos)} deals está fuera del rango esperado ({TOTAL_MIN}–{TOTAL_MAX}).",
              "O el fetch quedó incompleto (revisa la paginación), o el pipeline cambió muchísimo.")

    ids = {str(r.get("id", "")) for r in crudos if r.get("id")}
    if len(ids) != len(crudos):
        aviso(f"{len(crudos) - len(ids)} deals duplicados o sin id — se van a colapsar por id")
    return ids


def comparar(deals, ids_nuevos, vigente_path):
    """Diff contra el pipeline publicado. Devuelve False si es idéntico."""
    if not vigente_path.exists():
        aviso("No hay deals-mx.json previo con el cual comparar — se publica sin diff")
        return True

    anterior = json.loads(vigente_path.read_text(encoding="utf-8"))
    previos = {d["id"]: d for d in anterior.get("deals", [])}
    ids_previos = set(previos)

    titulo("Comparando contra el pipeline publicado")

    solape = len(ids_nuevos & ids_previos) / max(len(ids_previos), 1)
    if solape < SOLAPAMIENTO_MIN:
        morir(f"Solo {solape:.0%} de los deals coinciden con lo publicado.",
              "No parece el mismo pipeline — revisa el criterio de búsqueda. Si es real, corre con --forzar.")
    ok(f"{solape:.0%} de los deals coinciden con lo publicado")

    delta = (len(deals) - len(previos)) / max(len(previos), 1)
    if abs(delta) > DELTA_MAX:
        morir(f"El total de deals cambió {delta:+.0%} ({len(previos)} → {len(deals)}).",
              "Es mucho para una corrida. Si el cambio es real, corre de nuevo con --forzar.")
    ok(f"{len(previos)} → {len(deals)} deals ({len(deals) - len(previos):+d})")

    actuales = {d["id"]: d for d in deals}
    if actuales == previos:
        aviso("El pipeline es idéntico al publicado (mismos deals, mismas etapas)")
        return False

    nuevos = ids_nuevos - ids_previos
    cerrados_o_movidos = ids_previos - ids_nuevos
    if nuevos:
        nombres = sorted(actuales[i]["trato"] or actuales[i]["cuenta"] for i in nuevos)
        dato(f"nuevos ({len(nuevos)}): " + ", ".join(nombres[:6]) + (" …" if len(nuevos) > 6 else ""))
    if cerrados_o_movidos:
        nombres = sorted(previos[i]["trato"] or previos[i]["cuenta"] for i in cerrados_o_movidos)
        dato(f"salieron del pipeline ({len(cerrados_o_movidos)}): "
             + ", ".join(nombres[:6]) + (" …" if len(cerrados_o_movidos) > 6 else ""))

    cambios_etapa = [
        (previos[i]["trato"] or previos[i]["cuenta"], previos[i]["etapa"], actuales[i]["etapa"])
        for i in (ids_nuevos & ids_previos)
        if previos[i]["etapa"] != actuales[i]["etapa"]
    ]
    if cambios_etapa:
        dato(f"cambiaron de etapa ({len(cambios_etapa)}):")
        for nombre, antes, ahora in cambios_etapa[:10]:
            dato(f"  {nombre}: {antes} → {ahora}")
        if len(cambios_etapa) > 10:
            dato(f"  … {len(cambios_etapa) - 10} más")

    def por_etapa(rs):
        c = {}
        for r in rs.values():
            c[r["etapa"]] = c.get(r["etapa"], 0) + 1
        return c
    antes, ahora = por_etapa(previos), por_etapa(actuales)
    print()
    for etapa in sorted(set(antes) | set(ahora), key=orden_etapa):
        a, b = antes.get(etapa, 0), ahora.get(etapa, 0)
        d = b - a
        marca = f"  ({'+' if d > 0 else ''}{d})" if d else ""
        dato(f"{etapa:<40} {a:>4} → {b:>4}{marca}")
    return True


# ---------------------------------------------------------------- publicación

def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        morir(f"git {' '.join(args)} falló:\n{r.stderr.strip()}")
    return r.stdout.strip()


def publicar(payload, dry_run, push, forzar_commit_vacio=False):
    titulo("Publicando")
    if dry_run:
        dato(f"git add {DESTINO.name}")
        dato(f"git commit -m 'pipeline: sincroniza deals de Zoho'")
        dato("git push origin main" if push else "(sin push)")
        return

    DESTINO.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok(f"escrito {DESTINO.name}")

    git("add", "--", DESTINO.name)
    if not git("diff", "--cached", "--name-only") and not forzar_commit_vacio:
        morir("No hay nada que commitear — el archivo ya estaba así.")
    mensaje = f"pipeline: sincroniza deals de Zoho ({payload['total']} deals, {payload['generado'][:10]})"
    git("-c", "commit.gpgsign=false", "commit", "-m", mensaje)
    ok(f"commit: {git('log', '--oneline', '-1')}")
    if push:
        git("push", "origin", "main")
        ok("push a origin/main hecho")
        print(f"\n  El tablero se actualiza en ~1 min: "
              f"https://fdurancontreras4-ui.github.io/monitor-cartera-mx/")
    else:
        aviso("Sin push (--no-push). Cuando quieras: git push origin main")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Publica el pipeline de Zoho (Deals) en el Monitor de Cartera MX.")
    ap.add_argument("archivo", help="JSON con los deals crudos de Zoho (lista plana, todas las páginas combinadas)")
    ap.add_argument("--dry-run", action="store_true", help="valida y muestra el diff sin escribir ni commitear")
    ap.add_argument("--no-push", action="store_true", help="commitea pero no pushea")
    ap.add_argument("--forzar", action="store_true", help="publica aunque el solape/delta con lo previo sea sospechoso")
    args = ap.parse_args()

    origen = Path(args.archivo).expanduser()
    if not origen.exists():
        morir(f"No existe el archivo {origen}")

    crudos = leer_crudos(origen)

    if args.forzar:
        global TOTAL_MIN, TOTAL_MAX, SOLAPAMIENTO_MIN, DELTA_MAX
        TOTAL_MIN, TOTAL_MAX, SOLAPAMIENTO_MIN, DELTA_MAX = 1, 10**9, 0.0, 10**9

    ids = validar(crudos)
    deals = [dar_forma(r) for r in crudos]
    deals.sort(key=lambda d: (d["kam"], orden_etapa(d["etapa"]), -(d["valor"] or 0)))

    distinto = comparar(deals, ids, DESTINO)
    if not distinto and not args.forzar:
        morir("El pipeline no cambió desde la última publicación — no hay nada que subir.",
              "Si de verdad quieres forzar la publicación, corre de nuevo con --forzar.")

    ahora = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "generado": ahora,
        "fuente": "Zoho CRM · Deals",
        "propietario": KAM_OWNER_NOMBRE,
        "territorio": TERRITORIO_ESPERADO,
        "kams": KAMS_VALIDOS,
        "total": len(deals),
        "deals": deals,
    }

    publicar(payload, args.dry_run, push=not args.no_push, forzar_commit_vacio=args.forzar)


if __name__ == "__main__":
    main()
