import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { restoreTheme } from "./hooks/useTheme";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

restoreTheme();

// `__MOCK_API__` is a build-time constant: in a production build this branch, the import
// and every fixture behind it are removed.
if (__MOCK_API__) {
  const { installMockApi } = await import("./mocks/install");
  installMockApi();
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
