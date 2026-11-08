# Run and deploy AdaptSense

## Local demo

Use Python 3.13 and Node.js 22. From the project root with the existing Python environment:

```powershell
npm ci --prefix frontend
npm run build --prefix frontend
.\.venv\Scripts\python -m scripts.seed_demo
$env:HF_HUB_OFFLINE='1'
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` and choose **Explore Victoria results**. Seeding installs seven allowlisted records from the verified runs, is safe to repeat, and rejects conflicting records without overwriting them. Browsing the seeded results works without the model cache. Live inference requires the pinned Chronos checkpoint. On a new machine, either provide its Hugging Face cache or leave `HF_HUB_OFFLINE` unset for the first inference.

## Single-instance container

```sh
docker build -t adaptsense .
docker volume create adaptsense-state
docker run -d --name adaptsense --restart unless-stopped \
  -p 127.0.0.1:8765:8765 -v adaptsense-state:/state adaptsense
```

The image builds and serves the frontend and API at the same origin. It runs one Uvicorn worker as a non-root user and seeds the demo at startup. The volume holds SQLite and the checkpoint cache. The CPU-only Torch wheel is pinned. Container startup and the saved demo require no model download. The first live forecast downloads the pinned public checkpoint if the cache is empty.

`GET /health/ready` checks SQLite access. `GET /health` also reports whether the model has loaded in the process. Restarting the server preserves saved records and interrupts any active adaptive experiment.

For remote access, keep the backend behind an authenticated HTTPS proxy or a private network. Apply request size and rate limits at ingress. This is a shared workspace with no user-level data isolation, and record IDs are not access controls. Keep a single replica and a persistent local volume. Back up SQLite with a consistent database snapshot before upgrading. Hosted investigation is disabled in the image. If needed in a trusted environment, set `ADAPTSENSE_ENABLE_INVESTIGATION=1` and supply the provider key as a runtime secret.
