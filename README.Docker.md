### Running locally with the Cosmos DB emulator

The app stores its data in Azure Cosmos DB (NoSQL API). Locally, the
[Cosmos DB emulator](https://learn.microsoft.com/azure/cosmos-db/emulator-linux)
stands in for it, so no Azure account or cost is involved.

Start the app and the emulator with:

```sh
docker compose -f docker-compose.dev.yml up --build
```

The first run downloads the emulator image (about 2.3 GB). Then:

- The app is at `http://localhost:8000`. Open it from here, not from VS Code
  Live Server, which serves the pages without the API.
- The emulator's Data Explorer is at `http://localhost:1234`, where you can
  browse the `when_to_meet` database and its `users` and `meetings` containers.

The emulator takes around 15 seconds to start. If a request fails with
"An unexpected error occurred" straight after startup, wait until
`docker compose -f docker-compose.dev.yml logs cosmos-emulator` shows
`PostgreSQL=OK, Gateway=OK, Explorer=OK` and try again. The app creates the
database and containers itself on first use.

Emulator data is kept in the named `cosmos-data` volume. Stop the services with:

```sh
docker compose -f docker-compose.dev.yml down
```

Add `--volumes` only when you intentionally want to delete the local database.
After changing the code, run the `up --build` command again to rebuild the app.

### Configuration

The app reads these environment variables:

| Variable | Purpose |
| --- | --- |
| `COSMOS_ENDPOINT` | Cosmos DB account URI |
| `COSMOS_KEY` | Cosmos DB account key |
| `COSMOS_DB_NAME` | Database name; created with its containers if missing |
| `COSMOS_VERIFY_SSL` | Optional, default `true`. `false` is only accepted for the local emulator |
| `SESSION_SECRET` | Signs the login cookie. Required: the app will not start without it |
| `SESSION_COOKIE_SECURE` | Optional. Set to `true` when served over HTTPS |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional. Sends telemetry to Application Insights; see `docs/monitoring.md` |

`docker-compose.dev.yml` sets them for the emulator. For Azure deployments,
set them on the Container App and store `COSMOS_KEY` and `SESSION_SECRET` as
secrets; do not commit real credentials.

### Building and publishing

Build the application image with `docker build -t myapp .`. If your cloud uses
a different CPU architecture, specify the target platform, for example:
`docker build --platform=linux/amd64 -t myapp .`.

Then push the image to your registry, e.g. `docker push myregistry.com/myapp`.
Consult Docker's [getting started](https://docs.docker.com/go/get-started-sharing/)
docs for more detail.
