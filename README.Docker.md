### Running locally with MongoDB

Start the app and its MongoDB 7 service with:

```sh
docker compose -f docker-compose.dev.yml up --build
```

The app is available at `http://localhost:8000`. MongoDB data persists in the
named `mongo-data` volume. Stop the services with:

```sh
docker compose -f docker-compose.dev.yml down
```

Add `--volumes` only when you intentionally want to delete the local database.

The app reads `MONGO_URI` and `MONGO_DB_NAME` from its environment. For cloud
deployments, configure these as deployment environment variables and provide
the connection URI through the platform's secret/configuration store; do not
commit credentials.

### Building and publishing

Build the application image with `docker build -t myapp .`. If your cloud uses
a different CPU architecture, specify the target platform, for example:
`docker build --platform=linux/amd64 -t myapp .`.

Then push the image to your registry, e.g. `docker push myregistry.com/myapp`.
Consult Docker's [getting started](https://docs.docker.com/go/get-started-sharing/)
docs for more detail.
