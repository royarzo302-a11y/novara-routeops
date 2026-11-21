# Preparación previa a la ponderación

En **Preparación** se reúnen los factores que antes estaban dispersos: terminal habitual por cliente, base compartida de salida, recogidas aprobadas, matriz vial y reglas del motor. La pantalla conserva los componentes y colores del panel operativo. Al importar una nómina se abre esta preparación; en la demo alojada las incidencias se revisan primero en Solicitudes.

## Operación local

1. Registra terminales y bases con nombre, dirección y coordenadas verificadas desde «Registrar un terminal o una base».
2. Selecciona un terminal por cliente y una base de salida. Se puede elegir entre varias bases existentes. Guarda los factores antes de cargar el Excel para que el importador use el terminal elegido.
3. Los destinos de las solicitudes ya cargadas se corrigen en Solicitudes. Cambiar el terminal habitual no reasigna una nómina anterior.
4. Revisa las coordenadas de recogida en Ubicaciones. El cálculo intenta reutilizar aprobaciones de la misma persona y dirección; las ubicaciones nuevas requieren aprobación humana.
5. Usa el proveedor OSRM local autorizado o importa una matriz JSON verificada. El selector muestra matrices estáticas no sintéticas. Una matriz debe coincidir con la nómina, terminales, flota, base y aprobaciones vigentes.
6. Guarda las reglas y pulsa **Ponderar rutas**. El cálculo rápido exige todos los acercamientos de la jornada validados, sus destinos georreferenciados y recogidas aprobadas. No calcula silenciosamente solo un subconjunto. La selección deliberada de un subconjunto sigue disponible en Planificación.

Los factores se guardan en una tabla SQLite adicional, `operation_settings`; las tablas y registros previos se conservan. Las API de preparación e importación de matrices requieren el token de operador. Las reglas se envían tanto en el flujo rápido como en el manual y se agregan al resultado y a la hoja **Supuestos** del Excel.

## Matriz aportada

En «Tiempos y reglas de cálculo → Cargar una matriz vial verificada», descarga la plantilla de la nómina. Completa todos los elementos `null` de `matrix.seconds` y `matrix.meters` con enteros no negativos procedentes de un proveedor vial, manteniendo el orden de `matrix.location_keys`. Indica `matrix.source` y una fecha `matrix.verified_at` con zona horaria. La diagonal debe ser cero. La plantilla sin completar se rechaza. Importa el JSON y guarda la selección.

La API `POST /v5/operator/matrices/import` exige recogidas aprobadas y registra una instantánea de coordenadas y aprobaciones. Rechaza dimensiones, claves y valores inválidos. El plan devuelve 409 si esa instantánea cambia. La importación es una declaración de procedencia del operador, no una verificación externa de la calidad vial. Esta versión exige todos los tramos alcanzables; para tramos inaccesibles usa el proveedor vial local que ya admite esa condición.

## Prueba ceteris paribus

El perfil alojado conserva terminales, base, tres vans, capacidades, turnos, red vial de ejemplo y reglas constantes. El servidor aplica las reglas fijas aunque una petición intente sobrescribirlas. La pantalla permite consultarlas, con los campos bloqueados.

| Factor | Valor de prueba |
| --- | --- |
| Flota | 3 vans de 12 plazas, conductores 00:00–08:00, hasta 2 viajes |
| Preparación entre viajes | 600 segundos |
| Embarque por pasajero | 60 segundos |
| Margen de llegada | 10 minutos |
| Anticipación máxima | 30 minutos |
| Máximo a bordo | 60 minutos |
| Búsqueda | 3 segundos |
| Red vial | Catálogo y matriz de ejemplo incluidos en la imagen |

La asignación y secuencia se recalculan al cargar pasajeros; los tiempos viales no incluyen tráfico en vivo. El resultado es una vista previa, sin garantías de óptimo global. La demo admite únicamente los Excel ficticios emitidos por esa misma sesión. No es todavía un piloto abierto a nóminas operativas arbitrarias. Las sesiones duran dos horas y desaparecen al reiniciar o actualizar el contenedor.

El despliegue de prueba AWS está preparado en [deployment-aws.md](deployment-aws.md).
