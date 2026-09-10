#!/usr/bin/env python3
"""
Actualiza Cuentas Postventa.xlsx con el MRR y la fuga del mes.

Este script no se conecta a Power BI ni a SharePoint — eso lo hace quien lo
invoca (la skill /postventa-mrr, con la sesión de Chrome de Fernanda ya
autenticada). Este script se limita a tomar tres archivos ya descargados:

  1. Cuentas Postventa.xlsx      — el archivo real de SharePoint, descargado tal cual
  2. Tendencia de MRR por cliente/producto  — export del visual homónimo en Power BI
  3. Clientes que disminuyeron su facturación respecto al mes anterior — ídem

...y produce una copia de Cuentas Postventa.xlsx con:
  - la columna del mes agregada/actualizada en la hoja "MARE MX" (cruzando por CLIENTE)
  - las filas con Variación % = -100 agregadas a la pestaña "Detalle fuga"
  - el resto de las filas (entre -10% y -99%) agregadas a la pestaña "menor al 100"

El cruce de clientes es por nombre (mayúsculas, espacios colapsados). Cuando un
cliente del export de Power BI no aparece en MARE MX, NO se inventa una fila:
se reporta al final para que Fernanda lo revise a mano (puede ser un cliente
nuevo, o el mismo cliente con un nombre distinto en cada sistema).

Uso:
    python3 scripts/actualizar-postventa.py \
        --postventa "~/Downloads/Cuentas Postventa.xlsx" \
        --tendencia "~/Downloads/Tendencia de MRR por cliente_producto.xlsx" \
        --disminuyeron "~/Downloads/Clientes que disminuyeron su facturación.xlsx" \
        --mes "Septiembre" \
        --out "~/Downloads/Cuentas Postventa (actualizado).xlsx"

Corre primero con --dry-run: no escribe nada, solo reporta qué haría (cuántos
clientes cruzan, cuántos no, cuántas filas van a cada pestaña de fuga). Solo
depende de openpyxl (`pip install openpyxl` si no está instalado).
"""

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

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


def norm(valor):
    """Normaliza un nombre de cliente o encabezado para comparar: mayúsculas, espacios colapsados."""
    return " ".join(str(valor or "").strip().upper().split())


# ---------------------------------------------------------------- lectura de los exports de Power BI

def leer_export(path):
    """Lee un export 'Datos con diseño actual' de Power BI: primera hoja, fila 1 = encabezados."""
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    encabezados = [norm(c.value) for c in ws[1]]
    filas = []
    for fila in ws.iter_rows(min_row=2, values_only=True):
        if all(v is None for v in fila):
            continue
        filas.append(dict(zip(encabezados, fila)))
    return filas


def valor_mes_actual(fila_tendencia):
    """La 'Tendencia de MRR' trae una columna por mes (ago-2025, sept-2025, ...);
    el mes más reciente es la última columna con un valor no vacío en esa fila."""
    valores = [v for k, v in fila_tendencia.items() if k != "CLIENTE"]
    return next((v for v in reversed(valores) if v is not None), None)


def variacion_pct(fila):
    for llave in ("VARIACIÓN %", "VARIACION %"):
        if llave in fila and fila[llave] is not None:
            v = fila[llave]
            if isinstance(v, str):
                v = v.replace("%", "").replace(",", ".").strip()
            try:
                return round(float(v))
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------- MARE MX

def actualizar_mare_mx(wb, filas_tendencia, mes):
    if "MARE MX" not in wb.sheetnames:
        morir("No encontré la hoja 'MARE MX' en Cuentas Postventa.xlsx.",
              "¿Cambió el nombre de la pestaña? Revísalo y ajusta el script.")
    ws = wb["MARE MX"]

    encabezados = {norm(c.value): c.column for c in ws[1] if c.value is not None}
    col_cliente = encabezados.get("CLIENTE")
    if col_cliente is None:
        morir("No encontré la columna 'CLIENTE' en la fila 1 de MARE MX.")

    col_mes = encabezados.get(norm(mes))
    if col_mes is None:
        col_mes = ws.max_column + 1
        ws.cell(row=1, column=col_mes, value=mes)
        ok(f"MARE MX: agrego columna nueva '{mes}' (columna {col_mes}).")
    else:
        aviso(f"MARE MX: la columna '{mes}' ya existía (columna {col_mes}) — se sobreescribe.")

    fila_por_cliente = {}
    for r in range(2, ws.max_row + 1):
        cliente = norm(ws.cell(row=r, column=col_cliente).value)
        if cliente:
            fila_por_cliente[cliente] = r

    actualizados, sin_match = 0, []
    for fila in filas_tendencia:
        cliente = fila.get("CLIENTE")
        if not cliente or norm(cliente) == "TOTAL":
            continue
        r = fila_por_cliente.get(norm(cliente))
        if r is None:
            sin_match.append(cliente)
            continue
        ws.cell(row=r, column=col_mes, value=valor_mes_actual(fila))
        actualizados += 1

    ok(f"MARE MX: {actualizados} clientes actualizados con la facturación de {mes}.")
    if sin_match:
        aviso(f"MARE MX: {len(sin_match)} clientes del export de Power BI no se encontraron por nombre:")
        for c in sin_match:
            dato(c)
    return actualizados, sin_match


# ---------------------------------------------------------------- Detalle fuga / menor al 100

def agregar_filas(wb, nombre_pestana, filas):
    if nombre_pestana not in wb.sheetnames:
        aviso(f"No encontré la pestaña '{nombre_pestana}' — no se agregó nada ahí.")
        return 0
    ws = wb[nombre_pestana]
    encabezados = {norm(c.value): c.column for c in ws[1] if c.value is not None}

    siguiente_fila = ws.max_row + 1
    agregadas = 0
    for fila in filas:
        cliente = fila.get("CLIENTE")
        if not cliente or norm(cliente) == "TOTAL":
            continue
        for encabezado_norm, col in encabezados.items():
            llave_origen = next((k for k in fila if norm(k) == encabezado_norm), None)
            if llave_origen is not None:
                ws.cell(row=siguiente_fila, column=col, value=fila[llave_origen])
        siguiente_fila += 1
        agregadas += 1

    ok(f"{nombre_pestana}: {agregadas} filas agregadas.")
    return agregadas


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--postventa", required=True, help="Cuentas Postventa.xlsx descargado de SharePoint")
    ap.add_argument("--tendencia", required=True, help="Export 'Tendencia de MRR por cliente/producto'")
    ap.add_argument("--disminuyeron", required=True,
                     help="Export 'Clientes que disminuyeron su facturación respecto al mes anterior'")
    ap.add_argument("--mes", required=True, help="Nombre del mes que se está subiendo, p.ej. 'Septiembre'")
    ap.add_argument("--out", help="Ruta de salida (por defecto: junto al --postventa, con sufijo ' (actualizado)')")
    ap.add_argument("--dry-run", action="store_true", help="No escribe nada, solo reporta")
    args = ap.parse_args()

    postventa = Path(args.postventa).expanduser()
    if not postventa.exists():
        morir(f"No existe {postventa}")

    titulo("Leyendo exports de Power BI")
    filas_tendencia = leer_export(Path(args.tendencia).expanduser())
    filas_disminuyeron = leer_export(Path(args.disminuyeron).expanduser())
    ok(f"Tendencia de MRR por cliente: {len(filas_tendencia)} filas")
    ok(f"Clientes que disminuyeron: {len(filas_disminuyeron)} filas")

    fuga_total = [f for f in filas_disminuyeron if variacion_pct(f) == -100]
    fuga_parcial = [f for f in filas_disminuyeron
                     if variacion_pct(f) is not None and -100 < variacion_pct(f) < 0]
    sin_variacion = len(filas_disminuyeron) - len(fuga_total) - len(fuga_parcial)
    dato(f"→ {len(fuga_total)} con -100% (fuga total), {len(fuga_parcial)} entre -10% y -99% (fuga parcial)")
    if sin_variacion:
        aviso(f"{sin_variacion} filas sin 'Variación %' reconocible — revisar el export.")

    titulo(f"Actualizando Cuentas Postventa.xlsx para {args.mes}")
    wb = load_workbook(postventa)
    actualizar_mare_mx(wb, filas_tendencia, args.mes)
    agregar_filas(wb, "Detalle fuga", fuga_total)
    agregar_filas(wb, "menor al 100", fuga_parcial)

    if args.dry_run:
        titulo("--dry-run: no se escribió ningún archivo")
        return

    salida = Path(args.out).expanduser() if args.out else postventa.with_name(
        f"{postventa.stem} (actualizado){postventa.suffix}")
    wb.save(salida)
    titulo("Listo")
    ok(f"Guardado en: {salida}")
    dato("Súbelo a SharePoint reemplazando el archivo original (mismo enlace) y confírmalo con Fernanda antes.")


if __name__ == "__main__":
    main()
