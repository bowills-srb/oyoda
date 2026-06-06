import "@fontsource/jetbrains-mono/500.css";
import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";

import { Router } from "./app/Router";
import { ErrorBoundary } from "./components/system/ErrorBoundary";
import { hydratePreBookingCacheFromStorage } from "./domain/prebooking/bootstrapCache";
import { queryClient } from "./lib/query/queryClient";
import { RealtimeBridge } from "./realtime/RealtimeBridge";
import { ThemeProvider } from "./theme/ThemeProvider";
import "./styles.css";

hydratePreBookingCacheFromStorage(queryClient);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <RealtimeBridge />
        <ThemeProvider>
          <Router />
        </ThemeProvider>
      </ErrorBoundary>
    </QueryClientProvider>
  </React.StrictMode>,
);
