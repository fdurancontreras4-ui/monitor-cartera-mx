---
name: postventa-mrr
description: Actualiza "Cuentas Postventa.xlsx" (SharePoint) con el MRR y la fuga de clientes del mes, cruzando datos del reporte Power BI "Facturación Mensual" (página Recurrente, filtro México). Úsala cuando Fernanda diga "actualiza la fuga", "sube el MRR del mes", "actualiza cuentas postventa", "carga la facturación de [mes] en el Excel de postventa" o pida bajar del Power BI de Facturación Mensual la Tendencia de MRR por cliente y los clientes que disminuyeron facturación.
---

# Actualizar Cuentas Postventa (MRR y fuga México)

Flujo mensual: junta datos del reporte de Power BI "Facturación Mensual" y actualiza el Excel de SharePoint que Fernanda usa para dar seguimiento a MRR y fuga de clientes en México.

## Contexto fijo

- **El reporte de Power BI** se llama "Facturación Mensual":
  `https://app.powerbi.com/groups/me/reports/9d9bb26a-6b78-4525-9c3a-76c7bac5ed7a/e5fe58ad602b017d3718?experience=power-bi&clientSideAuth=0`
  Requiere la sesión de Chrome de Fernanda (perfil fduran@geovictoria.com) ya conectada — usar Claude in Chrome, no un tab anónimo.

- **El Excel** es "Cuentas Postventa.xlsx", que vive en `Documents/PostVenta/` dentro del OneDrive personal de Fernanda (no en la raíz). El enlace que ella usa para abrirlo:
  `https://geovictoria365-my.sharepoint.com/:x:/r/personal/fduran_geovictoria_com/_layouts/15/Doc.aspx?sourcedoc=%7B374CB29E-C6EC-4E2E-BF58-A6E8BB61C9ED%7D&file=Cuentas%20Postventa.xlsx&action=default`

  Su identidad real en el conector de SharePoint/OneDrive (para leerlo y sobrescribirlo por API, sin depender del navegador):
  - `driveId`: `b!sAG5r_bfbEGvk01PB7t4cQzL2hbo70NNv2KSjMR1GulyjRiY0B71TJsImZRJSNRV`
  - `itemId`: `01FBJR3VU6WJGDP3GGFZHL6WFG5C5WDSPN`

  Si algún día `sharepoint_update_file` devuelve que ese `itemId` no existe (el archivo se movió o se recreó), volver a resolverlo con `read_resource` sobre la carpeta `PostVenta` (`file:///{driveId}/01FBJR3VUFFVX2P2IQUBFJOPXLLPLWUFOW`, que lista el contenido de esa carpeta) y buscar la fila `Cuentas Postventa.xlsx` ahí — nunca adivinar por búsqueda de texto libre.

  ⚠️ **En el OneDrive de Fernanda hay decenas de copias parecidas** (`Cuentas Postventa (1).xlsx`, `Cuentas_Postventa_actualizado.xlsx`, `Cuentas_Postventa_MX_corregido.xlsx`, etc. — varias docenas). `sharepoint_search` por nombre casi siempre trae alguna de esas copias antes que el archivo real, y con ese nombre exacto a veces no lo encuentra en absoluto. Usar siempre el `driveId`/`itemId` de arriba (o el enlace de Fernanda), nunca un resultado de búsqueda que "se parezca" al nombre, y nunca crear una copia nueva como si fuera la buena.

- Dentro del Excel:
  - Hoja **"MARE MX"**: una fila por cliente, con columnas mensuales de facturación (Enero, Febrero, ...). Ahí se agrega la columna del mes que se está subiendo.
  - Pestaña **"Detalle fuga"**: cuentas cuya facturación bajó **100%** (fuga total) respecto al mes anterior.
  - Pestaña **"menor al 100"**: cuentas cuya facturación bajó, pero **menos del 100%** (fuga parcial).

  Las tres ya existen con sus propias columnas. La primera vez que se corra esta skill, abrir el archivo real y confirmar los encabezados exactos de "Detalle fuga" y "menor al 100" (por si tienen columnas cruzadas como KAM o Cartera que el export de Power BI no trae) — el script de abajo ya respeta el encabezado que encuentre, así que solo hay que confirmarlo, no hay que tocar el script para eso.

## Pasos

1. **Abrir el reporte de Power BI** en el enlace de arriba y entrar a la página **"Recurrente"** (panel de páginas a la izquierda). El filtro de País ya viene en **MÉXICO** por defecto.

2. **Confirmar el mes.** El filtro "Mes" trae seleccionado el mes más reciente con datos — es el último de la lista del dropdown, no necesariamente el mes calendario en curso (si hoy es 9 de septiembre y septiembre todavía no tiene facturación cargada, el filtro se queda en agosto). No cambiarlo a mano; solo leer cuál quedó marcado, porque ese es el nombre de la columna/mes que se va a subir.

3. **Descargar "Tendencia de MRR por cliente/producto".** Es la tabla grande bajo "Variación de facturación de productos v/s mes anterior". A su izquierda hay un toggle **"Producto/Cliente"** — dejarlo en **Cliente** (es el que viene marcado por defecto). Pasar el mouse sobre la tabla → clic en **"···" (Más opciones)** → **"Exportar datos"** → en el diálogo "¿Qué datos quiere exportar?" dejar **"Datos con diseño actual"** (preseleccionado) y formato **.xlsx**. Pedir confirmación a Fernanda antes de bajar el archivo (igual que en `/salud`).

4. **Descargar "Clientes que disminuyeron su facturación respecto al mes anterior (10%+)"**, la tabla a la derecha de "Clientes que aumentaron...". Mismo mecanismo de exportación. Esta tabla trae variaciones desde -100% (fuga total) hasta -10% (el "10%+" del título es el piso: no incluye caídas menores al 10%) — de ahí salen las dos pestañas del Excel.

5. **Bajar el archivo real** (los bytes del .xlsx, no solo su contenido — el conector de SharePoint no expone descarga binaria, así que esto se hace con Claude in Chrome, sesión de Fernanda):
   - Abrir el enlace de arriba. Ese editor (Excel Online) puede tardar mucho en pintar el grid, incluso 30-40s en este archivo (17 hojas, varias con fórmulas) — no hace falta esperar a que pinte: **"Archivo" → "Guardar una copia" → "Descargar una copia"** corre sobre el marco de Office, no sobre el grid, y suele funcionar aunque la hoja no haya cargado visualmente.
   - Si eso tampoco responde, ir directo a la vista de biblioteca de la carpeta (`Documents/PostVenta` en el OneDrive de Fernanda) en vez del editor, y descargar el archivo desde ahí con clic derecho → Descargar. Esa vista es mucho más liviana que el editor.

6. **Correr el script** con los tres archivos (Chrome los deja en `~/Downloads`, tomar los más recientes):

   ```bash
   cd ~/Geo/monitor-cartera-mx
   python3 scripts/actualizar-postventa.py \
     --postventa "~/Downloads/Cuentas Postventa.xlsx" \
     --tendencia "~/Downloads/Tendencia de MRR por cliente_producto.xlsx" \
     --disminuyeron "~/Downloads/Clientes que disminuyeron su facturación respecto al mes anterior.xlsx" \
     --mes "Septiembre" \
     --dry-run
   ```

   Correrlo primero con `--dry-run` y revisar el reporte: cuántos clientes se actualizaron en MARE MX, cuáles no cruzaron por nombre (pueden ser clientes nuevos, o el mismo cliente con razón social distinta entre sistemas — no forzar el cruce, dejarlos para que Fernanda los revise), y cuántas filas van a "Detalle fuga" vs "menor al 100". Si se ve razonable, correrlo sin `--dry-run`.

7. **Mostrarle el archivo resultante a Fernanda antes de subir nada.** Enviarle el archivo que generó el script (por defecto `Cuentas Postventa (actualizado).xlsx`) para que lo revise. No avanzar al paso siguiente sin su confirmación explícita.

8. **Con su confirmación, reemplazar el archivo real en SharePoint** — no antes. Leer los bytes del archivo ya confirmado, y llamar a `sharepoint_update_file` con el `driveId`/`itemId` de la sección de arriba y el contenido en `contentBase64`. Esto sobreescribe el archivo real en el mismo enlace, sin crear una copia nueva.

   ⚠️ El conector solo permite reemplazar archivos de hasta 1 MB. Hoy "Cuentas Postventa.xlsx" pesa ~605 KB, así que entra, pero va a crecer cada mes (una columna más en MARE MX, más filas de fuga). Si `sharepoint_update_file` rechaza el archivo por tamaño, no hay vuelta: hay que subirlo a mano desde el navegador (Doc.aspx → "Guardar una copia" → reemplazar, o arrastrarlo en la vista de carpeta) y avisarle a Fernanda que este paso dejó de poder automatizarse.

9. **Reportar a Fernanda** el resumen que imprime el script: mes subido, cuántos clientes con fuga total vs parcial, y la lista de clientes sin cruce (para que los revise a mano).

## Trampas

- Power BI no siempre tiene cargado el mes calendario actual — confirmar el mes real seleccionado en el filtro (paso 2) antes de nombrar la columna nueva.
- El archivo real vive en `Documents/PostVenta/`, no en la raíz del OneDrive de Fernanda. `sharepoint_search` por "Cuentas Postventa" trae docenas de copias parecidas y muchas veces ni siquiera encuentra el archivo real por nombre exacto — usar el `driveId`/`itemId` fijos de la sección de arriba, nunca un resultado de búsqueda de texto libre.
- El cruce de nombre de cliente entre Power BI y "MARE MX" no siempre es exacto (mayúsculas, razón social vs. nombre comercial). El script normaliza mayúsculas/espacios pero no adivina — los que no cruzan se reportan, no se pegan a ciegas.
- La tabla de "disminuyeron" del Power BI solo trae variaciones de -10% o más (el "10%+" del título) — "menor al 100" no es "toda baja que no sea del 100%", es específicamente el rango -10% a -99%.
- Excel Online puede tardar bastante en cargar este archivo en el navegador (son 17 hojas, varias con fórmulas pesadas en MARE MX) — no depender de que el grid pinte para descargar una copia (ver paso 5).
- `sharepoint_update_file` tiene un techo de 1 MB por archivo. El archivo hoy pesa ~605 KB — cuando se acerque al límite (crece cada mes), este paso automático va a empezar a fallar y hay que subirlo a mano.
- Nunca reemplazar el archivo real en SharePoint sin que Fernanda haya confirmado el archivo generado (paso 7). Es un archivo de negocio en uso — el show-antes-de-subir no es opcional.
- El script solo necesita `openpyxl` (`pip install openpyxl` si hace falta) — no toca Power BI ni SharePoint directamente, solo transforma los tres archivos locales.
