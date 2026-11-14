#!/bin/bash
# Copia el Excel «Cuentas Postventa» (OneDrive, sincronizado en este Mac) al repo como cartera.xlsx
# y, si cambió, hace commit + push SOLO de cartera.xlsx. El Excel original solo se lee: nunca se escribe.
# Uso: scripts/copiar-cartera.sh [--dry-run]
set -euo pipefail
ORIGEN="$HOME/Library/CloudStorage/OneDrive-VictoriaS.A/PostVenta/Cuentas Postventa.xlsx"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DESTINO="$REPO/cartera.xlsx"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

[ -f "$ORIGEN" ] || { echo "✗ No encuentro $ORIGEN (¿OneDrive sincronizado?)"; exit 1; }
TMP="$(mktemp -d)/cartera.xlsx"
cp "$ORIGEN" "$TMP"   # en OneDrive «solo en la nube» esto fuerza la descarga

# validar que sea el Excel correcto (xlsx con la hoja MARE MX) antes de pisar cartera.xlsx
python3 -I - "$TMP" <<'EOF'
import sys, zipfile, re
z = zipfile.ZipFile(sys.argv[1])
hojas = re.findall(r'<sheet [^>]*name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8"))
if not hojas or hojas[0] != "MARE MX":
    sys.exit(f"✗ El archivo no parece la cartera: primera hoja = {hojas[:1]}")
print(f"  ✓ Excel válido · {len(hojas)} hojas · primera: {hojas[0]}")
EOF

if cmp -s "$TMP" "$DESTINO"; then echo "  ✓ cartera.xlsx ya está al día (sin cambios)"; exit 0; fi
MOD="$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$ORIGEN")"
if [ $DRY = 1 ]; then echo "  (dry-run) cartera.xlsx cambiaría (Excel guardado $MOD)"; exit 0; fi
cp "$TMP" "$DESTINO"
cd "$REPO"
git add cartera.xlsx
git commit -q -m "cartera: actualiza desde Cuentas Postventa (guardado $MOD)" -- cartera.xlsx
git push -q origin main
echo "  ✓ cartera.xlsx actualizado y publicado (Excel guardado $MOD) · $(git log --oneline -1)"
