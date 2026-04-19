## ngoinhapinterest MVP

**MVP**: Docker Compose stack with `api`, `n8n`, `minio`, `redis` to generate product-style captions from images.

### 1. Setup

- Copy env file:

```bash
cp .env.example .env
```

- Adjust secrets/API keys in `.env` (do not commit real values).
- Adjust non-secret config in `config.yaml` if needed (bucket name, defaults, etc.).
- Choose one AI provider in `config.yaml`: `openai` or `gemini` (BLIP local removed).

### 2. Run stack

```bash
docker compose up -d
```

Services:
- API: `http://localhost:8080`
- n8n UI: `http://localhost:5678`
- MinIO S3: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

### 3. Import n8n workflow

1. Open n8n at `http://localhost:5678` (default user/pass from `.env`).
2. Import `infra/n8n/workflow-ngoinha-process.json`.
3. Activate the workflow.

### 4. Test flow with curl

Upload an image (include product `condition`, `size`, `price`):

```bash
curl -F "file=@/path/to/image.jpg" \
  -F "condition=90%" \
  -F "size=40x55cm" \
  -F "price=60000 VND" \
  http://localhost:8080/upload
```

Response:

```json
{"request_id":"uuid-here","status":"processing","missing_fields":[]}
```

Poll result:

```bash
curl http://localhost:8080/result/uuid-here
```

If processing, you get:

```json
{"status":"processing"}
```

If missing required input, you get:

```json
{
  "status":"needs_input",
  "missing_fields":["condition","size","price"],
  "message":"Please provide missing product info: condition, size, price"
}
```

Then submit missing fields:

```bash
curl -X POST http://localhost:8080/input/uuid-here \
  -H "Content-Type: application/json" \
  -d '{"condition":"90%","size":"40x55cm","price":"60000 VND"}'
```

When done, you get JSON like:

```json
{
  "product_name": "Cute cat-shaped carpet",
  "condition": "90%",
  "size": "40x55cm",
  "price": "60000 VND",
  "colors": ["white", "pink"],
  "caption": "Cute cat-shaped carpet\nCondition: 90%\nSize: 40x55cm\nPrice: 60,000 VND 🐳"
}
```

### 5. Zalo webhook stubs

- Incoming: `POST /webhooks/zalo/incoming`
- Outgoing: `POST /webhooks/zalo/outgoing`

Both endpoints echo payloads and can be wired later to real Zalo integrations.
