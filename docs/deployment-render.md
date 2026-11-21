# Despliegue de la demo de Novara en Render

Un Web Service Docker Free en Oregón sirve React y FastAPI en el mismo origen. Vite solo compila los assets durante el build. Uvicorn escucha en `0.0.0.0:$PORT` con un worker. Las llamadas del navegador usan `/api`. `GET /health` confirma la disponibilidad del servidor sin consultar SQLite ni invocar el optimizador.

El contenedor incluye OpenPyXL, OR-Tools y la matriz de ejemplo basada en OpenStreetMap. El mapa muestra marcadores y conexiones ilustrativas sin llamar a un proveedor externo. El modo local de VS Code conserva Vite y su proxy. Docker Compose continúa construyendo el objetivo `backend-local`.

## Probar la imagen localmente

Requiere Docker Desktop en funcionamiento. Genera una clave temporal fuera de Git y arranca el contenedor en loopback.

```sh
docker build -t novara-routeops:render-v06 .
test -e .env.render-local || (umask 077; printf 'NOVARA_DEMO_PASSWORD=%s\n' "$(openssl rand -hex 32)" > .env.render-local)
docker run --rm --name novara-render-demo --env-file .env.render-local \
  -e PORT=10000 -e NOVARA_DEMO_HTTP=1 -p 127.0.0.1:8174:10000 \
  novara-routeops:render-v06
```

Abre `http://127.0.0.1:8174/` e ingresa el valor de `NOVARA_DEMO_PASSWORD`. `curl -fsS http://127.0.0.1:8174/health` debe devolver `{"status":"ok"}`.

Si Docker está bloqueado, puedes verificar el mismo origen en macOS con las dependencias locales. Esta prueba no mide el comportamiento del contenedor Linux.

```sh
npm --prefix frontend ci
VITE_NOVARA_HOSTED_DEMO=1 npm --prefix frontend run build
set -a
. ./.env.render-local
set +a
PYTHONPATH=backend NOVARA_DEMO_HTTP=1 NOVARA_WEB_ROOT=frontend/dist \
  .venv/bin/uvicorn app.hosted:application --factory --host 127.0.0.1 --port 8174 \
  --workers 1 --limit-concurrency 24 --no-access-log
```

Pruebas automatizadas

```sh
.venv/bin/pytest
.venv/bin/ruff check backend scripts
npm --prefix frontend test
```

Desde `frontend/`, la prueba `tests/hosted.mjs` requiere `NOVARA_DEMO_PASSWORD` y `CHROME_BIN` en el entorno. Usa el puerto local 8174 por defecto. `NOVARA_TEST_UI` permite verificar otra URL con una sesión temporal.

## Crear el Web Service desde GitHub

1. Verifica el build y el flujo desde una imagen Linux antes de publicar. Revisa los archivos incluidos en Git y crea el remoto privado con autorización. La rama prevista es `main`.
2. En Render, selecciona **New → Blueprint** y conecta el repositorio privado de GitHub. Elige `main` y `render.yaml` de la raíz.
3. Comprueba que el Blueprint crea un único **Web Service**, runtime **Docker**, plan **Free**, región **Oregon**, contexto `.`, Dockerfile `./Dockerfile` y health check `/health`.
4. Crea una clave nueva, por ejemplo con `openssl rand -hex 32`. Escríbela como `NOVARA_DEMO_PASSWORD` en el formulario de Render. La longitud mínima es de 32 caracteres.
5. Inicia el primer despliegue tras autorizarlo. Render muestra la URL definitiva `https://<nombre-asignado>.onrender.com/`. Prueba `/health` y el flujo desde otro dispositivo. Comparte la dirección y la clave por separado.

El servicio también se puede crear con **New → Web Service** usando las mismas opciones del Blueprint. Deja vacío **Docker Command** para utilizar el comando de la imagen y desactiva **Auto-Deploy**.

| Variable | Configuración |
| --- | --- |
| `NOVARA_DEMO_PASSWORD` | Obligatoria. Se crea fuera de Git y se escribe en Render. |
| `PORT` | Render lo proporciona. La imagen tiene 10000 como valor de respaldo. |
| `NOVARA_WEB_ROOT` | La imagen usa `/app/web`. |
| `NOVARA_DEMO_HTTP` | Solo para el ensayo HTTP local en loopback. Render exige cookie segura. |
| `VITE_NOVARA_HOSTED_DEMO` | La etapa de compilación Docker ya fija `1`. |

El perfil alojado inicializa SQLite en memoria y usa un secreto interno de API generado al arrancar. Las sesiones tienen una cookie `HttpOnly`, `SameSite=Strict` y `Secure` bajo HTTPS. Cada navegador usa una base aparte durante hasta dos horas. Los endpoints administrativos y la documentación interactiva quedan fuera de la lista de rutas habilitadas. La imagen copia únicamente el catálogo público y la matriz de ejemplo. Se admiten los Excel exactos emitidos para la sesión y una corrección de comuna que coincida con el punto público. La demo no configura Gmail, SMS ni geocodificación externa. El backend limita las solicitudes a 512 KiB, las jornadas a 20 acercamientos, la búsqueda a tres segundos, y las sesiones concurrentes a ocho bases de datos temporales.

## Validar la demo

En una sesión nueva, descarga `demo-gran-america.xlsx` y `demo-lo-blanco.xlsx`. Carga el primero, corrige la comuna faltante a **Pudahuel** y guarda. Carga el segundo en la misma sesión y corrige su primera comuna a **Maipú**. Abre **Revisar preparación**, consulta los factores fijos y pulsa **Ponderar rutas** para planificar ambas nóminas con las tres vans compartidas, con hasta dos viajes por van. Revisa el mapa y descarga la planificación. Las filas vacías y encabezados repetidos de los ejemplos se ignoran. **Restablecer demo** limpia el escenario de ese navegador.

## Actualizar y resolver problemas

- El despliegue automático queda desactivado. Tras validar y autorizar una actualización, usa **Manual Deploy → Deploy latest commit**. El reinicio deja vacías las sesiones.
- Una instancia Free se suspende después de 15 minutos sin solicitudes. El primer acceso luego de la suspensión puede tardar alrededor de un minuto. Los archivos locales y los datos de SQLite son efímeros. Render aplica cuotas de horas, red y compilación. [Plan Free](https://render.com/docs/free)
- Si el inicio falla, revisa que `NOVARA_DEMO_PASSWORD` esté definida. Si falla la autenticación local HTTP, comprueba que `NOVARA_DEMO_HTTP=1` se use solo en localhost y que el navegador acepte cookies.
- Si se rechaza un Excel, vuelve a descargarlo desde la misma sesión. Es posible corregir la falta de comuna en la app. Las modificaciones al archivo descargado cambian su huella y se rechazan.
- Si Docker Desktop falla al escribir `meta.db`, revisa el espacio del Mac y el disco virtual desde Docker Desktop antes de repetir la compilación. No borres volúmenes o imágenes con datos sin una revisión y autorización.
- Para medir Linux, con la imagen corriendo registra `docker stats --no-stream novara-render-demo` en reposo y durante la prueba conjunta. Mide desde el arranque hasta el primer `/health` válido y registra el tiempo del `POST /api/v3/plans/preview`. Compara con el límite Free vigente. [Blueprint](https://render.com/docs/blueprint-spec) · [Docker](https://render.com/docs/docker)

## Resultado de la verificación local

- 127 pruebas Python, 2 pruebas de componentes, Ruff y build Vite aprobados.
- Chrome completó autenticación, descarga de ambas nóminas, carga, corrección de comunas, cálculo conjunto, mapa, exportación y recarga de la URL de Planificación. Se calcularon 4 viajes, 16 recogidas y 0 solicitudes sin asignar. La prueba observó cero solicitudes a otros orígenes.
- En macOS, con un worker, una ejecución midió 1,46 s hasta el primer `/health`, 137,7 MiB de RSS máximo muestreado durante la prueba y 3,13 s desde el clic de cálculo hasta la respuesta, incluyendo la preparación de la matriz.
- Docker Desktop falló antes de construir la imagen porque su archivo interno `meta.db` estaba en modo de solo lectura. El Mac informaba 3,0 GiB libres y 99 % de uso. No hay resultado de build Docker, arranque ni métricas en Linux. No se borraron datos de Docker.
- La rama local se llama `main` y todavía no tiene commits ni remoto. `data/real/` y los archivos de entorno están ignorados. La comprobación por patrones no encontró firmas de credenciales en los archivos candidatos. No se publicó el repositorio ni se desplegó en Render.
