import react from "@vitejs/plugin-react";
import { type ProxyOptions, loadEnv } from "vite";
import { defineConfig } from "vitest/config";

const gateway = process.env.GATEWAY_URL ?? "http://localhost:8000";
const agent = process.env.AGENT_URL ?? "http://localhost:8001";
// The web address of a running stack. Its nginx already routes the three API paths, so a local
// build can be tried against it: STACK_URL=http://localhost:8080 npm run dev
const stack = process.env.STACK_URL;

const proxy: Record<string, string | ProxyOptions> = stack
  ? { "/api": stack, "/v1": stack, "/agent-api": stack }
  : {
      "/api": gateway,
      "/v1": gateway,
      "/agent-api": { target: agent, rewrite: (path) => path.replace(/^\/agent-api/, "") },
    };

export default defineConfig(({ mode }) => {
  const mockApi = mode === "mock" || loadEnv(mode, process.cwd(), "VITE_").VITE_MOCK_API === "1";
  return {
    plugins: [react()],
    // A build-time constant, so a production build drops the mock API and its fixtures entirely.
    define: { __MOCK_API__: JSON.stringify(mockApi) },
    server: { proxy: mockApi ? undefined : proxy },
    preview: { proxy: mockApi ? undefined : proxy },
    test: {
      include: ["src/**/*.test.ts"],
      environment: "node",
    },
  };
});
