# Verificación de la fase 1

Fecha de trabajo: **19 de noviembre de 2026**, America/Santiago.

## Comprobaciones completadas

- Instalación local con `UV_CACHE_DIR=/tmp/novara-uv-cache uv sync`, que generó `uv.lock` y el entorno Python 3.12.5.
- `ruff check .`: sin errores.
- `ruff format --check .`: formato correcto en todos los archivos revisados.
- `pytest -q`: **53 pruebas aprobadas**. Cuatro advertencias de dependencias: tres avisos de SWIG/OR-Tools y uno de Starlette sobre su adaptación de HTTPX. No hubo fallos de pruebas.
- `uv lock --check --offline`: lock consistente con `pyproject.toml`.
- Compilación de módulos Python y configuración `docker compose config --quiet`: correctas.
- API ejecutada con Uvicorn en `127.0.0.1:8000`, un worker.
- HTTP real: `/health`, `/docs`, `/openapi.json`, `/vehicles`, `/drivers`, `/depots` y `/services` respondieron 200.
- `scripts/demo.py --case D`: seis pasajeros, resultado factible, una ruta simulada y exportación XLSX con seis paradas. Archivo de muestra: `/tmp/novara-simulation.xlsx`.
- `scripts/demo.py --case E`: resultado inviable, diagnóstico de tiempo máximo a bordo y pasajeros afectados.
- `scripts/demo.py --case C`: seis registros pendientes con errores esperados. Se corrigieron por HTTP cuatro filas y se excluyó un duplicado: cero errores pendientes, cinco pasajeros planificados y exportación `/tmp/novara-corrected-simulation.xlsx`.
- Pruebas adicionales verificaron que dos solicitudes concurrentes no reservan las mismas vans, que se respeta el tiempo acumulado a bordo entre recogidas y que las comunas permitidas determinan las asignaciones.

Los datos locales generados son exclusivamente sintéticos; `routeops.db` está excluido de Git. Los planes factibles de demostración reservan su flota. Para repetir todos los escenarios con recursos libres puede utilizarse otra base SQLite mediante `DATABASE_URL`.

## Docker: resultado y bloqueo ambiental

`docker build -t novara-routeops:local .` **construyó una primera imagen correctamente**, usando Python 3.12.16 y dependencias Linux ARM64. La descarga inicial tomó varios minutos.

Después se ajustó el Dockerfile para separar la instalación de dependencias del código y usar caché BuildKit, y se completaron las últimas validaciones de entrada. La reconstrucción de esa versión final y su arranque con Compose **no quedaron verificados**: el equipo agotó el espacio disponible y Docker pasó a devolver `read-only file system` al crear un contenedor. Se retiró la caché temporal de uv creada por esta tarea. El intento de crear `novara-routeops-smoke` no llegó a iniciar un contenedor.

No se reinició globalmente Docker ni se eliminaron imágenes, volúmenes o datos de otros proyectos. La API local y las 53 pruebas funcionan independientemente de ese problema. El pipeline de GitHub Actions está creado, pero no se ha ejecutado remotamente: no se hicieron commits ni pushes.

Para completar la verificación del contenedor, con espacio suficiente y el almacenamiento de Docker recuperado:

```bash
docker compose build
docker compose up -d --wait
curl http://localhost:8000/health
```

Debe liberarse el puerto 8000 deteniendo el Uvicorn local antes de iniciar Compose. Si Docker sigue indicando almacenamiento de solo lectura, recuperar/reiniciar Docker Desktop teniendo en cuenta los otros contenedores del equipo. Esto no afecta los pasos de ejecución local documentados en el README.
