import { requestJson } from "../../api/client";

import type { SessionPayload } from "./types";

export function fetchSession() {
  return requestJson<SessionPayload>("/app/auth/session");
}
