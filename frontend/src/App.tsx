import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { api, ApiError, type Me, setCsrfToken } from "./api";
import { Layout } from "./components/Layout";
import { ErrorBox, Loading } from "./components/ui";
import { Login } from "./pages/Login";
import { EscalationPage, FaqPage, SettingsPage, TypesPage } from "./pages/admin";
import { Overview } from "./pages/Overview";
import { Servers } from "./pages/Servers";
import { Stats } from "./pages/Stats";
import { Ticket } from "./pages/Ticket";
import { Tickets } from "./pages/Tickets";

export function App() {
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/auth/me"),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
  });
  useEffect(() => setCsrfToken(me.data?.csrf_token ?? null), [me.data]);

  if (me.isPending) return <Loading />;
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) return <Login />;
    return <ErrorBox error={me.error} retry={() => me.refetch()} />;
  }
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout me={me.data} />}>
          <Route index element={<Servers />} />
          <Route path="servers/:guildId" element={<Overview />} />
          <Route path="servers/:guildId/tickets" element={<Tickets />} />
          <Route path="servers/:guildId/tickets/:ticketId" element={<Ticket />} />
          <Route path="servers/:guildId/stats" element={<Stats />} />
          <Route path="servers/:guildId/settings" element={<SettingsPage />} />
          <Route path="servers/:guildId/types" element={<TypesPage />} />
          <Route path="servers/:guildId/faq" element={<FaqPage />} />
          <Route path="servers/:guildId/escalation" element={<EscalationPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
