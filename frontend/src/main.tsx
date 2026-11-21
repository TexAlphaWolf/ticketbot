import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { ApiError } from "./api";
import { App } from "./App";
import { Toasts } from "./components/toast";
import { detectLang, I18n, type Lang, translator } from "./i18n";
import "./styles.css";

// A 401 anywhere means the login ended: ask /auth/me again, which shows the login page
function loggedOut(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    queryClient.invalidateQueries({ queryKey: ["me"] });
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.queryKey[0] !== "me") loggedOut(error);
    },
  }),
  mutationCache: new MutationCache({ onError: loggedOut }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

function Root() {
  const [lang, setLangState] = useState<Lang>(detectLang);
  const value = useMemo(() => ({
    lang,
    t: translator(lang),
    setLang: (next: Lang) => {
      try {
        localStorage.setItem("lang", next);
      } catch {
        // storage blocked: the choice lasts until the page is closed
      }
      document.documentElement.lang = next;
      setLangState(next);
    },
  }), [lang]);
  document.documentElement.lang = lang;
  return (
    <I18n.Provider value={value}>
      <QueryClientProvider client={queryClient}>
        <Toasts>
          <App />
        </Toasts>
      </QueryClientProvider>
    </I18n.Provider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
