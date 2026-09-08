# Investigación — Versiones 1:1 (Nintendo vs carpetas MEGA)

Objetivo: saber para cada juego de la biblioteca si la versión que ofrece su
carpeta (base `B-ASE` + parches `U-PD/UP-D x.y.z`) coincide con la **versión
actual ofrecida por Nintendo**.

## 1) Qué identifica la versión en la carpeta (local)
- Base: carpeta `B-ASE` (base del juego, versión 1.0.0 implícita).
- Parches: carpetas `U-PD 1.0.1`, `U-PD 1.2.5`, `UP-D 3.6.0`, … → la versión
  "ofrecida" por la carpeta es la **máxima** de sus parches.
- Title-ID de Switch (cuando existe) en nombres de `.nsp`/`.nsz` reales:
  `Arcade Archives CUE BRICK [010066001E178000][v0][US]…`.
- Auditoría local (datos reales de la BD): **5.374 juegos**, **3.171 con
  parches** (58 %) y el resto solo base; solo 2 títulos base tienen su
  `.nsp` original con title-id incrustado en el nombre. → **los .rar no llevan
  id**: hace falta resolver por NOMBRE.

## 2) Fuentes oficiales evaluadas (pruebas reales)
| Fuente | Resultado |
|---|---|
| Nintendo EU SOLR `searching.nintendo-europe.com/select` | ✅ resuelve nombre→ficha: `application_id_s` (**title-id Switch**), `nsuid`, `product_code_txt`, precios, fechas… **No** expone la versión actual |
| `api.ec.nintendo.com/v1/price` | ❌ solo precios/disponibilidad; sin versión |
| Nintendo CDN de actualizaciones | fuente real de la versión actual, pero **privada** (requiere consola/cuenta) |
| BD comunitaria título-id→versión (tinfoil/nx-versions) | ⚠️ práctica común para este fin, no hay endpoint público estable confirmado; se integra como JSON `title_id → "x.y.z"` |

## 3) Pipeline 1:1 propuesto
1. `carpeta (nombre)` → resolver Nintendo EU SOLR → `title_id` (`application_id_s`).
2. `title_id` → "versión actual" desde BD comunitaria/oficial (JSON externo o
   endpoint futuro).
3. Comparar con la **máx versión U-PD local**.
4. Estado por juego: `al_dia` / `desactualizado` / `desconocido`.

Implementación: `app/versiones.py`
```bash
uv run python -m app.versiones                    # auditoría local
uv run python -m app.versiones --resolver 20      # + resolver 20 a title-id Nintendo
uv run python -m app.versiones --oficiales data/oficial.json --out data/version_audit.json
```
Futuro: guardar `nintendo_title_id` y `nintendo_latest` por título en la BD
(campos nuevos) y refrescarlo periódicamente (mismo patrón que el enriquecido
IGDB y el sync incremental).
