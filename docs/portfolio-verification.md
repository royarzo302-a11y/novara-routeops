# Portfolio verification / Verificación del portfolio

Date / Fecha: 21 November / noviembre 2026. All inputs were synthetic. The table below records local results. Source publication is now verified; remote CI is reported by the live workflow badges in the README. Public cloud deployment remains pending.

Todos los datos utilizados fueron sintéticos. La tabla registra resultados locales. La publicación del código ya se verificó; los indicadores del README muestran CI remoto. El despliegue público en nube sigue pendiente.

| Check / Comprobación | Observed result / Resultado |
| --- | --- |
| Python tests, including optional Bedrock SDK contract | 155 passed; 4 dependency deprecation warnings |
| Frontend component/unit tests | 6 passed across 3 files |
| Ruff lint and format | Passed; 83 Python files already formatted |
| Hosted frontend build | TypeScript and Vite passed |
| Browser hosted flow | Login, fixed factors, two downloads/imports, corrections, planning, map, Excel export and route reload passed |
| Browser planning observation | 16 requests, 4 trips, 0 unassigned; 3851 ms from planning click to response |
| Browser network observation | No requests to another origin during the tested hosted scenario |
| Publication scan | No findings among reviewed Git candidates; private paths excluded |
| Bedrock live inference | Not executed; no model quality result or model charge claimed |

The browser rehearsal used the current Python application with compiled hosted-mode React, loopback port 18175, one Uvicorn worker, in-memory sessions and a generated temporary password. The server was stopped after the test. Screenshots show only the synthetic application and contain no password or AWS identifiers. This was a macOS application rehearsal, separate from the earlier Linux Docker rehearsal described in the case study.

El ensayo de navegador utilizó la aplicación Python actual y React compilado en modo alojado, puerto local 18175, un worker, sesiones en memoria y una clave temporal. El servidor se detuvo al terminar. Las capturas solo muestran la aplicación sintética. Este ensayo en macOS es independiente del ensayo Linux anterior descrito en el caso de estudio.

## Reproduction / Reproducción

```bash
uv sync --frozen --extra ai
uv run --frozen --extra ai ruff check .
uv run --frozen --extra ai ruff format --check .
uv run --frozen --extra ai pytest -q
npm --prefix frontend ci
npm --prefix frontend test
VITE_NOVARA_HOSTED_DEMO=1 npm --prefix frontend run build
uv run --frozen python scripts/evaluate_headers.py --split test
uv run --frozen python scripts/evaluate_headers.py --split dev
python3 scripts/check_publication.py
```

The browser scenario is `frontend/tests/hosted.mjs`. It requires a running synthetic hosted application, `NOVARA_TEST_UI`, a temporary `NOVARA_DEMO_PASSWORD` and `CHROME_BIN`. Optional `NOVARA_UX_EVIDENCE` selects the screenshot directory. See the [hosted runbook](deployment-render.md) for server setup. Do not run the scenario against an operational deployment with real data.

El escenario de navegador requiere la aplicación alojada sintética iniciada, su URL, una clave temporal y Chrome. `NOVARA_UX_EVIDENCE` indica dónde guardar las capturas. El [procedimiento alojado](deployment-render.md) describe el arranque.

## Evaluation interpretation / Interpretación

[Development baseline](../evals/headers/baseline-dev.json): 35/35 expected mappings found, 0 wrong mappings, exact match on 12/12 cases. [Test baseline](../evals/headers/baseline-test.json): 13/51 expected mappings found, 0 wrong mappings, exact match on 12/24 cases. Development cases contain known/noisy labels; test cases intentionally introduce unknown vocabulary, English, ambiguity and adversarial instructions. These distributions do not estimate real-world accuracy. Both reports make zero model calls.

Línea base de desarrollo: 35/35 correspondencias y 12/12 casos exactos. Prueba: 13/51 correspondencias y 12/24 casos exactos, sin correspondencias incorrectas. Es un conjunto diseñado para probar límites de vocabulario, no una estimación de precisión en producción. Ambos reportes se ejecutan sin modelo.
