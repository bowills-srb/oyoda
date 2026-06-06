import os
from locust import HttpUser, between, task


OPERATOR_ID = os.getenv("OPERATOR_ID", "beach_habitats")


class ConciergeKnowledgeUser(HttpUser):
    wait_time = between(0.1, 0.4)

    @task(4)
    def knowledge_retrieve(self):
        payload = {
            "query": "bike lock code",
            "operator_id": OPERATOR_ID,
            "top_k": 3,
        }
        with self.client.post(
            "/api/v1/knowledge/retrieve",
            json=payload,
            catch_response=True,
            name="knowledge.retrieve",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"status={resp.status_code}")
                return
            data = resp.json()
            if "documents_retrieved" not in data:
                resp.failure("missing documents_retrieved")
                return
            resp.success()

    @task(1)
    def health(self):
        with self.client.get("/health", catch_response=True, name="health") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"status={resp.status_code}")
