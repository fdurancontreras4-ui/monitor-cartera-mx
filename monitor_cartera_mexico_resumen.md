# Monitor de Cartera — México · Resumen del proyecto

Documento de seguimiento de todo lo construido y conversado alrededor del artefacto **`monitor_cartera_mexico.html`**: un dashboard interactivo de un solo archivo HTML para monitorear la cartera de postventa de GeoVictoria México.

---

## 1. Objetivo

Construir un artefacto que permita:

- Monitorear la cartera de México a partir de un Excel, con posibilidad de actualizar la información en cualquier momento.
- Revisar cada cuenta en detalle: ventas, fuga, referidos, semáforo y métricas importantes.
- Cargar un tablero de salud semanal y señalar las cuentas más importantes a priorizar.
- Calcular número de clientes y % con cross-sell por mes.
- Que las indicaciones de priorización consideren el modelo de salud **y** los Playbooks CSS, entregando acciones concretas a realizar.
- Poder publicarlo en GitHub Pages.

---

## 2. Fuentes de datos

| Archivo | Rol | Notas técnicas |
|---|---|---|
| `cuentas0206.xlsx` (hoja MARE MX) | Cartera principal: 453 cuentas con ventas, KAM, cartera, cuadrante, módulos cross | Encabezado en la fila 2 (`header=1`). Módulos codificados como `OK`/`OP`/`NO` con prefijo. |
| `directorio-empresas (6).xlsx` (hoja Directorio) | Tablero de salud: 488 cuentas México con adopción, NPS, incidencias, score y categoría | Encabezado en fila 1. Llave de cruce: `ID Empresa` ↔ `ID Geo` y por nombre. |
| `Playbooks_CSS_-_GeoVictoria_T2_2026.docx` | Protocolos de Customer Success (PB-01, PB-02, PB-03) | Define triggers, SLAs y acciones por escenario. |

**Cruce de archivos.** 296 de 453 cuentas de la cartera emparejaron con el tablero de salud (108 por ID, 188 por nombre). Las 157 restantes no figuran en el tablero o difieren en el nombre. La cartera guardaba el ID como decimal (`29157.0`) y el tablero como entero (`29157`); se normaliza el ID para que cruce.

---

## 3. El artefacto y sus pestañas

Dashboard HTML autocontenido, en español, con el sistema visual "v2" (dark mode, tabs, badges, barras). Precargado con los datos reales, funciona desde que se abre.

1. **Resumen** — KPIs de cartera: cuentas activas, MRR total (~$168k/mes), % con cross activo, cuentas en fuga y monto en riesgo, críticas (salud), en riesgo sin CS, sin KAM. Más MRR por KAM, distribución por cuadrante y top 8 a priorizar.
2. **Prioridad** — Lente de prevención de churn. Índice 0–100 que prioriza cuentas críticas/en riesgo, con peso extra a las que **no tienen Customer Success**. Métricas de cobertura CS, filtros (estado × cobertura) y acción de playbook por cuenta.
3. **Cuentas** — Tabla buscable/filtrable/ordenable (cartera, KAM, fuga). Clic en una fila abre el detalle completo de la cuenta.
4. **Fuga** — Bajas vs. disminuciones derivadas de la tendencia de facturación, ordenadas por monto.
5. **Cross-sell** — Penetración mensual (clientes activos, con cross, %), pipeline OP por módulo y cuentas con oportunidad.
6. **Datos** — Carga por URL/ruta o por archivo (cartera y tablero de salud) e instrucciones de GitHub Pages.

**Vista de detalle de cuenta** (modal): ventas (barras Ene–Abr + MRR + Δ%), fuga, referidos, semáforo de salud (cuadrante, estado, riesgo + adopción/NPS/incidencias/score del tablero), módulos OK/OP/NO, métricas, índice de prioridad con sus drivers, y la **acción recomendada del playbook**.

---

## 4. Evolución por iteración

1. **v1** — Dashboard con las 453 cuentas reales embebidas, vista de detalle por cuenta, carga de Excel por URL o por arrastre (SheetJS), y módulo de prioridad que consume un archivo de salud.
2. **Botón Recargar + Prioridad + colores + GitHub Pages**
   - Botón global **↻ Recargar datos** que re-lee el Excel desde su URL/ruta (con cache-busting).
   - Pestaña Prioridad reenfocada a prevención de churn con cobertura de Customer Success.
   - Nueva paleta: de cálida-neutra a **teal-pizarra** (acento `#0e7d6e`), manteniendo los badges semánticos.
   - Auto-carga nativa de `cartera.xlsx`/`salud.xlsx` en el mismo repo para GitHub Pages.
3. **Cross-sell mensual + Playbooks**
   - Penetración de cross-sell por mes (con desglose SMB/Enterprise).
   - Mapeo de PB-01/PB-02/PB-03 a las señales disponibles; acción concreta por cuenta.
4. **Tablero de salud nuevo (directorio-empresas)**
   - El motor reconoce nativamente el esquema del tablero (ID, adopción, variación, NPS, incidencias, score, categoría).
   - Cruce por ID + nombre, semáforo desde la categoría del tablero, playbooks evaluados con datos reales, y tablero embebido y aplicado al abrir.

---

## 5. Cómo conectar el Excel y actualizarlo

- **Para que sea la base permanente:** editar `CONFIG.portfolioUrl` (y `CONFIG.healthUrl`) al inicio del HTML con el enlace o ruta.
- **Sin tocar código:** pegar el enlace en la pestaña Datos y dar Cargar una vez (queda recordado; el botón ↻ Recargar lo vuelve a buscar).
- **Requisito del enlace:** debe ser directo al `.xlsx` y público. Lo más fiable es Google Sheets → *Archivo · Compartir · Publicar en la web · formato .xlsx*. Enlaces privados de Drive/OneDrive (visor) no sirven.
- **GitHub Pages:** subir el HTML como `index.html` y el Excel como `cartera.xlsx` (y opcional `salud.xlsx`) en el mismo repo → se autocarga. Para actualizar: reemplazar el `.xlsx` y pulsar ↻ Recargar. No requiere editar el HTML.
- **Nota de entorno:** en la vista previa del chat, la descarga desde dominios externos a veces se bloquea por CORS; funciona de forma fiable en la versión descargada localmente o publicada en Pages.

---

## 6. Cross-sell por mes

Penetración sobre la base activa de cada mes (cuentas con facturación ese mes que tienen ≥1 módulo en OK):

| Mes | Clientes activos | Con cross-sell | % |
|---|---|---|---|
| Enero | 393 | 50 | 12.7% |
| Febrero | 414 | 50 | 12.1% |
| Marzo | 438 | 50 | 11.4% |
| Abril | 420 | 50 | 11.9% |

El número con cross (~50) es estable porque el estado de cross es una foto actual, no histórica; lo que varía mes a mes es la base activa (denominador). Para una curva de activación real se necesitaría la fecha de alta de cada módulo (hoy solo aparece el trimestre aproximado en algunas celdas).

---

## 7. Playbooks CSS (T2 2026) integrados

| Playbook | Trigger | SLA primera acción | Acción base |
|---|---|---|---|
| **PB-01 Adopción Cayendo** | Adopción <60% o caída >20pp; 0% por 2 semanas = crítico | ≤ 5 días hábiles | Validar dato, diagnóstico con el administrador, clasificar causa raíz (Técnica/Operativa/Comportamental/Producto) y plan. |
| **PB-02 Detractor NPS** | NPS 0–6 (últimos 90 días) | ≤ 48h | Contacto inmediato sin defender producto; escucha 70/30; clasificar motivo; seguimiento 30 días. |
| **PB-03 Riesgo de Fuga** | 2+ señales: sin marcaje 14d, NPS detractor, ticket sin resolver >7d | ≤ 24h | Contacto con decisor, clasificar fuga evitable/inevitable, plan de recuperación por escrito en ≤72h. |

**Principio rector aplicado:** toda alerta necesita un responsable de monitoreo. Cuando una cuenta está en riesgo y no tiene CSS asignado, el primer paso es asignar gestión antes de ejecutar el playbook. Escalaciones: mencionar competidor o pedir baja → escalar el mismo día.

---

## 8. Indicadores actuales (tablero de salud cruzado)

**Tablero completo México (488 cuentas):** 272 Saludables · 100 Crítico · 89 Sin Uso · 27 En Riesgo. Adopción promedio 61%; 167 cuentas bajo 60%.

**Sobre las 296 cuentas emparejadas con la cartera:**

- 81 cuentas Crítico/Sin Uso = **$25,689/mes** en riesgo.
- De esas, **74 sin Customer Success** = **$16,588/mes** expuesto (el hueco de prevención de churn).
- 8 En Riesgo adicionales ($3,243/mes).

**Playbooks activados:** 41 PB-03 (Fuga) · 30 PB-01 (Adopción) · 6 PB-02 (NPS detractor).

**Top cuentas a priorizar:**

| Cliente | Estado | Adopción | MRR | Acción |
|---|---|---|---|---|
| PLATO EXPRESS | Crítico | 84% | $2,099 | PB-03 · asignar CS + contacto decisor ≤24h |
| Puratos de México | Crítico | 45% | $884 | PB-01 · diagnóstico de adopción ≤5d |
| TDSYSTEM | Crítico | 58% | $1,206 | PB-03 · 2 señales (adopción + facturación) |
| TIENDAS ADITIVO | Crítico | 0% | $439 | PB-03 · sin uso → módulo retención |
| IMPULSORA IDINSA | Crítico | 40% | $2,614 | PB-01 (tiene CS: Antonio) |
| GRUPO NACIONAL COLCHONERO | Crítico | 79% | $276 | PB-02 si NPS detractor |
| METRO ASFALTOS | Crítico | 30% | $235 | PB-01 · caída de uso |
| BKAYA | Sin Uso | 0% | $134 | PB-03 · sin marcaje |

> Varias cuentas "Crítico" tienen adopción alta (PLATO EXPRESS 84%, JUGUETRON 97%): su criticidad viene del score compuesto (tickets/variación), no de la adopción. El detalle muestra el desglose para que el CSS identifique el driver real.

---

## 9. Notas técnicas clave

- **Cruce de nombres:** normalización quitando sufijos legales (S.A. de C.V., SAPI, etc.), acentos, paréntesis y espacios; match por ID (normalizado a entero), luego por nombre exacto y por contención.
- **Categoría → semáforo:** Crítico/Sin Uso → crítico (rojo) · En Riesgo → atención (ámbar) · Saludable → ok (verde).
- **Cobertura CS:** considera el CSS de la cartera y el del tablero (el tablero suma José Antonio Garnica y Bárbara Mejías a los previos Tony/Antonio).
- **Persistencia:** la carga semanal y la URL se recuerdan vía almacenamiento del artefacto (best-effort); la cartera base embebida es el respaldo.
- **Fuga:** derivada de la tendencia Ene→Abr (Baja = cae a ~0; Disminución = cae ≥15%). Para el corte oficial conviene reconciliar con el archivo de Detalle Fuga.

---

## 10. Pendientes / próximos pasos

- **Datos que elevarían la fidelidad del modelo:** NPS por cuenta (activa PB-02 y la 2ª señal de PB-03) y días sin marcaje / adopción % reales — el nuevo tablero ya los trae, así que esto queda cubierto al usarlo semanalmente.
- **Decisión de fondo:** asignar responsable de monitoreo al bloque de **74 cuentas en riesgo sin CS** (principalmente SMB) antes de que caiga la facturación. Pendiente definir si se reparten entre los CS actuales (Tony, Antonio, José Antonio Garnica) o se crea un rol de CS dedicado a SMB.
- **Referidos:** la columna existe pero está vacía en la cartera; la sección aparece sin datos hasta poblarla.
- **Opcional:** preparar un `cartera.xlsx` de ejemplo y un README para dejar el repo de GitHub Pages listo para subir.
