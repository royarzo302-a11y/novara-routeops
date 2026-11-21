# Motor de optimización v0.3

`POST /v3/plans/preview` calcula un plan para una fecha y una flota compartida de tres vans registradas. Recibe solicitudes validadas de lotes originales de la ingesta v0.2. El resultado identifica van, conductor, cliente, terminal, secuencia de recogidas, tiempos a bordo, horarios, distancias y solicitudes pendientes de asignación.

Cada viaje sirve a un cliente y termina en uno de sus terminales. Cada van dispone de hasta dos viajes para el conjunto de la jornada. El conductor permanece asignado a la misma van y su límite de viajes puede reducir el máximo de esa van. La capacidad por defecto de una van nueva es 12 plazas. Puede registrarse con una capacidad inferior. La v0.3 aplica el menor valor entre 12 y la capacidad registrada. Los identificadores de la flota deben representar vehículos físicos distintos.

## Ejecución local

Reinicie Uvicorn para cargar la nueva ruta de API y abra Swagger en `http://localhost:8000/docs`.

1. Registre tres vans en `POST /vehicles` y un conductor por van en `POST /drivers`. Envíe `max_trips: 2` si el conductor está habilitado para dos viajes. El valor anterior por defecto sigue siendo uno.
2. Registre los terminales con coordenadas revisadas en `POST /v2/terminals`. Importe y revise las solicitudes con `/v2/ingestions` y `PATCH /v2/requests/{id}`.
3. Envíe a `POST /v3/plans/preview` la fecha operativa en `service_date`, los lotes originales en `original_batch_ids` y los tres IDs de van en `vehicle_ids`. Para cada recurso disponible, indique en `vehicle_origins` su ubicación inicial, indexada por ID de van. Proporcione los puntos de recogida en `pickup_points`, indexados por ID de solicitud. Cada punto requiere latitud, longitud y procedencia en `source`.
4. Adjunte `matrix` con tiempos en segundos, distancias en metros, `source`, `verified_at` con zona horaria y `location_keys`. Use `pickup:<id de solicitud>`, `terminal:<id de terminal>` y `origin:<id de van>`. Filas y columnas siguen el orden de esas claves. Las tablas son cuadradas y dirigidas, con diagonal cero. Deben corresponder a los puntos aportados y contener todos los pares que el motor requiera. La API también admite un proveedor `TravelTimeProvider` inyectado al crear la aplicación.

La matriz suministrada lleva la procedencia y fecha declaradas por el operador. RouteOps valida su estructura, pero la verificación de su origen y correspondencia con las coordenadas depende de quien la suministra. El resultado indica `simulation: false` para esa matriz o para un proveedor configurado que entrega datos verificados, y `simulation: true` para el proveedor de pruebas cuando se habilita explícitamente en la aplicación de pruebas. Si el prechequeo resuelve el resultado sin usar matriz, los metadatos de viaje son nulos.

## Restricciones y configuración

- La llegada de cada viaje cae en la intersección de las ventanas de sus pasajeros. Para cada solicitud, el límite se calcula restando el margen de anticipación al ingreso. La ventana se abre hasta 30 minutos antes de ese límite por defecto.
- Los valores iniciales son 10 minutos de anticipación, 60 minutos máximo a bordo, 60 segundos de abordaje y 600 segundos de preparación entre viajes. Son parámetros configurables. El tiempo a bordo cuenta desde el inicio de la recogida hasta la llegada e incluye abordajes y tramos intermedios.
- La van sale de su origen declarado hacia la primera recogida. Para el segundo viaje dispone primero de tiempo de preparación y luego se desplaza desde el terminal anterior hasta la nueva primera recogida. Los tiempos efectivos, incluidos los desplazamientos vacíos, deben caber en el turno del conductor. `dispatch_at` marca la salida hacia la primera recogida, después de la preparación si corresponde. Los viajes no contemplan esperas con pasajeros a bordo ni un retorno tras la última entrega.
- La capacidad se aplica por viaje. `allowed_communes` restringe las recogidas de cada van. Una lista vacía permite todas las comunas. Una van o conductor no disponible, sin origen o reservado por un plan anterior del MVP queda fuera del conjunto elegible.
- El modelo usa [CP-SAT de OR-Tools](https://developers.google.com/optimization/cp/cp_solver) con tiempos enteros. Prioriza la cobertura y, a igualdad de cobertura, reduce el tiempo de conducción y penaliza el uso de viajes. Una solución factible obtenida en el límite de búsqueda puede ser parcial. El motor distingue esa situación de un resultado óptimo que confirma que las restricciones conjuntas impiden cubrir todas las solicitudes.
- Las solicitudes no asignadas incluyen su motivo, por ejemplo revisión pendiente, punto de recogida sin verificar, continuación bajo restricciones incompatibles o búsqueda interrumpida. `joint_constraints` indica que el conjunto no pudo cubrirse por completo bajo las reglas activas y no atribuye cada omisión a una sola regla.

## Límites de la versión

La unidad de planificación es una fecha de servicio. Se admiten recogidas la noche anterior dentro de un turno nocturno. Para un turno cuyo fin es anterior a su comienzo, el comienzo se sitúa en el día previo. Los horarios se expresan en hora civil de Santiago. El motor todavía no resuelve las transiciones del horario de verano ni planifica retornos de término. Estos aparecen con `unsupported_direction`, pues falta confirmar sus ventanas y su cómputo como viaje.

La v0.3 entrega una vista previa con hasta 60 solicitudes elegibles por llamada. La protección frente a solapamientos cubre los viajes de ambos clientes calculados juntos, y la API consulta las reservas vigentes del MVP. La vista previa carece de una confirmación o reserva persistente propia. Las vistas previas de una fecha son alternativas y no deben combinarse como despachos independientes.

El flujo anterior de simulación sigue disponible en `/services`. Para la v0.3, las pruebas usan matrices sintéticas en memoria. Las jornadas de validación del 17 y 24 de octubre quedaron fuera de la calibración y verificación del motor.
