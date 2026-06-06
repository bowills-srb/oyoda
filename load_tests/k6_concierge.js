import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const OPERATOR_ID = __ENV.OPERATOR_ID || "beach_habitats";

export const options = {
  scenarios: {
    concierge_retrieve_burst: {
      executor: "ramping-arrival-rate",
      startRate: 10,
      timeUnit: "1s",
      preAllocatedVUs: 50,
      maxVUs: 500,
      stages: [
        { target: 50, duration: "2m" },
        { target: 120, duration: "5m" },
        { target: 250, duration: "5m" },
        { target: 0, duration: "2m" },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1200", "p(99)<2500"],
    checks: ["rate>0.99"],
  },
};

export default function () {
  const payload = JSON.stringify({
    query: "bike lock code",
    operator_id: OPERATOR_ID,
    top_k: 3,
  });

  const headers = { "Content-Type": "application/json" };
  const res = http.post(`${BASE_URL}/api/v1/knowledge/retrieve`, payload, { headers });

  check(res, {
    "status is 200": (r) => r.status === 200,
    "has retrieval body": (r) => !!r.body,
  });

  sleep(0.2);
}
