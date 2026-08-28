#!/usr/bin/env python3
"""
Sube el reporte de salud semanal al repo del Monitor de Cartera MX.

Hace en un solo comando lo que antes era manual:
  1. encuentra el .xlsx recién descargado (o el que le pases como argumento)
  2. valida que sea el reporte correcto y que esté filtrado a México
  3. lo compara contra la semana vigente y te muestra qué cambió
  4. lo renombra a salud-mx-DDmes.xlsx y lo copia al repo
  5. actualiza salud_semanas.json (vigente + archivos)
  6. commitea y hace push a main

Uso:
    python3 scripts/subir-salud.py                    # busca el archivo en ~/Downloads
    python3 scripts/subir-salud.py ~/Downloads/x.xlsx # archivo explícito
    python3 scripts/subir-salud.py --dry-run          # muestra todo sin escribir nada
    python3 scripts/subir-salud.py --fecha 2026-08-24 # fecha distinta a hoy
    python3 scripts/subir-salud.py --no-push          # commitea pero no pushea
    python3 scripts/subir-salud.py --forzar           # sobreescribe si el archivo ya existe

Solo usa la librería estándar de Python 3 — no hay que instalar nada.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parent.parent
MANIFIESTO = REPO / "salud_semanas.json"
DESCARGAS = Path.home() / "Downloads"

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

HOJA = "Directorio"
# Columnas que el dashboard necesita sí o sí (el reporte gana columnas con el tiempo:
# 22 en junio, 25 en agosto — por eso se valida por nombre, no por cantidad ni por posición).
COLUMNAS_REQUERIDAS = [
    "ID Empresa", "Nombre Empresa", "Unidad de Negocio", "Segmento",
    "% Adopción", "% Variación", "NPS", "Incidencias 30 días",
    "Score Total", "Categoría", "CSS",
]
UNIDAD_ESPERADA = "México"
NOMBRE_EXPORT = "directorio-empresas"   # el tablero siempre exporta con este nombre
FILAS_MIN, FILAS_MAX = 350, 900      # rango sano de la cartera MX (~500 cuentas)
DELTA_FILAS_MAX = 0.15               # 15% de variación semanal como tope razonable
SOLAPAMIENTO_MIN = 0.85              # 85% de los IDs deben coincidir con la semana anterior

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

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


# ---------------------------------------------------------------- lectura xlsx

def _col_a_indice(ref):
    """'AB12' -> 27 (índice 0-based de la columna AB)."""
    letras = re.match(r"([A-Z]+)", ref).group(1)
    n = 0
    for c in letras:
        n = n * 26 + (ord(c) - 64)
    return n - 1


def leer_hoja(path, nombre_hoja):
    """Devuelve (encabezado, filas) de la hoja pedida. Respeta las celdas vacías:
    el reporte omite las celdas sin valor, así que las filas se arman por
    referencia de columna (A, B, C…) y no por orden de aparición."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        morir(f"No se pudo abrir {path.name} como xlsx: {e}")

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    hojas = {h.get("name"): h.get(NS_R + "id") for h in wb.iter(NS + "sheet")}
    if nombre_hoja not in hojas:
        morir(f"{path.name} no tiene la hoja «{nombre_hoja}» (tiene: {', '.join(hojas) or 'ninguna'}).",
              "¿Seguro que es el reporte de salud y no otra descarga?")

    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    destino = {r.get("Id"): r.get("Target") for r in rels}[hojas[nombre_hoja]]
    ruta_hoja = ("xl/" + destino).replace("xl//", "xl/")

    compartidas = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(NS + "si"):
            compartidas.append("".join(t.text or "" for t in si.iter(NS + "t")))

    def valor(celda):
        if celda.get("t") == "inlineStr":
            el = celda.find(NS + "is")
            return "".join(t.text or "" for t in el.iter(NS + "t")) if el is not None else ""
        v = celda.find(NS + "v")
        if v is None or v.text is None:
            return ""
        if celda.get("t") == "s":
            return compartidas[int(v.text)]
        return v.text

    filas = []
    for fila in ET.fromstring(z.read(ruta_hoja)).iter(NS + "row"):
        celdas = {}
        ancho = 0
        for c in fila:
            ref = c.get("r")
            if not ref:
                continue
            i = _col_a_indice(ref)
            celdas[i] = valor(c)
            ancho = max(ancho, i + 1)
        filas.append([celdas.get(i, "") for i in range(ancho)])

    if not filas:
        morir(f"La hoja «{nombre_hoja}» de {path.name} está vacía.")
    return filas[0], [f for f in filas[1:] if any(str(v).strip() for v in f)]


def a_registros(encabezado, filas):
    """Filas como dicts por nombre de columna. Si un nombre se repite ('Pts'
    aparece 4 veces en el reporte), gana la primera aparición — ninguna de las
    columnas que nos importan está duplicada."""
    idx = {}
    for i, nombre in enumerate(encabezado):
        nombre = str(nombre).strip()
        if nombre and nombre not in idx:
            idx[nombre] = i
    return [{k: (f[i] if i < len(f) else "") for k, i in idx.items()} for f in filas], idx


# ---------------------------------------------------------------- validación

def parece_salud(path):
    """Sniff rápido y silencioso, para elegir candidato entre las descargas."""
    try:
        z = zipfile.ZipFile(path)
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        if HOJA not in {h.get("name") for h in wb.iter(NS + "sheet")}:
            return False
        crudo = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
        return "ID Empresa" in crudo and "Score Total" in crudo
    except Exception:
        return False


def buscar_descarga(horas=48):
    """El reporte descargado más reciente en ~/Downloads.

    El tablero siempre exporta como `directorio-empresas.xlsx`, así que ese nombre
    manda. Chrome no pisa la descarga anterior: le agrega " (1)", " (2)"… — por eso
    se toma el más reciente por fecha de modificación y no el de nombre exacto."""
    if not DESCARGAS.is_dir():
        return None

    exactos = [
        p for p in DESCARGAS.glob("*.xlsx")
        if p.name.lower().startswith(NOMBRE_EXPORT) and not p.name.startswith("~$")
    ]
    for p in sorted(exactos, key=lambda p: p.stat().st_mtime, reverse=True):
        if parece_salud(p):
            return p
        aviso(f"{p.name} se llama como el export pero no parece el reporte de salud — lo salto")

    # Respaldo por si algún día cambia el nombre del export: cualquier xlsx reciente que huela a salud
    limite = dt.datetime.now().timestamp() - horas * 3600
    candidatos = [
        p for p in DESCARGAS.glob("*.xlsx")
        if not p.name.startswith("~$") and p.stat().st_mtime >= limite and parece_salud(p)
    ]
    return max(candidatos, key=lambda p: p.stat().st_mtime) if candidatos else None


def validar(registros, idx, encabezado, path):
    titulo(f"Validando {path.name}")

    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in idx]
    if faltantes:
        morir(f"Al reporte le faltan columnas que el dashboard necesita: {', '.join(faltantes)}.",
              "Revisa que hayas descargado el reporte completo y no una vista recortada.")
    ok(f"{len(encabezado)} columnas, están las {len(COLUMNAS_REQUERIDAS)} requeridas")

    unidades = {}
    for r in registros:
        u = (r.get("Unidad de Negocio") or "").strip()
        unidades[u or "(vacía)"] = unidades.get(u or "(vacía)", 0) + 1
    ajenas = {u: n for u, n in unidades.items() if u != UNIDAD_ESPERADA}
    if ajenas:
        detalle = ", ".join(f"{u}: {n}" for u, n in sorted(ajenas.items(), key=lambda x: -x[1])[:5])
        morir(f"El reporte trae filas fuera de México ({detalle}).",
              "Parece que no aplicaste el filtro de México en el tablero antes de descargar.")
    ok(f"{len(registros)} filas, todas con Unidad de Negocio = {UNIDAD_ESPERADA}")

    if not (FILAS_MIN <= len(registros) <= FILAS_MAX):
        morir(f"{len(registros)} filas está fuera del rango esperado ({FILAS_MIN}–{FILAS_MAX}).",
              "O el filtro quedó mal, o la cartera cambió muchísimo. Revísalo a mano.")

    ids = [str(r.get("ID Empresa", "")).strip() for r in registros]
    vacios = sum(1 for i in ids if not i)
    if vacios:
        aviso(f"{vacios} filas sin ID Empresa — el dashboard las va a intentar cruzar por nombre")
    return set(i for i in ids if i)


def comparar(registros, ids_nuevos, vigente_path):
    """Diff contra la semana vigente. Devuelve False si el reporte es idéntico."""
    if not vigente_path or not vigente_path.exists():
        aviso("No hay semana vigente con la cual comparar — se sube sin diff")
        return True

    enc, filas = leer_hoja(vigente_path, HOJA)
    previos, _ = a_registros(enc, filas)
    ids_previos = {str(r.get("ID Empresa", "")).strip() for r in previos if str(r.get("ID Empresa", "")).strip()}

    titulo(f"Comparando contra {vigente_path.name}")

    solape = len(ids_nuevos & ids_previos) / max(len(ids_previos), 1)
    if solape < SOLAPAMIENTO_MIN:
        morir(f"Solo {solape:.0%} de las cuentas coinciden con la semana pasada.",
              "Eso no parece la misma cartera — revisa que sea el reporte de México y no otro.")
    ok(f"{solape:.0%} de las cuentas coinciden con la semana pasada")

    delta = (len(registros) - len(previos)) / max(len(previos), 1)
    signo = "+" if len(registros) >= len(previos) else ""
    if abs(delta) > DELTA_FILAS_MAX:
        morir(f"El total de cuentas cambió {signo}{delta:.0%} ({len(previos)} → {len(registros)}).",
              "Es demasiado para una semana. Si el cambio es real, corre de nuevo con --forzar.")
    ok(f"{len(previos)} → {len(registros)} cuentas ({signo}{len(registros) - len(previos)})")

    def firma(rs):
        return {str(r.get("ID Empresa", "")).strip(): (r.get("% Adopción", ""), r.get("Score Total", ""))
                for r in rs}
    if firma(registros) == firma(previos):
        aviso("Este reporte es idéntico al de la semana vigente (mismos IDs, adopción y score)")
        return False

    nuevas = ids_nuevos - ids_previos
    salieron = ids_previos - ids_nuevos
    nombre_de = {str(r.get("ID Empresa", "")).strip(): r.get("Nombre Empresa", "") for r in registros}
    nombre_previo = {str(r.get("ID Empresa", "")).strip(): r.get("Nombre Empresa", "") for r in previos}
    if nuevas:
        dato(f"altas ({len(nuevas)}): " + ", ".join(sorted(nombre_de.get(i, i) for i in nuevas)[:6])
             + (" …" if len(nuevas) > 6 else ""))
    if salieron:
        dato(f"bajas ({len(salieron)}): " + ", ".join(sorted(nombre_previo.get(i, i) for i in salieron)[:6])
             + (" …" if len(salieron) > 6 else ""))

    def por_categoria(rs):
        c = {}
        for r in rs:
            k = (r.get("Categoría") or "sin categoría").strip()
            c[k] = c.get(k, 0) + 1
        return c
    antes, ahora = por_categoria(previos), por_categoria(registros)
    print()
    for cat in sorted(set(antes) | set(ahora)):
        a, b = antes.get(cat, 0), ahora.get(cat, 0)
        d = b - a
        marca = f"  ({'+' if d > 0 else ''}{d})" if d else ""
        dato(f"{cat:<22} {a:>4} → {b:>4}{marca}")
    return True


# ---------------------------------------------------------------- manifiesto y git

def fecha_de_url(url):
    """La URL del tablero trae la fecha de la semana, y es la que manda para nombrar el archivo:
    el correo puede llegar el martes pero el enlace dice 24-agosto, igual que el nombre del xlsx.
    Ej: https://dashboard-de-salud-24-agosto-2026.replit.app/ -> 2026-08-24"""
    patron = r"(\d{1,2})[-_ ]?(" + "|".join(MESES) + r")[-_ ]?(20\d{2})"
    m = re.search(patron, url.lower())
    if not m:
        morir(f"No pude sacar la fecha de {url}",
              "El enlace debería verse como dashboard-de-salud-24-agosto-2026.replit.app. "
              "Si cambió el formato, pasa la fecha a mano con --fecha YYYY-MM-DD.")
    return dt.date(int(m.group(3)), MESES.index(m.group(2)) + 1, int(m.group(1)))


def nombre_destino(fecha):
    return f"salud-mx-{fecha.day:02d}{MESES[fecha.month - 1]}.xlsx"


def actualizar_manifiesto(nombre, dry_run):
    manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    archivos = manifiesto.get("archivos", [])
    anterior = manifiesto.get("vigente", "")
    if nombre not in archivos:
        archivos.append(nombre)          # el orden ya es cronológico por la cadencia semanal
    manifiesto["archivos"] = archivos
    manifiesto["vigente"] = nombre
    if not dry_run:
        MANIFIESTO.write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return anterior, len(archivos)


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        morir(f"git {' '.join(args)} falló:\n{r.stderr.strip()}")
    return r.stdout.strip()


def publicar(nombre, fecha, dry_run, push):
    titulo("Publicando")
    rutas = [nombre, MANIFIESTO.name]
    if dry_run:
        dato(f"git add {' '.join(rutas)}")
        dato(f"git commit -m 'salud semana del {fecha:%d de %B}'")
        dato("git push origin main" if push else "(sin push)")
        return

    git("add", "--", *rutas)
    if not git("diff", "--cached", "--name-only"):
        morir("No hay nada que commitear — el archivo y el manifiesto ya estaban así.")
    mensaje = f"salud semana del {fecha.day} de {MESES[fecha.month - 1]}"
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
    ap = argparse.ArgumentParser(description="Sube el reporte de salud semanal al Monitor de Cartera MX.")
    ap.add_argument("archivo", nargs="?", help="xlsx descargado (default: el más reciente de ~/Downloads)")
    ap.add_argument("--fecha", default="hoy", help="fecha del snapshot: YYYY-MM-DD, 'hoy' o 'lunes' (default: hoy)")
    ap.add_argument("--url", help="enlace del tablero de esa semana; la fecha se saca de ahí (gana sobre --fecha)")
    ap.add_argument("--dry-run", action="store_true", help="valida y muestra el diff sin escribir ni commitear")
    ap.add_argument("--no-push", action="store_true", help="commitea pero no pushea")
    ap.add_argument("--forzar", action="store_true", help="sobreescribe el archivo de la semana si ya existe")
    args = ap.parse_args()

    if args.url:
        fecha = fecha_de_url(args.url)
    elif args.fecha == "hoy":
        fecha = dt.date.today()
    elif args.fecha == "lunes":
        hoy = dt.date.today()
        fecha = hoy - dt.timedelta(days=hoy.weekday())
    else:
        try:
            fecha = dt.datetime.strptime(args.fecha, "%Y-%m-%d").date()
        except ValueError:
            morir(f"Fecha inválida: {args.fecha}", "Usa YYYY-MM-DD, 'hoy' o 'lunes'.")

    if args.archivo:
        origen = Path(args.archivo).expanduser()
        if not origen.exists():
            morir(f"No existe el archivo {origen}")
    else:
        origen = buscar_descarga()
        if not origen:
            morir(f"No encontré ningún {NOMBRE_EXPORT}.xlsx en ~/Downloads.",
                  "Descárgalo del tablero y vuelve a correr esto, o pásame la ruta como argumento.")
        print(f"{GRIS}Usando la descarga más reciente: {origen}{FIN_COLOR}")
        dias = (dt.datetime.now().timestamp() - origen.stat().st_mtime) / 86400
        if dias > 3:
            aviso(f"esa descarga tiene {dias:.0f} días — ¿bajaste el reporte de esta semana?")

    encabezado, filas = leer_hoja(origen, HOJA)
    registros, idx = a_registros(encabezado, filas)
    ids = validar(registros, idx, encabezado, origen)

    manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    vigente = manifiesto.get("vigente", "")
    distinto = comparar(registros, ids, REPO / vigente if vigente else None)
    if not distinto and not args.forzar:
        morir("Es el mismo reporte que ya está publicado.",
              "Si de verdad quieres volver a subirlo, corre de nuevo con --forzar.")

    destino_nombre = nombre_destino(fecha)
    destino = REPO / destino_nombre

    titulo("Destino")
    if fecha.weekday() > 2:
        aviso(f"{fecha:%Y-%m-%d} cae {['lunes','martes','miércoles','jueves','viernes','sábado','domingo'][fecha.weekday()]}"
              f" — el reporte suele fecharse lunes o martes. Si corresponde a otro día usa --fecha.")
    if destino.exists() and not args.forzar:
        morir(f"{destino_nombre} ya existe en el repo.",
              "Si es un reemplazo, corre de nuevo con --forzar; si es otra semana, usa --fecha.")
    dato(f"{origen.name}  →  {destino_nombre}")

    if not args.dry_run:
        shutil.copy2(origen, destino)
        ok(f"copiado a {destino_nombre}")

    anterior, total = actualizar_manifiesto(destino_nombre, args.dry_run)
    ok(f"salud_semanas.json · vigente: {anterior or '(ninguno)'} → {destino_nombre} · {total} semanas")

    if args.dry_run:
        titulo("Dry run — no se escribió nada")
        return
    publicar(destino_nombre, fecha, args.dry_run, push=not args.no_push)


if __name__ == "__main__":
    main()
