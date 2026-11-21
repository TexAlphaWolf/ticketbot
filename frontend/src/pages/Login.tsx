import { loginUrl } from "../api";
import { useI18n } from "../i18n";

const ERRORS = ["cancelled", "expired", "invalid", "scope", "discord"] as const;

export function Login() {
  const { t } = useI18n();
  const params = new URLSearchParams(window.location.search);
  const error = params.get("login_error");
  const known = ERRORS.find((e) => e === error);
  params.delete("login_error");
  const next = window.location.pathname + (params.size ? `?${params}` : "");
  return (
    <div className="login">
      <div className="card login-card">
        <img src="/favicon.svg" alt="" width={56} height={56} />
        <h1>{t("login.title")}</h1>
        <p>{t("login.text")}</p>
        {error && (
          <p className="notice notice-error" role="alert">
            {known ? t(`login.error.${known}`) : t("error.title")}
          </p>
        )}
        <a className="button button-primary button-large" href={loginUrl(next)}>
          {t("login.button")}
        </a>
        <p className="muted small">{t("login.privacy")}</p>
      </div>
    </div>
  );
}
