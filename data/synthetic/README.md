# Nóminas ficticias

No contienen personas ni domicilios reales. Las coordenadas ilustrativas tampoco validan las calles inventadas. Fecha fija: 2026-11-20, independiente del reloj de ejecución.

| Caso | Archivo | Objetivo |
|---|---|---|
| A | case_a_structured.xlsx | 14 pasajeros, columnas consistentes, cuatro turnos |
| B | case_b_messy.xlsx | Igual escenario, título previo, columnas reordenadas, alias y horas mixtas |
| C | case_c_errors.xlsx | Dirección incompleta, hora ambigua, nombre/coordenadas faltantes, duplicado |
| D | case_d_feasible.xlsx | Seis pasajeros a las 05:00, solución verificable |
| E | case_e_infeasible.xlsx | Nómina D con máximo a bordo de un minuto: inviable |

Los parámetros y recursos necesarios están en `scenarios.json`. E no es inviable con cualquier configuración: debe usarse `max_onboard_minutes=1` o la configuración del manifiesto. El generador está en `scripts/generate_synthetic.py`. API y pruebas utilizan matrices simuladas, no tráfico real.
