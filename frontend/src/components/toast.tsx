import { createContext, type ReactNode, useCallback, useContext, useState } from "react";
import { ApiError, type Queued, waitForCommand } from "../api";
import { useI18n } from "../i18n";

type Kind = "info" | "success" | "error";
interface Toast { id: number; kind: Kind; text: string }

const ToastContext = createContext<(kind: Kind, text: string) => void>(() => {});

export function Toasts({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback((kind: Kind, text: string) => {
    const id = Date.now() + Math.random();
    setToasts((all) => [...all.slice(-3), { id, kind, text }]);
    setTimeout(() => setToasts((all) => all.filter((x) => x.id !== id)), kind === "error" ? 8000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((x) => (
          <div key={x.id} className={`toast toast-${x.kind}`}>{x.text}</div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/** Run an API call; for actions queued for the bot, wait until it carried them out. */
export function useRun(guildId: string) {
  const toast = useToast();
  const { t } = useI18n();
  return useCallback(async (call: () => Promise<unknown>, onDone?: () => void) => {
    try {
      const result = await call();
      if (result && typeof result === "object" && "command_id" in result) {
        toast("info", t("toast.queued"));
        await waitForCommand(guildId, result as Queued);
        toast("success", t("toast.done"));
      } else {
        toast("success", t("toast.saved"));
      }
      onDone?.();
      return true;
    } catch (error) {
      const message = error instanceof ApiError && error.status === 504
        ? t("toast.timeout")
        : t("toast.failed", { reason: error instanceof Error ? error.message : String(error) });
      toast("error", message);
      onDone?.();
      return false;
    }
  }, [guildId, t, toast]);
}
