# Reglas de negocio

## Contexto proporcionado por el documento de trabajo

Estas reglas se toman del encargo; no equivalen a una validación operativa presencial con Novara:

- El cliente es Gran América y el destino es su depósito.
- Los pasajeros se inscriben por Excel y requieren supervisión humana ante datos ambiguos.
- El escenario inicial contempla tres vans y aproximadamente 13–14 pasajeros por jornada.
- Los ingresos habituales son 04:00, 05:00, 05:30 y 06:00.
- Las capacidades y disponibilidades deben respetarse; un conductor no puede realizar viajes simultáneos.
- No se deben inventar direcciones, horarios ni presentar una simulación como tráfico real.
- El máximo de hasta dos viajes requiere reglas adicionales confirmadas.

## Hipótesis configurables implementadas

| Regla | Valor inicial | Interpretación |
|---|---|---|
| Capacidad | Definida al registrar van (demo: 6) | Solo pasajeros; confirmar si el asiento del conductor ya está descontado |
| Tiempo a bordo | 60 minutos | Inicio de recogida a llegada; incluye abordaje y recogidas posteriores |
| Anticipación | 10 minutos | Llegar al depósito antes del ingreso |
| Llegada temprana adicional | 30 minutos | Límite de espera antes de la anticipación exigida |
| Abordaje | 60 segundos por pasajero | Se aplica incluso en ubicaciones coincidentes |
| Disponibilidad | 00:00–08:00 | Configurable por conductor; inicio y regreso dentro del turno |
| Comunas | Sin filtro | `allowed_communes` por vehículo; comparación normalizada |
| Origen del vehículo | Depósito | No se conoce ubicación real del conductor/van |
| Viajes ejecutables | 1 por recurso y fecha | Simplificación explícita; el segundo viaje no está implementado |

Para cada pasajero: `ingreso - anticipación - llegada_temprana <= llegada_ruta <= ingreso - anticipación`. Si varios pasajeros comparten una van, la llegada debe pertenecer a la intersección de sus ventanas. Todos los pasajeros incluidos deben asignarse exactamente una vez; la nómina nunca se completa omitiendo silenciosamente pasajeros difíciles.

La van y el conductor quedan reservados por un plan factible vigente para su fecha. Otros servicios no pueden reutilizarlos ese día en este modelo de un viaje. Para fechas adyacentes se bloquea también un recurso si su disponibilidad puede solaparse con un viaje nocturno existente. Esto evita conflictos pero puede rechazar secuencias que serían factibles con reutilización; esa ampliación queda pendiente.

`max_trips=1|2` expresa el límite superior solicitado al conductor; con el motor actual ambos permiten **como máximo un viaje**. El contrato de solicitud de optimización admite únicamente `max_trips_per_vehicle=1`. El Excel indica `trip_number=1`.

## Validación humana

Nombre, dirección, comuna, hora y fecha son obligatorios. La dirección debe tener un mínimo de ocho caracteres y número o `s/n`; es una comprobación estructural, no una validación postal. Las coordenadas deben existir y estar en rango, pero no se presume que correspondan a la dirección. El operador debe verificarlas; no hay geocodificador.

Duplicado probable: mismo nombre/identificador, dirección, comuna, horario y fecha normalizados. No se elimina automáticamente. El operador puede corregirlo o excluirlo con `excluded=true`, conservando el original. Excluir un registro no autoriza inventar otro pasajero. Los registros incluidos con advertencias o errores bloquean la optimización. Las filas excluidas se identifican en la nómina y no ocupan plazas.

Toda corrección y toda nueva planificación invalidan exportaciones anteriores. Un plan inviable informa capacidad insuficiente, pasajeros sin vehículo elegible, tiempos mínimos incompatibles o conflictos conjuntos. Si la búsqueda no demuestra imposibilidad, se indica `no_solution` y se recomienda revisar restricciones o ampliar el límite.

## Por confirmar antes de operación

Coordenadas y dirección real del depósito, capacidades utilizables, posiciones iniciales, margen por turno, duración de abordaje, máximo a bordo, comunas y límites territoriales, tiempo entre viajes, retorno y descanso de conductores, reutilización de vans, asignaciones alternativas de conductor, políticas de exclusión de pasajeros y cambios de hora en Santiago. No hay aprobación operacional automática ni envío de mensajes.
