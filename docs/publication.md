# GitHub publication / Publicación en GitHub

## Current preparation / Preparación actual

The reviewed source is published at [https://github.com/royarzo302-a11y/novara-routeops](https://github.com/royarzo302-a11y/novara-routeops), with public visibility and default branch `main`. The first published head was `439b66695797c0c9f327958064165989c628fd0e`; it matched the local source at publication. CI results are available through the README workflow badges. Cloud deployment and live-model evaluation remain separate pending milestones.

El código revisado está publicado en el enlace anterior, con visibilidad pública y rama `main`. Se verificó que el primer HEAD publicado coincidía con la copia local. Los indicadores del README enlazan a CI. El despliegue en nube y la evaluación real del modelo siguen pendientes.

## Release boundary / Límite público

Commit source code, lockfiles, synthetic examples, tests, evaluation protocol, public reports and infrastructure templates. Exclude `.env`, credentials, databases, real workbooks, local agent/editor configuration and private AWS support history. Preserve local operational documents under `docs/private/`; that directory is ignored.

Publicar código, lockfiles, ejemplos ficticios, pruebas, protocolo de evaluación, reportes públicos y plantillas. Excluir credenciales, bases de datos, archivos reales e historial interno de soporte. Conservar los documentos operativos locales en `docs/private/`.

Run `python3 scripts/check_publication.py` before staging and after staging. The script checks Git candidates, including tracked files that may have been force-added. It reports only filenames and rule labels, never matched values. It detects selected high-confidence credential/identifier patterns; it is not a complete personal-data or secret detector. Manually review `git diff --cached --stat`, `git diff --cached` and binary fixture provenance before pushing.

El control automático no reemplaza la revisión humana de datos personales, permisos para mostrar marcas ni contenido binario. Las nóminas públicas deben provenir de los generadores sintéticos.

## Suggested release sequence / Secuencia

1. The initial local snapshot contains the source, bilingual documentation, Bedrock experiment, labels and offline test baseline.
2. A separate documentation commit adds the observed verification results, development baseline and synthetic screenshots.
3. Add the GitHub remote, push the reviewed history and verify remote CI before adding success badges.
4. Add a live-model comparison only after an authorized Bedrock run. Keep unreviewed live reports under ignored `evals/runs/`.
5. Select a license before describing the code as open source. No license has been chosen yet.

Use `README.md` for English and `README.es.md` for Spanish. Link to both case-study and AI-evaluation language versions. Do not describe pending cloud deployment or unmeasured model improvements as completed work.
