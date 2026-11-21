# Decisiones arquitectónicas

Los puntos 1–12 registran las decisiones del MVP inicial. El estado actual, incluido CP-SAT multiviaje, React y el experimento Bedrock, se describe en [Arquitectura](architecture.md).

1. **Parser determinista primero.** Alias y reglas de hora auditables resuelven los formatos conocidos sin credenciales ni coste de IA. Estructuras desconocidas se reportan. `HeaderInterpreter` permite ampliar la interpretación con aprobación humana más adelante.
2. **Modelos de entrada separados de persistencia.** Pydantic v2 valida contratos; SQLAlchemy mantiene relaciones y unicidad. JSON preserva originales y estructuras de resultados sin crear tablas prematuras por cada parada. Antes de consultas analíticas y PostgreSQL se normalizarán entidades y añadirán migraciones.
3. **Fecha del servicio explícita.** El formulario proporciona la fecha; contradicciones en filas bloquean revisión. No se infiere una fecha a partir del reloj del servidor ni se adivinan horas numéricas ambiguas.
4. **Coordenadas manuales en el MVP.** No se geocodifica una dirección incompleta. Una advertencia de coordenadas faltantes exige corrección antes de planificar.
5. **Matriz desacoplada.** OR-Tools recibe una matriz de segundos/metros validada. El modelo sintético identifica sus constantes y su procedencia en API y Excel; el adaptador real es un contrato con función inyectable, no una integración terminada.
6. **Un viaje explícito.** La capacidad inicial es suficiente para demostrar el flujo. No se crean vehículos virtuales que permitirían viajes simultáneos del mismo conductor. Se reservan recursos entre servicios, con exclusión conservadora de turnos nocturnos superpuestos. El multiviaje requerirá secuenciación, descansos y posiciones iniciales confirmadas.
7. **Primera solución factible reproducible.** El orden estable y el límite de una solución priorizan verificabilidad del MVP. No se garantiza distancia mínima; el coste usa segundos de desplazamiento y abordaje. IDs y fecha de creación varían entre ejecuciones, no la secuencia probada.
8. **Diagnósticos honestos.** Capacidad y cotas inferiores permiten demostrar algunos fallos. Un fracaso o timeout heurístico no se etiqueta automáticamente como inviabilidad. No se promete un conjunto mínimo de restricciones conflictivas.
9. **Resultados versionados y obsoletos.** Corregir datos o ejecutar otra planificación conserva los resultados previos con `stale=true`; se bloquea su exportación. Los originales del Excel no se sobrescriben. No existe aún una auditoría completa de cada edición.
10. **SQLite, un proceso.** Las operaciones se serializan con un bloqueo de aplicación. Esta decisión reduce complejidad para uso local; no sirve como bloqueo entre procesos o instancias. La imagen y los comandos fijan un worker.
11. **Dependencias reproducibles.** `uv.lock` fija versiones, hashes y marcadores de plataforma. Python mínimo 3.11, desarrollo y CI con 3.12. Docker instala únicamente dependencias de producción y el paquete sin modo editable.
12. **Exportación trazable.** Fechas completas para recogidas nocturnas, tiempos individuales, observaciones y parámetros en hoja separada. Los textos que podrían interpretarse como fórmulas se escapan. No se exportan resultados inviables u obsoletos.

Se reutilizaron los directorios del repositorio inicial. `database.py` y `scripts/` se añadieron para centralizar sesiones e ilustrar el flujo; el frontend React y los proveedores geoespaciales pertenecen a etapas posteriores, descritas en la arquitectura actual.

13. **IA acotada a propuestas de encabezados.** Amazon Bedrock usa un contrato separado de solo etiquetas, sin filas de pasajeros, sin escrituras ni herramientas. La evaluación compara vocabulario determinista y modelo sobre los mismos casos. No se aplica una propuesta automáticamente.
14. **Publicación por evidencia.** Se separan resultados locales, CI preparado, despliegue pendiente y calidad de modelo sin medir. Los documentos internos permanecen locales e ignorados.
