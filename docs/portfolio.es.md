# Caso de portfolio: Novara RouteOps

[English](portfolio.md) · [Resumen del proyecto](../README.es.md)

## Problema y usuarios

Un operador de transporte de personal recibe Excel con columnas variables, ubicaciones incompletas y distintos turnos. Planificar exige respetar capacidad, disponibilidad de conductores, ventanas de llegada y datos confiables. Una ruta aparentemente razonable basada en una importación incorrecta no es un resultado aceptable.

El flujo implementado muestra las ambigüedades antes de planificar. La demostración pública utiliza pasajeros ficticios y puntos públicos de referencia. Los archivos operativos privados no forman parte de la entrega.

## Recorrido del producto

1. Importar el Excel de ejemplo y revisar procedencia e incidencias.
2. Corregir una comuna faltante y aprobar las ubicaciones.
3. Preparar flota compartida, terminales, matriz de viaje y restricciones.
4. Calcular una vista previa conjunta de ingresos y revisar asignados y pendientes.
5. Descargar el Excel con horarios, identificadores y una hoja de supuestos.

El perfil alojado fija los factores e independiza las sesiones temporales. El perfil local permite configurar la operación. Cada modo tiene permisos y límites distintos.

## Capacidades demostrables

| Área | Implementación | Evidencia |
| --- | --- | --- |
| Calidad de entrada | Perfiles deterministas, rechazo de fórmulas, límites y procedencia | Pruebas de ingesta y generadores ficticios |
| Consistencia | Correcciones humanas e invalidación de planes obsoletos | Pruebas de API, revisión y preparación |
| Optimización | CP-SAT con capacidad, turnos y viajes secuenciales | Pruebas conjuntas y estados de resultado explícitos |
| Aplicación | React, FastAPI, contenedor de un origen y sesiones aisladas | Prueba de integración alojada y escenario de navegador |
| Integración de IA | Adaptador opcional Bedrock con validación estricta | Pruebas de respuestas malformadas y fallos del proveedor |
| Evaluación | Etiquetas versionadas, desarrollo/prueba y métricas por grupo | `evals/headers/` y `scripts/evaluate_headers.py` |
| Reproducibilidad | Dependencias fijadas, Docker probado y CI definido | Lockfiles, Dockerfile y workflows |

## Evidencia observada

Antes de preparar el portfolio, el ensayo Linux completó autenticación, importación de dos nóminas, corrección de comunas, consulta de factores, cálculo, mapa y exportación. Una ejecución asignó 16 solicitudes en 5 viajes sin pendientes; salud respondió a los 7,25 segundos y la interacción de planificación demoró 3292 ms. Una muestra posterior registró 173,1 MiB de memoria. Son observaciones locales de Docker: no son un benchmark AWS, una medición de memoria máxima ni una prueba de óptimo global.

La IA todavía no tiene resultados de un modelo real. Su línea base determinista se reproduce con el conjunto sintético publicado. Las pruebas de SDK con respuestas simuladas no demuestran precisión, resistencia general a inyecciones ni valor económico del modelo.

## Aporte al perfil de AI Engineer

El proyecto reúne contratos de datos, integración de producto, optimización, empaquetado para nube y un límite de IA evaluable. El aporte propuesto del modelo es interpretar etiquetas desconocidas; las reglas verificadas y el solver conservan la responsabilidad de planificar.

La pregunta experimental es si Bedrock mejora la recuperación de campos desconocidos sin aumentar correspondencias incorrectas. Se miden coincidencia exacta, precisión, recall, fallos, latencia y tokens. La futura integración en la aplicación dependerá de esos resultados.

## Alcance y pendientes

Es un prototipo supervisado. Las vistas previas conjuntas no reservan recursos de despacho, las matrices no incluyen tráfico en vivo y SQLite en un proceso no resuelve concurrencia distribuida. Faltan la publicación en nube, la evaluación con un modelo real y la interfaz de revisión de propuestas de IA. No se atribuyen uso productivo, ahorro de negocio ni mejoras de precisión sin evidencia.

Se utiliza asistencia de IA en el desarrollo. La autoría profesional debe demostrarse explicando las restricciones, revisando los cambios y reproduciendo los resultados. Temas para entrevista: exclusión de valores personales del prompt, abstención ante ambigüedad, diferencia entre timeout e inviabilidad demostrada, y separación entre vista previa y confirmación operativa.

[Verificación actual y capturas sintéticas](portfolio-verification.md).
