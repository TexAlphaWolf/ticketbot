import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

/** Keep the dashboard of a server up to date: the server sends `tickets` when a ticket
 * changes (opened, answered, claimed, closed...) and the visible lists reload. */
export function useLiveUpdates(guildId: string | undefined) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!guildId) return;
    const source = new EventSource(`/api/v1/guilds/${guildId}/events`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);       // EventSource reconnects by itself
    source.addEventListener("tickets", () => {
      for (const key of ["tickets", "guild", "ticket", "stats", "transcript"]) {
        queryClient.invalidateQueries({ queryKey: [key, guildId] });
      }
    });
    source.addEventListener("logout", () => {
      source.close();
      queryClient.invalidateQueries({ queryKey: ["me"] });
    });
    return () => {
      source.close();
      setConnected(false);
    };
  }, [guildId, queryClient]);
  return connected;
}
