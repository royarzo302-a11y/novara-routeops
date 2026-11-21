# Interpretación de encabezados con Amazon Bedrock

[English](ai-headers.md) · [Caso de estudio](portfolio.es.md)

## Pregunta y estado

¿Puede un modelo recuperar campos con etiquetas desconocidas manteniendo la precisión de los perfiles deterministas? El adaptador y el evaluador están implementados. **La inferencia real y sus resultados de calidad siguen pendientes.** No se atribuye ninguna mejora a Bedrock todavía.

El parser operativo sigue siendo determinista. El módulo de IA no tiene un endpoint público ni puede modificar ingestas, aceptar propuestas, aprobar ubicaciones o despachar vehículos. El antiguo protocolo `HeaderInterpreter` es un punto de extensión histórico; este experimento usa un contrato separado que solo admite encabezados.

## Contrato y fallos

La entrada admite entre 1 y 30 etiquetas, de hasta 120 caracteres cada una. No acepta filas ni archivos. La respuesta debe ser JSON con pares de índice de columna y campo de una lista de 11 campos permitidos. Se rechazan columnas/campos repetidos, índices inexistentes, tipos incorrectos y propiedades adicionales. Toda propuesta exige `requires_human_review=true`.

El prompt trata las etiquetas como datos no confiables. No se registran herramientas. Respuestas truncadas, filtradas, con herramientas, JSON inválido o esquema incorrecto fallan de forma explícita. Los errores del proveedor se registran mediante códigos fijos, sin texto de entrada ni diagnósticos privados. No hay una sustitución silenciosa por la línea base que pudiera contarse como éxito del modelo. Validar el esquema no demuestra corrección semántica ni resistencia universal a inyecciones.

## Datos y línea base

`evals/headers/cases.json` contiene 36 casos sintéticos escritos manualmente, sin filas de pasajeros ni extractos privados. Versión: `headers-synthetic-v1`.

| Partición | Grupos | Casos |
| --- | --- | --- |
| Desarrollo | Vocabulario conocido y ruido | 12 |
| Prueba | Expresiones nuevas, inglés, ambigüedad e instrucciones maliciosas | 24 |

Es una prueba pública diseñada para exigir vocabulario desconocido. No representa la frecuencia operativa ni constituye una evaluación ciega. Si se ajusta el prompt usando sus resultados, hace falta otro conjunto independiente para medir generalización.

La línea base reúne el vocabulario actual de los perfiles v2 y se abstiene ante campos duplicados. Mide correspondencias de columnas, no el reconocimiento completo de libros Excel. Resultado de la ejecución registrada:

| Métrica | Línea base sin IA |
| --- | --- |
| Correspondencias correctas / emitidas / esperadas | 13 / 13 / 51 |
| Precisión | 100% sobre las 13 correspondencias emitidas |
| Recall | 25,49% |
| Casos con coincidencia exacta | 50% (12/24) |
| Incorrectas / omitidas / errores | 0 / 38 / 0 |
| Llamadas de red / tokens | 0 / 0 |

[Reporte reproducible](../evals/headers/baseline-test.json). La latencia es una medición local variable. Los grupos de inglés y expresiones nuevas tienen recall cero; ese es el problema de vocabulario que la IA deberá resolver. También hay que comprobar el vocabulario conocido en desarrollo para detectar regresiones.

## Reproducir sin AWS

```bash
uv sync --frozen
uv run --frozen python scripts/evaluate_headers.py --split test
uv run --frozen python scripts/evaluate_headers.py --split dev
```

Se calculan coincidencia exacta, precisión/recall, campos erróneos y omitidos, errores, resultados por grupo, latencia y tokens. La precisión es `null` si no se propone nada. Un fallo nunca cuenta como coincidencia exacta, incluso cuando el resultado esperado es vacío.

## Evaluación real opcional, todavía no ejecutada

Instala `uv sync --frozen --extra ai`. El adaptador usa boto3 y `bedrock-runtime.converse`, con `maxTokens=1024`, temperatura cero, timeout de conexión de 5 segundos, lectura de 30 segundos y reintentos adaptativos limitados a dos intentos totales. Las pruebas de contrato no sustituyen una llamada real.

La región está fijada a `us-east-2`. Solo se admiten identificadores directos de modelos de la lista de proveedores. Se rechazan perfiles geográficos/globales y ARN; no hay alternativa entre regiones. La autenticación usa un perfil local, sin credenciales estáticas en Git. Ver un modelo en el catálogo no prueba que pueda invocarse.

Después de verificar acceso al modelo regional y autorizar el costo:

```bash
uv run --frozen --extra ai python scripts/evaluate_headers.py \
  --provider bedrock --model-id IDENTIFICADOR_REGIONAL_DEL_MODELO \
  --profile novara-routeops --allow-paid --split dev --limit 1 \
  --output evals/runs/bedrock-smoke.json
```

Luego se compara sobre la misma partición de prueba, sin ajustar el prompt contra sus resultados. `--limit` limita casos, no dólares; los reintentos pueden añadir intentos. Esta preparación no crea permisos IAM, suscripciones de modelos ni servicios de pago. El acceso debe estar disponible previamente.

El costo queda `null`: se registran tokens observados, sin inventar tarifas. Se estima con precios específicos verificados y se contrasta con facturación AWS. Si el proyecto tiene habilitado el registro de invocaciones, AWS puede almacenar prompts. La herramienta solo carga el corpus sintético incluido; no debe sustituirse por datos personales.

## Decisión antes de integrar

Se debe demostrar mejora de recall en etiquetas nuevas/inglés, ausencia de regresiones en etiquetas conocidas, precisión aceptable y revisión de cada falso positivo. Las inyecciones y los fallos de proveedor/esquema se revisan por separado. Antes del experimento pagado hay que fijar umbrales numéricos según la tolerancia del operador. Este conjunto pequeño no certifica seguridad operativa. Faltan la pantalla de revisión y aceptación explícita con procedencia.

Referencias: [API Converse](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html), [SDK Python](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime/client/converse.html).
