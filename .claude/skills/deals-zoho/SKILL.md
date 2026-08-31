---
name: deals-zoho
description: Sincroniza el pipeline de Zoho CRM (Deals) con la pestaña Pipeline del Monitor de Cartera MX. Úsala cuando Fernanda diga "actualiza el pipeline", "sube los deals de Zoho", "sincroniza Zoho" o similar. También es el procedimiento que sigue la tarea programada deals-mx-diario.
---

# Sincronizar el pipeline de Zoho CRM

El repo es `~/Geo/monitor-cartera-mx`, que es **público** (GitHub Pages sobre
`main`) — por eso este flujo nunca mete credenciales de Zoho en el repo. La
lectura de Zoho la hace quien corre esta skill (yo, con el conector MCP de
Zoho ya autorizado en la cuenta); `scripts/subir-deals-zoho.py` solo valida,
le da forma y publica lo que ya se leyó.

## Qué se trae

Módulo **Deals** de Zoho CRM, con `searchRecords` y este criterio exacto:

```
((Owner:equals:3525045000270215054)
 and((KAM:equals:Dafne de la Rosa)
  or(KAM:equals:Raúl Campos)
  or(KAM:equals:Karla Patiño)))
```

- `Owner:equals:3525045000270215054` — el usuario Zoho **KAM México**
  (`kammexico@geovictoria.pro`), dueño de todos los deals de México.
- El campo **KAM** (picklist propio de Deals, no el Owner) trae el nombre del
  KAM de cuenta — ahí es donde viven "Dafne de la Rosa", "Raúl Campos" y
  "Karla Patiño".
- No hace falta filtrar por `Territorio` aparte: con ese Owner y esos tres
  KAM ya da México (pero el script igual lo valida por si acaso).

Campos a pedir (`fields` de `searchRecords`):
`id,Deal_Name,Account_Name,KAM,Owner,Territorio,Stage,Producto_Soluci_n,Valor_del_trato_Global,Correo_KAM,Created_Time,Modified_Time`

`Amount` y `Closing_Date` (los campos estándar de Zoho) están vacíos en este
pipeline — el monto real vive en el campo custom **Valor_del_trato_Global**.

## Paginación

`searchRecords` devuelve como máximo 200 por página. Hoy son ~429 deals (3
páginas), y va a seguir creciendo — repetir con `page` incremental hasta que
`info.more_records` sea `false`, y juntar todas las páginas en **una sola
lista plana** antes de pasársela al script (no una por archivo).

## Publicar

1. Volcar la lista combinada a un JSON temporal, por ejemplo
   `/tmp/deals-zoho-raw.json` (fuera del repo — nunca dentro de
   `~/Geo/monitor-cartera-mx`, para no arriesgarse a commitear un archivo de
   trabajo a medio hacer).
2. Correr:
   ```bash
   cd ~/Geo/monitor-cartera-mx && python3 scripts/subir-deals-zoho.py /tmp/deals-zoho-raw.json
   ```
   El script valida (Owner, Territorio, KAM, rango de totales, solape contra
   lo publicado), arma `deals-mx.json`, y si hay cambios hace commit + push a
   `main` solo. `--dry-run` para revisar sin escribir nada.
3. Reportar el diff que imprime el script (deals nuevos, los que salieron del
   pipeline, y los que cambiaron de etapa) — eso es lo que le interesa a
   Fernanda de la corrida, no el detalle mecánico.

Si el script se detiene por solape/rango sospechoso y el cambio es real
(pipeline reorganizado, cuenta reasignada de KAM, etc.), correr de nuevo con
`--forzar`.

## Dónde se ve

Pestaña **Pipeline** del dashboard: tablero en columnas por etapa (estilo
kanban), con filtro de KAM y buscador, más un resumen "Pipeline y Forecast
por mes" (Pipeline = etapa 4-5, Forecast = etapa 6-7, agrupado por mes de
última actualización — no hay fecha de cierre estimada cargada en Zoho). El
botón "↻ Recargar datos" también refresca `deals-mx.json` sin recargar la
página.
