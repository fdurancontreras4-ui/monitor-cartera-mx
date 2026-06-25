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

## Consideraciones de negocio (`consideraciones.json`)

Reglas y excepciones que el monitor aplica al calcular salud y criticidad. Viven en **`consideraciones.json`** en el repo (se carga solo al abrir) y se editan sin tocar el HTML. Tras editar, vuelve a subir el archivo y pulsa ↻ Recargar datos. También puedes arrastrarlo en la pestaña Datos.

Estructura:

- **`reglas_globales.critico_solo_por_ticket`** — Cuentas marcadas críticas solo por ≤ `max_tickets` incidencias y por lo demás sanas (adopción ≥ `marcaje_minimo`, sin NPS detractor, sin caída fuerte y sin fuga) pasan a Saludable.
- **`cuentas`** — Excepciones por cuenta, identificadas por `id` (ID Geo, lo más fiable) o `nombre`:
  - `accion: "congelar"` — La cuenta no se cuenta como crítica (ej. va a freeze y se retoma después).
  - `accion: "ajustar_marcaje"` con `marcaje_maximo` — Reescala la adopción sobre ese tope (ej. usuarios de solo-acceso que nunca marcan). Si tras el ajuste el marcaje es sano, deja de ser crítica por marcaje, pero se conservan otras señales reales (p. ej. caída de facturación → queda En riesgo).
  - `accion: "cambio_razon_social"` — La cuenta **no se cuenta como fuga ni como crítica** (la caída de facturación es re-facturación bajo una nueva entidad, no churn). También se detecta automáticamente cualquier cuenta cuyo **comentario** en la cartera mencione "cambio de razón social".
  - `accion: "no_fuga"` — **Saca la cuenta de la marca de fuga** (no entra en "En fuga" ni en la pestaña Fuga, y la fuga deja de empujarla a Crítica/En riesgo), pero conserva otras señales de salud. Además, si tu `cartera.xlsx` trae una hoja llamada **"detalle fuga"** (con una columna de cliente/empresa o ID Geo), esas cuentas se excluyen de fuga automáticamente.

Detalles de presentación derivados de las consideraciones: el tag de criticidad muestra el motivo (`Crítico-marcaje`, `Crítico-sinuso`, `Crítico-nps`, `Crítico-ticket`, `Crítico-fuga`), y la acción del playbook aparece separada con el rótulo **"Acción a realizar:"**.

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
