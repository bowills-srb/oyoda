# Concierge Load Tests

## k6

Run a ramping arrival-rate load profile against knowledge retrieval:

```bash
k6 run load_tests/k6_concierge.js \
  -e BASE_URL=http://localhost:8000 \
  -e OPERATOR_ID=beach_habitats
```

## Locust

Run user-based load with weighted concierge traffic:

```bash
locust -f load_tests/locustfile.py --host=http://localhost:8000
```

Recommended first pass:

```bash
locust -f load_tests/locustfile.py \
  --host=http://localhost:8000 \
  --users 200 \
  --spawn-rate 20 \
  --run-time 10m \
  --headless
```
