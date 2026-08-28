#!/usr/bin/env python3
"""
Recordatorios de seguimiento de la cartera MX, publicados en un canal de Teams.

Los puntos viven en seguimiento.json (versionado en el repo). El script los
lista, los da de alta, los cierra y publica una tarjeta en Teams con los que
siguen abiertos — vencidos primero.

Uso:
    python3 scripts/recordatorios.py                      # lista los abiertos
    python3 scripts/recordatorios.py listar --todos       # incluye los cerrados
    python3 scripts/recordatorios.py agregar \
        --titulo "Cerrar plan de adopción con Grupo Lumo" \
        --cuenta "Grupo Lumo" --responsable "Fernanda" \
        --compromiso 2026-09-03 --origen "Granola — QBR 27 ago"
    python3 scripts/recordatorios.py cerrar grupo-lumo-plan-de-adopcion
    python3 scripts/recordatorios.py publicar --dry-run   # muestra la tarjeta
    python3 scripts/recordatorios.py publicar             # la manda a Teams

El webhook de Teams se busca, en este orden:
    1. --webhook <url>
    2. la variable de entorno TEAMS_WEBHOOK_URL
    3. el archivo ~/.config/monitor-cartera/teams-webhook

Nunca se guarda la URL en el repo: quien la tenga puede publicar en el canal.

Solo usa la librería estándar de Python 3 — no hay que instalar nada.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUNTOS = REPO / "seguimiento.json"
WEBHOOK_LOCAL = Path.home() / ".config" / "monitor-cartera" / "teams-webhook"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

MAX_EN_TARJETA = 12          # más que esto y Teams corta la tarjeta
PROXIMO_EN_DIAS = 3          # qué cuenta como "urge" además de lo vencido

VERDE, ROJO, AMARILLO, GRIS, NEGRITA, FIN_COLOR = (
    "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[1m", "\033[0m"
) if sys.stdout.isatty() else ("", "", "", "", "", "")


def ok(msg):     print(f"  {VERDE}✓{FIN_COLOR} {msg}")
def aviso(msg):  print(f"  {AMARILLO}⚠{FIN_COLOR}  {msg}")
def dato(msg):   print(f"    {GRIS}{msg}{FIN_COLOR}")
def titulo(msg): print(f"\n{NEGRITA}{msg}{FIN_COLOR}")


def morir(msg, sugerencia=None):
    print(f"\n{ROJO}✗ {msg}{FIN_COLOR}")
    if sugerencia:
        print(f"  {sugerencia}")
    sys.exit(1)


# ------------------------------------------------------------------ el archivo

def cargar():
    if not PUNTOS.exists():
        return {"puntos": []}
    try:
        datos = json.loads(PUNTOS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        morir(f"{PUNTOS.name} no es JSON válido: {e}")
    datos.setdefault("puntos", [])
    return datos


def guardar(datos):
    PUNTOS.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def slug(texto):
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:48] or "punto"


def id_libre(datos, base):
    usados = {p["id"] for p in datos["puntos"]}
    if base not in usados:
        return base
    n = 2
    while f"{base}-{n}" in usados:
        n += 1
    return f"{base}-{n}"


def buscar(datos, ident):
    exactos = [p for p in datos["puntos"] if p["id"] == ident]
    if exactos:
        return exactos[0]
    parciales = [p for p in datos["puntos"] if ident.lower() in p["id"]]
    if len(parciales) == 1:
        return parciales[0]
    if len(parciales) > 1:
        morir(f"'{ident}' coincide con varios puntos:",
              "  " + "\n  ".join(p["id"] for p in parciales))
    morir(f"no existe ningún punto con id '{ident}'",
          "Corre 'python3 scripts/recordatorios.py' para ver los ids.")


# -------------------------------------------------------------------- fechas

def leer_fecha(texto):
    """Acepta YYYY-MM-DD, 'hoy', o desplazamientos tipo '+7d' / '+2s'."""
    if not texto:
        return None
    texto = texto.strip().lower()
    if texto == "hoy":
        return dt.date.today().isoformat()
    m = re.fullmatch(r"\+(\d+)([ds])", texto)
    if m:
        n = int(m.group(1)) * (7 if m.group(2) == "s" else 1)
        return (dt.date.today() + dt.timedelta(days=n)).isoformat()
    try:
        return dt.date.fromisoformat(texto).isoformat()
    except ValueError:
        morir(f"no entiendo la fecha '{texto}'",
              "Usa YYYY-MM-DD, 'hoy', '+7d' o '+2s'.")


def en_largo(fecha):
    return f"{DIAS[fecha.weekday()]} {fecha.day} de {MESES[fecha.month - 1]}"


def urgencia(punto, hoy):
    """vencido | urge | pendiente | sin-fecha"""
    if not punto.get("compromiso"):
        return "sin-fecha"
    dias = (dt.date.fromisoformat(punto["compromiso"]) - hoy).days
    if dias < 0:
        return "vencido"
    if dias <= PROXIMO_EN_DIAS:
        return "urge"
    return "pendiente"


ORDEN = {"vencido": 0, "urge": 1, "pendiente": 2, "sin-fecha": 3}


def ordenar(puntos, hoy):
    return sorted(
        puntos,
        key=lambda p: (ORDEN[urgencia(p, hoy)], p.get("compromiso") or "9999-12-31"),
    )


def etiqueta(punto, hoy):
    u = urgencia(punto, hoy)
    if u == "sin-fecha":
        return "sin fecha"
    fecha = dt.date.fromisoformat(punto["compromiso"])
    dias = (fecha - hoy).days
    if dias < 0:
        return f"vencido hace {-dias} día{'s' if dias != -1 else ''} ({en_largo(fecha)})"
    if dias == 0:
        return f"vence hoy ({en_largo(fecha)})"
    if dias == 1:
        return f"vence mañana ({en_largo(fecha)})"
    return f"en {dias} días ({en_largo(fecha)})"


# --------------------------------------------------------------------- git

def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        morir(f"git {' '.join(args)} falló:\n{r.stderr.strip()}")
    return r.stdout.strip()


def versionar(mensaje, push):
    git("add", str(PUNTOS.relative_to(REPO)))
    if not git("diff", "--cached", "--name-only"):
        dato("sin cambios que commitear")
        return
    git("commit", "-m", mensaje)
    ok(f"commit: {mensaje}")
    if push:
        git("push")
        ok("pusheado a main")
    else:
        dato("no se pusheó (--no-push)")


# ------------------------------------------------------------------ comandos

def cmd_listar(args):
    datos = cargar()
    hoy = dt.date.today()
    puntos = datos["puntos"]
    if not args.todos:
        puntos = [p for p in puntos if p.get("estado") != "cerrado"]
    if not puntos:
        titulo("Seguimiento cartera MX")
        dato("no hay puntos abiertos")
        return

    titulo(f"Seguimiento cartera MX — {en_largo(hoy)}")
    for p in ordenar(puntos, hoy):
        u = urgencia(p, hoy)
        color = {"vencido": ROJO, "urge": AMARILLO}.get(u, GRIS)
        cerrado = p.get("estado") == "cerrado"
        marca = f"{GRIS}✓{FIN_COLOR}" if cerrado else f"{color}●{FIN_COLOR}"
        print(f"\n  {marca} {NEGRITA}{p['titulo']}{FIN_COLOR}")
        meta = [x for x in (p.get("cuenta"), p.get("responsable")) if x]
        if meta:
            dato(" · ".join(meta))
        dato(f"cerrado el {p.get('cerrado')}" if cerrado else etiqueta(p, hoy))
        if p.get("origen"):
            dato(f"origen: {p['origen']}")
        dato(f"id: {p['id']}")

    abiertos = [p for p in datos["puntos"] if p.get("estado") != "cerrado"]
    vencidos = [p for p in abiertos if urgencia(p, hoy) == "vencido"]
    print()
    ok(f"{len(abiertos)} abierto{'s' if len(abiertos) != 1 else ''}"
       + (f", {len(vencidos)} vencido{'s' if len(vencidos) != 1 else ''}" if vencidos else ""))


def cmd_agregar(args):
    datos = cargar()
    hoy = dt.date.today()
    punto = {
        "id": id_libre(datos, slug(f"{args.cuenta or ''} {args.titulo}".strip())),
        "titulo": args.titulo,
        "cuenta": args.cuenta,
        "responsable": args.responsable,
        "compromiso": leer_fecha(args.compromiso),
        "origen": args.origen,
        "detalle": args.detalle,
        "estado": "abierto",
        "creado": hoy.isoformat(),
        "cerrado": None,
    }
    datos["puntos"].append(punto)

    titulo("Nuevo punto de seguimiento")
    print(f"\n  {NEGRITA}{punto['titulo']}{FIN_COLOR}")
    for campo in ("cuenta", "responsable", "origen"):
        if punto[campo]:
            dato(f"{campo}: {punto[campo]}")
    dato(etiqueta(punto, hoy))
    dato(f"id: {punto['id']}")
    print()

    if args.dry_run:
        aviso("--dry-run: no se guardó nada")
        return
    guardar(datos)
    ok(f"guardado en {PUNTOS.name}")
    versionar(f"seguimiento: {punto['titulo']}", push=not args.no_push)


def cmd_cerrar(args):
    datos = cargar()
    punto = buscar(datos, args.id)
    if punto.get("estado") == "cerrado":
        aviso(f"'{punto['titulo']}' ya estaba cerrado el {punto.get('cerrado')}")
        return
    punto["estado"] = "cerrado"
    punto["cerrado"] = dt.date.today().isoformat()
    if args.nota:
        punto["detalle"] = ((punto.get("detalle") or "") + f"\nCierre: {args.nota}").strip()

    titulo("Cerrar punto")
    print(f"\n  {NEGRITA}{punto['titulo']}{FIN_COLOR}")
    dato(f"id: {punto['id']}")
    print()
    if args.dry_run:
        aviso("--dry-run: no se guardó nada")
        return
    guardar(datos)
    ok("marcado como cerrado")
    versionar(f"seguimiento: cierra {punto['titulo']}", push=not args.no_push)


def cmd_reabrir(args):
    datos = cargar()
    punto = buscar(datos, args.id)
    punto["estado"] = "abierto"
    punto["cerrado"] = None
    if args.compromiso:
        punto["compromiso"] = leer_fecha(args.compromiso)
    if args.dry_run:
        aviso("--dry-run: no se guardó nada")
        return
    guardar(datos)
    ok(f"reabierto: {punto['titulo']}")
    versionar(f"seguimiento: reabre {punto['titulo']}", push=not args.no_push)


# ------------------------------------------------------------------- Teams

def resolver_webhook(explicito):
    if explicito:
        return explicito.strip(), "--webhook"
    if os.environ.get("TEAMS_WEBHOOK_URL"):
        return os.environ["TEAMS_WEBHOOK_URL"].strip(), "TEAMS_WEBHOOK_URL"
    if WEBHOOK_LOCAL.exists():
        url = WEBHOOK_LOCAL.read_text(encoding="utf-8").strip()
        if url:
            return url, str(WEBHOOK_LOCAL)
    morir(
        "no encuentro el webhook del canal de Teams",
        "Créalo en el canal (··· → Workflows → 'Publicar en un canal cuando se\n"
        f"  reciba una solicitud de webhook') y guarda la URL en:\n"
        f"    {WEBHOOK_LOCAL}",
    )


def bloque_punto(punto, hoy):
    u = urgencia(punto, hoy)
    estilo = {"vencido": "attention", "urge": "warning"}.get(u, "default")
    hechos = []
    for nombre, valor in (
        ("Cuenta", punto.get("cuenta")),
        ("Responsable", punto.get("responsable")),
        ("Compromiso", etiqueta(punto, hoy)),
        ("Origen", punto.get("origen")),
    ):
        if valor:
            hechos.append({"title": nombre, "value": valor})

    cuerpo = [{
        "type": "TextBlock", "text": punto["titulo"],
        "weight": "Bolder", "wrap": True,
    }]
    if hechos:
        cuerpo.append({"type": "FactSet", "facts": hechos})
    if punto.get("detalle"):
        cuerpo.append({
            "type": "TextBlock", "text": punto["detalle"],
            "wrap": True, "isSubtle": True, "size": "Small",
        })
    return {
        "type": "Container", "style": estilo, "bleed": False,
        "spacing": "Medium", "items": cuerpo,
    }


def construir_tarjeta(puntos, hoy, mostrados, ocultos):
    vencidos = sum(1 for p in puntos if urgencia(p, hoy) == "vencido")
    urgen = sum(1 for p in puntos if urgencia(p, hoy) == "urge")
    resumen = [f"{len(puntos)} abierto{'s' if len(puntos) != 1 else ''}"]
    if vencidos:
        resumen.append(f"{vencidos} vencido{'s' if vencidos != 1 else ''}")
    if urgen:
        resumen.append(f"{urgen} por vencer")

    cuerpo = [
        {"type": "TextBlock", "text": "🔔 Seguimiento — Cartera MX",
         "size": "Large", "weight": "Bolder", "wrap": True},
        {"type": "TextBlock", "text": f"{en_largo(hoy).capitalize()} · " + " · ".join(resumen),
         "isSubtle": True, "spacing": "None", "wrap": True},
    ]
    cuerpo += [bloque_punto(p, hoy) for p in mostrados]
    if ocultos:
        cuerpo.append({
            "type": "TextBlock", "size": "Small", "isSubtle": True, "wrap": True,
            "text": f"…y {ocultos} punto{'s' if ocultos != 1 else ''} más en seguimiento.json",
        })

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "msteams": {"width": "Full"},
                "body": cuerpo,
            },
        }],
    }


def cmd_publicar(args):
    datos = cargar()
    hoy = dt.date.today()
    puntos = [p for p in datos["puntos"] if p.get("estado") != "cerrado"]
    if args.solo_vencidos:
        puntos = [p for p in puntos if urgencia(p, hoy) == "vencido"]

    if not puntos:
        titulo("Nada que publicar")
        dato("no hay puntos abiertos" + (" y vencidos" if args.solo_vencidos else ""))
        return

    puntos = ordenar(puntos, hoy)
    mostrados, ocultos = puntos[:args.max], max(0, len(puntos) - args.max)
    if ocultos:
        aviso(f"la tarjeta muestra {args.max} de {len(puntos)} puntos; "
              f"{ocultos} quedan fuera")

    tarjeta = construir_tarjeta(puntos, hoy, mostrados, ocultos)

    if args.dry_run:
        titulo("Tarjeta que se mandaría a Teams")
        print(json.dumps(tarjeta, ensure_ascii=False, indent=2))
        print()
        aviso("--dry-run: no se envió nada")
        return

    url, fuente = resolver_webhook(args.webhook)
    if "logic.azure" not in url and "webhook.office.com" not in url:
        aviso(f"la URL de {fuente} no parece un webhook de Teams; se intenta igual")

    cuerpo = json.dumps(tarjeta, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=cuerpo, method="POST",
        headers={"Content-Type": "application/json"},
    )
    titulo("Publicando en Teams")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            codigo = r.status
    except urllib.error.HTTPError as e:
        morir(f"Teams respondió {e.code}: {e.read().decode('utf-8', 'replace')[:400]}",
              "Si es 401/403, el Workflow del canal se desactivó o la URL caducó: vuelve a crearlo.")
    except urllib.error.URLError as e:
        morir(f"no se pudo llegar al webhook: {e.reason}")

    ok(f"publicado ({codigo}) — {len(mostrados)} punto{'s' if len(mostrados) != 1 else ''} en la tarjeta")
    dato(f"webhook tomado de {fuente}")


# ---------------------------------------------------------------------- CLI

def main():
    p = argparse.ArgumentParser(
        description="Recordatorios de seguimiento de la cartera MX en Teams.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd")

    def con_git(sp):
        sp.add_argument("--no-push", action="store_true", help="commitea pero no pushea")
        sp.add_argument("--dry-run", action="store_true", help="no escribe nada")

    l = sub.add_parser("listar", help="lista los puntos (por defecto)")
    l.add_argument("--todos", action="store_true", help="incluye los cerrados")
    l.set_defaults(func=cmd_listar)

    a = sub.add_parser("agregar", help="da de alta un punto de seguimiento")
    a.add_argument("--titulo", required=True)
    a.add_argument("--cuenta", help="empresa o cuenta involucrada")
    a.add_argument("--responsable")
    a.add_argument("--compromiso", help="YYYY-MM-DD, 'hoy', '+7d' o '+2s'")
    a.add_argument("--origen", help="de dónde salió: reunión, correo, Granola…")
    a.add_argument("--detalle")
    con_git(a)
    a.set_defaults(func=cmd_agregar)

    c = sub.add_parser("cerrar", help="marca un punto como resuelto")
    c.add_argument("id")
    c.add_argument("--nota", help="cómo se resolvió")
    con_git(c)
    c.set_defaults(func=cmd_cerrar)

    r = sub.add_parser("reabrir", help="vuelve a abrir un punto cerrado")
    r.add_argument("id")
    r.add_argument("--compromiso", help="nueva fecha")
    con_git(r)
    r.set_defaults(func=cmd_reabrir)

    pub = sub.add_parser("publicar", help="manda la tarjeta al canal de Teams")
    pub.add_argument("--dry-run", action="store_true", help="imprime la tarjeta sin enviarla")
    pub.add_argument("--solo-vencidos", action="store_true")
    pub.add_argument("--max", type=int, default=MAX_EN_TARJETA)
    pub.add_argument("--webhook", help="URL del webhook (si no, env o archivo local)")
    pub.set_defaults(func=cmd_publicar)

    args = p.parse_args()
    if not args.cmd:
        args = p.parse_args(["listar"])
    args.func(args)


if __name__ == "__main__":
    main()
