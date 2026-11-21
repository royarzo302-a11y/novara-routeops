# Frontend v0.5

El panel de Novara permite importar una nómina, revisar solicitudes, aprobar ubicaciones y calcular una jornada conjunta. La vista previa incluye el mapa local y descarga a Excel.

## Abrir desde VS Code

Requisitos: Node 22 o posterior, Python y el entorno `.venv` del repositorio.

1. En la terminal de backend, ejecute los comandos siguientes. Conserve el token que ha configurado para iniciar sesión en el panel.

   ```bash
   uv sync --frozen
   export NOVARA_GEO_TOKEN='reemplace-por-un-token-local-privado'
   uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
   ```

2. En otra terminal, ejecute lo siguiente.

   ```bash
   cd frontend
   npm ci
   npm run dev
   ```

3. Abra `http://localhost:5173` e introduzca el token. Vite envía las solicitudes bajo `/api` a FastAPI en el puerto 8000. La regla CORS para acceso directo admite únicamente `localhost:5173` y `127.0.0.1:5173`, los métodos usados por el panel y las cabeceras de autenticación y contenido. El token y los datos de sesión quedan en memoria. Cerrar sesión descarta el estado de pantalla.

## Utilizar el panel

1. Seleccione la fecha operativa. En **Importar Excel**, seleccione cliente y terminal y cargue un archivo `.xlsx`. Puede registrar un terminal con coordenadas verificadas en la misma pantalla.
2. En **Solicitudes**, revise el estado, corrija campos y confirme únicamente los valores contrastados con la fuente. Deje pendientes las ambigüedades sin resolver.
3. En **Ubicaciones**, busque candidatos mediante Nominatim local o registre manualmente un punto verificado con su motivo. El mapa no carga teselas externas.
4. En **Flota**, registre tres vans compartidas y asigne un conductor a cada una. Configure capacidad, disponibilidad, turno y máximo de viajes del conductor. Para vans nuevas, el panel propone 12 plazas. El máximo físico de dos viajes por van se aplica en el motor.
5. En **Planificación**, seleccione acercamientos validados, tres vans y sus orígenes. Use una matriz guardada que corresponda a las solicitudes y orígenes o genere una matriz con OSRM local. Seleccionar una matriz existente recupera sus orígenes.
6. Ejecute el plan. Revise las horas estimadas, la secuencia, los motivos de no asignación y la categoría de la matriz. Descargue el Excel de la vista previa. El archivo conserva los IDs de solicitud, van, conductor y terminal, las horas y los motivos, de modo que puede relacionarse con los registros de origen.

La generación de matrices viales requiere un proveedor autorizado. La aprobación manual puede hacerse sin geocodificador cuando el operador ya conoce la ubicación. Consulte la configuración de [proveedores geoespaciales](geospatial-v04.md). Las conexiones discontinuas en el mapa son esquemáticas. La geometría de calles y el compromiso de reservas operativas siguen pendientes.

## Verificación con datos ficticios

```bash
cd frontend
npm test
npm run build
```

La prueba de navegador usa una API aislada en memoria e instala únicamente un cliente de automatización. Requiere un Chrome local. Desde la raíz, en una terminal libre:

```bash
NOVARA_BROWSER_TEST_TOKEN=novara-browser-fixture PYTHONPATH=backend \
  .venv/bin/uvicorn scripts.frontend_demo:app --host 127.0.0.1 --port 8001
```

En una segunda terminal, dentro de `frontend`, ejecute `NOVARA_DEV_API_PORT=8001 npm run dev`. En una tercera, también dentro de `frontend`, ejecute:

```bash
NOVARA_BROWSER_TEST_TOKEN=novara-browser-fixture CHROME_BIN='/ruta/al/binario/Chrome' \
  node tests/browser.mjs
```

La prueba carga un Excel ficticio, resuelve una comuna que falta, aprueba una ubicación, registra la flota, genera una matriz sintética, calcula el recorrido y descarga el Excel. Las capturas y los archivos generados se guardan por defecto en `/tmp/novara-ui-evidence`. Reinicie la API aislada entre ejecuciones para comenzar con una base vacía.
## Demo de un clic

Inicia el backend aislado desde la raíz del proyecto y abre el frontend en otra terminal.

```bash
NOVARA_PRESET_DEMO=1 NOVARA_BROWSER_TEST_TOKEN=novara-local-demo PYTHONPATH=backend \
  .venv/bin/uvicorn scripts.frontend_demo:app --host 127.0.0.1 --port 8001
```

```bash
cd frontend
VITE_NOVARA_DEMO=1 NOVARA_DEV_API_PORT=8001 npm run dev -- --port 5174
```

Abre [la demo local](http://localhost:5174/) en el equipo que ejecuta los servidores y pulsa **Probar con nómina incluida**. Entra sin escribir un token. La nómina genera entre 6 y 15 pasajeros ficticios en al menos cinco comunas. **Simular otra jornada** sortea un cliente, paradas, horarios y fecha, y vuelve a calcular. La flota de simulación tiene tres vans de 12 plazas, con hasta dos viajes por conductor. La base de datos vive en memoria.

El sorteo usa rangos de pasajeros y frecuencias agregadas de comunas y bloques de media hora de 12 planillas internas de desarrollo. Los días reservados se excluyeron antes de abrir los archivos. Las recogidas emplean direcciones de lugares públicos, con coordenadas de referencia aproximadas. [Oficinas de Pudahuel](https://www.mpudahuel.cl/municipio/oficinas-y-telefonos-municipales), [directorio público de SENDA](https://www.senda.gob.cl/quienes-somos/encuentranos/), [Bolsa Nacional de Empleo](https://dev.bne.cl/listado-omil).

Los tiempos y distancias de viaje provienen de una matriz de referencia para estos puntos públicos, guardada en `data/synthetic/santiago-road-demo.json`. El optimizador utiliza esa matriz sin consultar un servicio de rutas en cada simulación. Los tiempos de la matriz son estáticos y las conexiones dibujadas son ilustrativas. [OSRM / FOSSGIS](https://routing.openstreetmap.de/about.html) · [OpenStreetMap y licencia ODbL](https://www.openstreetmap.org/copyright).

El fondo de Santiago utiliza [OSM Bright de Stadia Maps](https://docs.stadiamaps.com/map-styles/osm-bright/) con datos de OpenStreetMap. Requiere internet y se activa en la demo local. Si falla el proveedor, la interfaz muestra un aviso y conserva las paradas y conexiones. Los tiempos son simulados y las líneas entre recogidas son ilustrativas. En Planificación, filtra por van o pulsa un pasajero para encontrar su parada. **Descargar Excel** incluye la secuencia, los pasajeros, las direcciones y los horarios del plan vigente. Si cambias la selección, genera otra matriz y ejecuta la planificación para poder descargar de nuevo.

La demo reutiliza Leaflet con React Leaflet para el mapa, OR-Tools para calcular, openpyxl para el Excel y Lucide para los íconos. [Leaflet BSD-2-Clause](https://github.com/Leaflet/Leaflet/blob/main/LICENSE), [React Leaflet Hippocratic-2.1](https://github.com/PaulLeCam/react-leaflet/blob/master/LICENSE.md), [OR-Tools Apache-2.0](https://github.com/google/or-tools), [openpyxl MIT/Expat](https://openpyxl.readthedocs.io/en/stable/), [Lucide ISC](https://github.com/lucide-icons/lucide#license).

En el entorno privado ([localhost:5173](http://localhost:5173/)), **Subir nómina** intenta detectar cliente y fecha desde el Excel original y calcular una vista previa. Para el modo automático configura una base de salida compartida, tres vans con conductores y un terminal identificado por cliente. Se requiere un proveedor vial local autorizado o una matriz compatible. El flujo reutiliza ubicaciones aprobadas para el mismo cliente, código y domicilio solo cuando las aprobaciones concuerdan. Las ubicaciones nuevas y las nóminas ambiguas quedan pendientes de revisión. Los cálculos automáticos cubren acercamientos.
