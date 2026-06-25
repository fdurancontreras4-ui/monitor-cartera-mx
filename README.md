# Monitor de Cartera — México · GeoVictoria

Dashboard interactivo de un solo archivo para monitorear la cartera de postventa de GeoVictoria México: salud de cuentas, priorización **por KAM**, fuga, cross-sell y métricas de venta. Funciona desde que se abre (trae la cartera base embebida) y se actualiza cargando un Excel.

## Publicar en GitHub Pages

1. Crea un repositorio y sube **`index.html`** (este archivo) a la raíz.
2. (Opcional, recomendado) Sube la cartera como **`cartera.xlsx`** y el modelo de salud como **`salud.xlsx`** en la misma raíz: el dashboard los detecta y carga solos al abrir.
3. Activa Pages en **Settings → Pages → Branch: `main` / root**.
4. Tu equipo entra en `https://<usuario>.github.io/<repo>/`.

## Actualización semanal (lunes)

- **Cartera (SharePoint):** el archivo base vive en SharePoint y **no se puede cargar por URL** (los enlaces privados de SharePoint/OneDrive exigen sesión). Exporta ese archivo a `.xlsx`, súbelo al repo como `cartera.xlsx`, y pulsa **↻ Recargar datos**. No hay que tocar el HTML.
- **Salud:** sube el modelo de salud semanal en la pestaña **Datos** (arrastrar el archivo) o como `salud.xlsx` en el repo. Empareja por ID + nombre y reclasifica el semáforo de cada cuenta.

## Pestañas

- **Resumen** — KPIs de cartera, **gráfico de MRR mensual** (enero al último mes cargado), MRR por KAM, cuadrantes y salud por tamaño de empresa.
- **Salud** — Agrupada **por KAM**: dentro de cada uno, las **críticas se ordenan por marcaje ascendente** (peor marcaje primero) y luego las en riesgo. Las tarjetas de arriba (Críticas / En riesgo / Saludables) filtran al tocarlas. Cada cuenta trae su acción de playbook (PB-01/02/03).
- **Cuentas** — Tabla buscable y filtrable; clic abre el detalle (incluye % adopción, NPS y tickets/incidencias).
- **Fuga** — Bajas y disminuciones por monto.
- **Cross-sell** — Penetración mensual; **Mayo** y meses siguientes aparecen solos al cargar un Excel con esas columnas.
- **Datos** — Carga de cartera y salud (con listado de filas de salud sin emparejar y su estado), e instrucciones de publicación.

La cabecera muestra la **última hora de recarga de datos** junto al nombre de la cartera.

## Marca

Paleta GeoVictoria: amarillo `#FFBB00`, azul `#00AFF2`, gris `#646464`. Logo embebido (funciona en modo claro y oscuro). Para botones se usa un azul más oscuro derivado (`#006FA8`) para mantener contraste legible con texto blanco; los rojos/ámbar/verde se conservan por su significado de semáforo.
