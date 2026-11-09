import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, type TitleSummary } from "~/lib/api";

/**
 * Buscador con autosuggest (mismo contrato que el frontend anterior: `#search-input`
 * + `#search-results`). El formulario sigue funcionando sin JS (GET a `/?q=`).
 */
export function SearchBox({
  initialQuery = "",
  mode = "switch",
  hiddenParams = {},
}: {
  initialQuery?: string;
  /** `retro` busca en la colección de ROMs y navega a `/retro/game/:slug/`. */
  mode?: "switch" | "retro";
  /** Filtros que deben sobrevivir al envío del formulario (sistema, orden…). */
  hiddenParams?: Record<string, string>;
}) {
  const retro = mode === "retro";
  const inputId = retro ? "retro-search-input" : "search-input";
  const resultsId = retro ? "retro-search-results" : "search-results";
  const [value, setValue] = useState(initialQuery);
  const [items, setItems] = useState<TitleSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    setValue(initialQuery);
  }, [initialQuery]);

  useEffect(() => {
    const q = value.trim();
    if (q.length < 2) {
      setItems([]);
      setOpen(false);
      setError(null);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = retro
          ? await api.retroSearch(q, 8, controller.signal)
          : await api.search(q, 8, controller.signal);
        setItems(data.items);
        setOpen(true);
      } catch (e) {
        if (controller.signal.aborted) return;
        setItems([]);
        setOpen(false);
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 180);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [value, retro]);

  useEffect(() => {
    const onDocClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!boxRef.current?.contains(target) && !inputRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  const hrefFor = (slug: string) => (retro ? `/retro/game/${slug}/` : `/game/${slug}/`);
  const formPath = retro ? "/retro" : "/";

  return (
    <form
      className="search-wrap"
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        setOpen(false);
        const q = value.trim();
        const sp = new URLSearchParams(hiddenParams);
        if (q) sp.set("q", q);
        const qs = sp.toString();
        navigate(qs ? `${formPath}?${qs}` : formPath);
      }}
    >
      {Object.entries(hiddenParams).map(([key, value]) =>
        value ? <input key={key} type="hidden" name={key} value={value} /> : null,
      )}
      <label className="sr-only" htmlFor={inputId}>
        {retro ? "Buscar ROM en la colección retro" : "Buscar juego en la biblioteca"}
      </label>
      <span className="search-wrap__icon" aria-hidden="true">
        ⌕
      </span>
      <input
        ref={inputRef}
        id={inputId}
        name="q"
        type="text"
        autoComplete="off"
        spellCheck={false}
        className="search-input"
        placeholder={
          retro
            ? "Buscar ROM en MEGA… (After Burner, Golden Eye, Mame)"
            : "Buscar juego en MEGA… (Zelda, Arcade, Final Fantasy)"
        }
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onFocus={() => {
          if (items.length) setOpen(true);
        }}
        aria-expanded={open}
        aria-controls={resultsId}
        aria-autocomplete="list"
      />
      <div
        id={resultsId}
        ref={boxRef}
        className="search-results"
        role="listbox"
        hidden={!open || items.length === 0}
      >
        {items.map((game) => (
          <Link
            key={game.slug}
            to={hrefFor(game.slug)}
            role="option"
            onClick={() => setOpen(false)}
          >
            <span>{retro ? game.igdb_name?.trim() || game.name : game.name}</span>
            <span aria-hidden="true">{game.plataforma?.corto ?? game.letter}</span>
          </Link>
        ))}
      </div>
      {open && !loading && error ? (
        <p className="mono-label text-subtle" style={{ marginTop: "0.5rem" }}>
          {error}
        </p>
      ) : null}
    </form>
  );
}
