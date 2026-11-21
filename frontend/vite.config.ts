import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes inside the Python package: `python -m ticketbot web` serves it.
// In development (`npm run dev`) the API calls go to the web server on port 8080.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../ticketbot/web/static",
    emptyOutDir: true,
    // No inline scripts: the Content Security Policy only allows files from the site
    modulePreload: { polyfill: false },
  },
  server: {
    host: "127.0.0.1",
    proxy: { "/api": "http://127.0.0.1:8080" },
  },
});
