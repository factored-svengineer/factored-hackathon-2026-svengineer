# Frontend

Minimal React + Vite interface for verifying the API connection.

## Local development

1. Install dependencies with `npm install` inside `frontend/`.
2. Start the backend using the instructions in [`backend/README.md`](../backend/README.md).
3. Run `npm run dev` and open `http://localhost:5173`.

Vite proxies `/api/*` to `http://localhost:8000` and removes the `/api` prefix before forwarding the request. Set `VITE_API_PROXY_TARGET` to change the target.

## Docker Compose

From the repository root, run `docker compose --profile full up --build`. Compose points the proxy at `backend:8000` and waits for the backend `/health` check to pass before starting Vite.

The interface checks `GET /health` and displays the connection state, service name, and HTTP response. Use **Retry** to check the endpoint again.
