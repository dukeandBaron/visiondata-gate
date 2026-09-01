import { defineConfig, loadEnv, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

function configSourcePath(relative: string): string {
  const pathname = decodeURIComponent(new URL(relative, import.meta.url).pathname);
  return /^\/[A-Za-z]:\//.test(pathname) ? pathname.slice(1) : pathname;
}

type ProxyRequest = {
  destroy(): void;
};

type ProxyIncomingRequest = {
  headers: Record<string, string | string[] | undefined>;
  method?: string;
};

type ProxyResponse = {
  end(body?: string): void;
  headersSent: boolean;
  writeHead(
    statusCode: number,
    headers: Record<string, string>,
  ): void;
};

export default defineConfig(({ mode }) => {
  const runtime = loadEnv(mode, ".", "");
  const apiTarget =
    runtime.VISIONDATA_WEB_API_TARGET?.trim() || "http://127.0.0.1:8787";
  const publicReplay =
    runtime.VITE_VISIONDATA_PUBLIC_REPLAY?.trim() === "true";
  const base = runtime.VISIONDATA_WEB_BASE_PATH?.trim() || "/";
  const unsafeBrowserMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);
  const apiProxy: ProxyOptions = {
    target: apiTarget,
    changeOrigin: false,
    configure(proxy) {
      const eventProxy = proxy as unknown as {
        on(
          event: "proxyReq",
          listener: (
            proxyRequest: ProxyRequest,
            request: ProxyIncomingRequest,
            response: ProxyResponse,
          ) => void,
        ): void;
      };
      eventProxy.on("proxyReq", (proxyRequest, request, response) => {
        const method = (request.method ?? "GET").toUpperCase();
        if (!unsafeBrowserMethods.has(method)) return;
        const rawOrigin = request.headers.origin;
        const origin = Array.isArray(rawOrigin) ? rawOrigin[0] ?? "" : rawOrigin ?? "";
        const rawFetchSite = request.headers["sec-fetch-site"];
        const fetchSite = (
          Array.isArray(rawFetchSite) ? rawFetchSite[0] ?? "" : rawFetchSite ?? ""
        ).toLowerCase();
        const host = request.headers.host;
        const expectedOrigin =
          typeof host === "string" && host ? `http://${host}` : "";
        const crossSite =
          fetchSite === "cross-site" ||
          (origin !== "" && (origin === "null" || origin !== expectedOrigin));
        if (!crossSite) return;

        if (!response.headersSent) {
          response.writeHead(403, {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
          });
          response.end(
            JSON.stringify({
              error: {
                code: "cross_site_request_rejected",
                message:
                  "Cross-site browser requests cannot use local proxy authority.",
              },
            }),
          );
        }
        proxyRequest.destroy();
      });
    },
  };

  return {
    base,
    plugins: [react()],
    resolve: {
      alias: publicReplay
        ? [
            {
              find: /^\.\/App$/,
              replacement: configSourcePath("./src/public/PublicApp.tsx"),
            },
            {
              find: /^\.\/ProductContext$/,
              replacement: configSourcePath(
                "./src/public/PublicProductContext.tsx",
              ),
            },
            {
              find: /^\.\.\/ProductContext$/,
              replacement: configSourcePath(
                "./src/public/PublicProductContext.tsx",
              ),
            },
            {
              find: /^\.\.\/data\/api$/,
              replacement: configSourcePath("./src/public/publicApi.ts"),
            },
          ]
        : [],
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/v1": apiProxy,
        "/api/reviewer": "http://127.0.0.1:8765",
      },
    },
    preview: {
      port: 4173,
      strictPort: true,
      proxy: {
        "/v1": apiProxy,
        "/api/reviewer": "http://127.0.0.1:8765",
      },
    },
    build: {
      sourcemap: mode !== "desktop" && !publicReplay,
      target: "es2022",
    },
  };
});
