# Real Data Ingestion v0.2

Implementación del 19 de noviembre de 2026 basada en [data-audit.md](data-audit.md). Esta iteración cubre interpretación, conservación, revisión y conciliación de datos. El solver OR-Tools, el proveedor de viajes y las reglas físicas de planificación permanecen intactos.

## Alcance y separación del planificador

La API nueva está bajo `/v2`. Las solicitudes se persisten en tablas nuevas, separadas de los pasajeros/servicios del planificador v0.1. No hay conversión automática hacia el solver ni cálculo de rutas sobre el histórico real. Compartir flota y el máximo confirmado de dos viajes por van siguen documentados en la auditoría; su implementación no forma parte de esta versión.

Se mantienen los endpoints anteriores y su parser. El esquema SQLite se amplía de forma aditiva mediante `create_all`, sin alterar columnas ni sobrescribir registros anteriores. Al iniciar se registran, si faltan, los clientes `gran_america` y `lo_blanco`. No se añadieron dependencias; `pyproject.toml`, OpenAPI y la versión local del proyecto en `uv.lock` se actualizaron a 0.2.0.

## Modelos y procedencia

- **Customer:** código estable y nombre del cliente, elegido expresamente al importar; no se infiere a partir de un archivo que podría conservar el nombre del otro cliente.
- **Terminal:** pertenece a un cliente. Dirección y pareja de coordenadas son opcionales en ingesta. No se geocodifican nombres ni domicilios.
- **TransportRequest:** código de trabajador, nombre, contacto, dirección, comuna, fecha, sentido, terminal, hora de inicio, término, recogida y llegada reportada. Inicio y término son campos distintos.
- **IngestionBatch:** cliente, perfil, función del documento (`original`/`internal`), fecha archivada opcional, fecha esperada opcional, contexto de terminal, SHA-256 y reporte agregado de hojas.
- **CellEvidence:** columna, valor original, fórmula, valor guardado y origen (`literal`, `cached_unverified` o `unresolved`). La procedencia incluye índice de hoja, fila, encabezado y bloque.
- **Correction:** fecha UTC, actor `operator`, motivo, cambios, valores anteriores y campos confirmados. No reemplaza ni borra la evidencia de origen.
- **UnclassifiedRow:** celdas privadas conservadas aparte cuando no se puede identificar un esquema de traslado o una fila tiene horario sin identidad. No se cuentan como solicitudes activas.
- **ReconciliationReport:** coincidencias por IDs de solicitud, faltantes, incorporaciones, grupos ambiguos y diferencias por nombre de campo. No incluye nombres, domicilios, teléfonos ni códigos de trabajador.

No se copia una hoja maestra laboral completa a las solicitudes. En las tablas activas se conserva la evidencia de las columnas de traslado reconocidas; las filas de esquema desconocido quedan separadas para revisión. Los índices de bloque describen la estructura de la hoja: **no representan viajes físicos**.

## Perfiles y reglas de interpretación

### Gran América

Reconoce las variantes de nombres/código/contacto, `Hora Inicio`, `Hora Ingreso` y `Hora Término`, fechas y recogidas. Segmenta encabezados repetidos. En documentos internos selecciona las listas consolidadas, sin duplicarlas con hojas de ruta ni cierres.

### Lo Blanco

Añade `Depósito asignado`, `Fecha de presentación`, variantes de contacto y columnas de ingreso. Los encabezados que agregan una anotación al prefijo «Hora de ingreso» se interpretan como una **propuesta pendiente de confirmación**, marcada `source_header_variant`; no se consideran verificados automáticamente. Las hojas internas de reparto con terminal/recogida se mantienen como referencias, separadas de la lista consolidada.

### Comportamiento común

1. Leer fórmulas y cachés en dos pasadas de OpenPyXL, sin evaluar ni recalcular.
2. Excluir referencias maestras identificables, cierres, hojas de reparto internas y filas vacías o solo numeradas. Las hojas desconocidas visibles no se descartan silenciosamente: sus filas quedan en revisión aparte.
3. Conservar filas con un código o datos de identidad incluso si otra fórmula carece de caché. Si únicamente hay un horario explícito sin identidad suficiente, conservar la fila aparte sin inventar un pasajero.
4. Normalizar formatos de hora admitidos por el parser existente y fechas ISO o día/mes/año explícito. Una hora numérica ambigua, una fecha ilegible o una coordenada ausente no se completan por inferencia. Las coordenadas no son obligatorias para esta etapa de ingesta.
5. No deducir la fecha de servicio a partir de la carpeta, `TODAY()` actual o la fecha esperada. Una fecha esperada sirve para marcar conflicto; no rellena una fecha ausente. Diferentes fechas dentro de un mismo sentido generan revisión.
6. Conservar valores almacenados utilizables de fórmulas como vista previa **no verificada**. Señalar fórmulas volátiles, referencias externas y cachés ausentes. No consultar archivos externos ni servicios de IA.
7. Mantener ambos registros de un posible duplicado y marcar `duplicate_candidate`. El código tiene ámbito de cliente, fecha y sentido. Los ceros iniciales de códigos textuales no se eliminan para forzar coincidencias.
8. Normalizar teléfonos chilenos completos de 9 u 11 dígitos a `+56…`, conservando el original. No agregar dígitos locales faltantes. Un teléfono no interpretable queda pendiente con evidencia conservada.
9. Vincular un terminal registrado solo por contexto explícito del operador o coincidencia normalizada con su nombre. Un terminal de otro cliente se rechaza; una discrepancia se mantiene pendiente.

Un archivo puede estar interpretado y contener solicitudes pendientes. `records` cuenta solicitudes; `unclassified_rows` cuenta filas separadas. `pending_review` cuenta solicitudes pendientes, mientras `status` también considera las hojas/filas sin clasificación. Interpretado no significa listo para operar.

## API y revisión

Reinicie cualquier Uvicorn que estuviera ejecutando la versión anterior para cargar los nuevos endpoints. Desde la raíz:

```bash
uv sync --frozen
uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Swagger: `http://localhost:8000/docs`. Se conserva el uso local de un worker; los detalles de ingesta contienen información privada y no deben compartirse, registrarse como logs ni exponerse públicamente.

| Método | Endpoint | Función |
|---|---|---|
| GET | `/v2/customers` | Clientes y códigos de perfil |
| POST / GET | `/v2/terminals` | Registrar/consultar terminales; filtro `customer_id` opcional |
| POST | `/v2/ingestions` | Importar XLSX con perfil explícito |
| GET | `/v2/ingestions` | Resúmenes de lotes |
| GET | `/v2/ingestions/{id}` | Detalles privados, solicitudes, evidencia y filas sin clasificación |
| GET | `/v2/ingestions/{id}/summary` | Reporte de lote sin contenido de celdas |
| GET | `/v2/requests/{id}` | Solicitud y revisiones |
| PATCH | `/v2/requests/{id}` | Cambiar o confirmar datos con motivo obligatorio |
| POST | `/v2/reconciliations` | Conciliar original e interno del mismo cliente/jornada |
| GET | `/v2/reconciliations/{id}` | Informe e indicador `stale` |

`POST /v2/ingestions` usa multipart: `file`, `customer_id`, `role`; opcionales `archive_date`, `expected_service_date` y `terminal_id`. No se admite CSV como entrada de solicitudes en esta iteración. El nombre del archivo no se almacena ni se utiliza para elegir cliente o fecha.

Ejemplo exclusivamente sintético de revisión:

```json
{
  "changes": {"employee_code": "SIM-001", "work_time": "05:30"},
  "confirm_fields": ["name"],
  "reason": "Datos sintéticos revisados por el operador"
}
```

`confirm_fields` resuelve las alertas de origen del campo tras una comprobación humana explícita; no rellena un valor nulo ni elimina las comprobaciones obligatorias. `changes: {"excluded": true}` excluye una solicitud únicamente por decisión humana registrada; el registro y su evidencia permanecen. Corregir una solicitud revalida su lote y marca como obsoletas las conciliaciones previas que lo utilizaban.

Las filas separadas por esquema desconocido se conservan en el detalle privado del lote. No se promueven automáticamente a solicitudes: su incorporación requiere aclarar el esquema y volver a interpretar, sin alterar los originales. No se implementó en esta versión un editor de mapeos desconocidos.

Los errores de entrada y validación de respuesta de `/v2` no devuelven los valores privados rechazados. Los errores de lectura del libro utilizan mensajes fijos sin rutas, fórmulas ni contenido de celdas. Los endpoints detallados sí devuelven información privada al operador local autorizado; los resúmenes y conciliaciones son salidas diferentes.

## Conciliación

El cuerpo de creación contiene `original_batch_id` e `internal_batch_id`. Se exige el mismo cliente y las funciones correctas; fechas archivadas distintas se rechazan cuando ambas están disponibles. Si falta el contexto archivado, el resultado advierte `archive_scope_unverified`.

Se prioriza el código de trabajador dentro del cliente y sentido. Sin código en ambos lados se permiten coincidencias exactas de nombre/teléfono o nombre/dirección, marcadas **provisionales**. No se fuerza un enlace cuando un lado tiene código y el otro no, ni se deduce identidad por abreviación del nombre. Los grupos con varias filas posibles se conservan ambiguos, sin elegir arbitrariamente una.

La fecha se compara después de vincular la identidad dentro del paquete seleccionado, permitiendo detectar fechas discordantes. Se distinguen cambios sobre campos existentes de **enriquecimientos**: por ejemplo, agregar recogida en la lista interna no se presenta como si el original trajera un horario contradictorio.

## Verificación privada de desarrollo

```bash
.venv/bin/python scripts/verify_private_ingestion.py \
  --output /tmp/novara-v02-private-summary.json
```

La utilidad no usa API, base de datos ni solver. Selecciona el contexto de carpetas antes de abrir los libros y rechaza todas las jornadas archivadas desde el **17 de octubre de 2026**. De ese modo excluye los paquetes reservados del 17 y 24, ambos clientes y todas sus etapas. No usa fechas de nombres de archivo ni cachés para incorporar casos al conjunto de desarrollo. La salida se limita a contadores; no permite escribirla dentro de la carpeta fuente.

### Resultado de la lectura local

| Comprobación | Resultado |
|---|---:|
| Nóminas originales interpretadas | **12/12 elegibles**: 10 Gran América y 2 Lo Blanco |
| Listas internas interpretadas | **12/12 elegibles**: 10 Gran América y 2 Lo Blanco |
| Solicitudes originales conservadas | 166: 139 de ingreso y 27 de término |
| Solicitudes internas conservadas | 162: 134 de ingreso y 28 de término |
| Filas auxiliares separadas para revisión | 25, en dos hojas de originales |
| Paquetes conciliados | 12 |
| Correspondencias de identidad uno a uno | 160, incluida una provisional |
| Originales sin contraparte interna | 4 |
| Internas sin contraparte original | 1 |
| Grupos ambiguos de identidad | 1: dos filas originales frente a una interna |
| Archivos reservados no abiertos | 16, incluidas **4 nóminas originales** |
| Libros reservados abiertos | **0** |
| Escrituras en la base de datos real durante la comprobación | **0** |
| Integridad antes/después de los libros abiertos | Sin cambios, comprobada por SHA-256 |

Los 166 registros originales y los 162 internos siguen pendientes de revisión: se omitió intencionadamente la vinculación de terminales durante esta comprobación y existen cachés de fórmulas no verificadas. No se afirma que esos datos estén aprobados para operar. Tampoco se afirma cobertura sobre las cuatro nóminas reservadas, que permanecieron sin abrir.

### Diferencias pendientes

Entre correspondencias uno a uno se encontraron **107 diferencias de nombre, 48 de dirección, 13 de fecha y 3 de comuna**. Son conteos por campo: no se suman como personas distintas y no implican que todas las variaciones de nombre/dirección sean errores. Se registraron aparte **133 enriquecimientos de recogida**.

Además quedan los cuatro originales sin contraparte, la incorporación interna, el grupo duplicado sin resolver y las 25 filas auxiliares sin contexto de traslado. No se eliminaron ni se completaron automáticamente.

Las alertas de origen incluyen 833 incidencias de caché no verificada, 165 de fórmula temporal y 64 de referencia externa, contadas por campo sobre originales e internos. Hay 15 incidencias de encabezado anotado en Lo Blanco, 15 solicitudes con alerta de fechas mezcladas y cuatro incidencias de obligatoriedad. Una solicitud puede tener varias incidencias. Las dos filas candidatas a duplicado se conservan.

Estos resultados corresponden solo a desarrollo; no reemplazan los totales de la auditoría inicial, que tenía un alcance mayor. Las referencias de cierre y reparto no se importaron como nuevas solicitudes ni se utilizaron para ajustar el planificador.

## Pruebas y archivos de implementación

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
UV_CACHE_DIR=/tmp/novara-v02-uv-cache uv lock --check --offline
```

Resultado: **91 pruebas aprobadas**, incluidas las 53 anteriores. Se verifican perfiles, bloques, plantillas, fórmulas con/sin caché, fechas ambiguas, terminales, duplicados conservados, correcciones persistentes, aislamiento de clientes, conciliación, migración aditiva y redacción de errores. Los libros de prueba se construyen en memoria con valores ficticios. Una prueba intercepta las lecturas de archivos y falla si se abre un archivo reservado de ejemplo.

Hay cuatro advertencias de dependencias ya presentes: tres de SWIG y una de la adaptación HTTPX de Starlette. No hubo fallos de pruebas. La comprobación de `uv.lock` es local y las dependencias se mantienen fijadas.

Implementación: [modelos](../backend/app/models/ingestion.py), [entidades](../backend/app/models/entities.py), [perfiles](../backend/app/ingestion/profiles.py), [lector](../backend/app/ingestion/real_excel.py), [persistencia/revisión](../backend/app/services/ingestion.py), [conciliación](../backend/app/services/reconciliation.py), [API](../backend/app/api/ingestion.py) y [verificación privada](../scripts/verify_private_ingestion.py).

No se modificaron `optimization/solver.py`, `optimization/travel.py`, `services/planning.py`, los modelos de planificación v0.1 ni `ingestion/excel.py`; se compararon sus hashes con el inicio de la iteración. No se hicieron commits, pushes, envíos de mensajes ni llamadas a integraciones externas.
