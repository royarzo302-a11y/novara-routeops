# Data provenance for the public repository

This public note describes methodology only. Operational inventories, source filenames and private audit reports remain in a local ignored directory.

- Private source workbooks are never committed, copied into images or used as public test fixtures.
- Ingestion tests construct fictitious workbooks in memory and test structural patterns and failure modes.
- The public route demonstration uses fictitious passengers and public reference locations. See the demo dataset documentation for matrix provenance and upstream attribution.
- The AI header corpus is hand-authored from labels only. It contains no passenger rows, addresses, telephone values or private workbook extracts.
- Private validation outcomes are not public reproducibility evidence. Public claims should be verified with the committed synthetic data and commands.

## Español

Esta nota pública describe el método. Los inventarios operativos, nombres de archivos fuente y reportes privados quedan en un directorio local excluido de Git. Las pruebas generan Excel ficticios; la evaluación de IA contiene solo etiquetas redactadas manualmente. Los resultados privados no sustituyen la evidencia reproducible con los datos publicados.
