# QOrder

Multi-tenant QR ordering system for restaurants/bars. Backend built with FastAPI
(async) + SQLAlchemy 2.0 + PostgreSQL, realtime over WebSocket + Redis Pub/Sub.

See `.kiro/specs/qorder-mvp/` for requirements, design, and the implementation plan.

## Local development

```bash
# 1. Start infrastructure (PostgreSQL + Redis)
docker compose up -d

# 2. Create a virtualenv and install dependencies
py -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# 3. Copy environment template
copy .env.example .env

# 4. Run the API
uvicorn qorder_api.main:app --reload
```

Health check: `GET http://localhost:8000/health` → `{"status": "ok"}`.
