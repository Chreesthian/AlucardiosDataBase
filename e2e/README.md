# Auditoría end-to-end (AlucardiosDataBase)

Suite de **auditoría externa e interna** con Playwright contra el despliegue.

- `tests/audit-api.spec.ts` → API REST y coherencia de la ingesta (interno).
- `tests/audit-ui.spec.ts` → navegador real (Chromium): SSR, autosuggest,
  chips de letra, orden, paginación y detalle (externo).

## Requisitos

- Stack desplegado: `docker compose up -d` (web y API publicadas).
- Navegador: `pnpm exec playwright install chromium`.

## Uso

```bash
# puertos por defecto del despliegue local
BASE_URL=http://127.0.0.1:7440 API_BASE=http://127.0.0.1:7441 pnpm test
# o desde la raíz:
make e2e
```

Configurables vía entorno: `BASE_URL`, `API_BASE` (ver `playwright.config.ts`).
Evidencias: screenshots en `results/`, informe HTML en `playwright-report/`,
traces de fallos en `test-results/`.
