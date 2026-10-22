# Monitoring

The production environment must collect and visualise CPU utilisation, RAM
usage, disk I/O, network traffic and HTTP request latency. Two Azure sources
cover these between them:

- **Azure Container Apps platform metrics**: collected automatically for every
  container app, with no code or setup.
- **Application Insights**: the app sends request timings, Cosmos DB call
  timings, errors, logs and process performance counters when the
  `APPLICATIONINSIGHTS_CONNECTION_STRING` environment variable is set
  (see `backend/app/telemetry.py`). Without it, nothing is sent, so local runs
  and tests are unaffected.

## What is measured where

| Requirement | Source | Metric |
| --- | --- | --- |
| CPU utilisation | Container App | **CPU Usage Percentage** (`CpuPercentage`), **CPU Usage** (`UsageNanoCores`) |
|  | Application Insights | **Process CPU**, **Processor time** |
| RAM usage | Container App | **Memory Percentage** (`MemoryPercentage`), **Memory Working Set Bytes** (`WorkingSetBytes`) |
|  | Application Insights | **Private bytes**, **Available memory** |
| Disk I/O | Application Insights | **Process IO rate**: bytes read and written per second by the app process |
| Network traffic | Container App | **Network In Bytes** (`RxBytes`), **Network Out Bytes** (`TxBytes`) |
| HTTP request latency | Application Insights | **Server response time**, plus percentiles from the `requests` table |
|  | Container App | **Average Response Time** (`ResponseTime`) |
| Also available | Application Insights | Request rate, failed requests, Cosmos DB call durations (dependencies), exceptions, Live Metrics |

Container Apps has no disk metric, so disk I/O comes only from the Application
Insights process counter. The app keeps its data in Cosmos DB rather than on
local disk, so expect this value to stay low; it rises mainly when static files
are first read.

`/api/health` is excluded from request telemetry so frequent health checks do
not skew the latency charts.

## Monitoring page

The app has its own monitoring page at `/monitoring.html`. A **Monitoring**
link appears in the nav for users with the **Admin** role. The server enforces
this: logged-out visitors are sent to the login page, other roles get a 403,
and the page's data endpoints (`/api/monitoring/live`, `/api/monitoring/azure`)
return 403 for anyone who is not an Admin.

It has two sections:

- **Live: this server.** Measured inside the app process, so it works
  everywhere: locally, in Docker and in Azure, with no setup. A background
  sampler records CPU, memory, disk I/O and network every 5 seconds and keeps
  the last hour; every request's duration is recorded too (health checks and
  the page's own polling excluded). It shows stat tiles, charts, and latency
  per route for the last 15 minutes. It covers only the replica that answered
  the request and resets when the app restarts.
- **Azure Monitor: all replicas.** History for 1, 6 or 24 hours, read from
  Azure Monitor: the Container App metrics and the Application Insights
  metrics listed above, plus p50/p95/p99 latency and the slowest routes.
  Hidden behind a "not connected" note until it is set up (below). Results
  are cached for 60 seconds to limit API calls.

Every chart has a **Show as table** view with the same numbers.

### Connecting the page to Azure Monitor

The page reads Azure Monitor using the container app's **managed identity**,
so no keys are stored.

1. **Give the container app an identity:**

   ```sh
   az containerapp identity assign --name <container-app> --resource-group <rg> --system-assigned
   ```

2. **Let that identity read monitoring data** in the resource group (covers
   both the Container App and Application Insights):

   ```sh
   az role assignment create --assignee-object-id "$(az containerapp show --name <container-app> --resource-group <rg> --query identity.principalId -o tsv)" --assignee-principal-type ServicePrincipal --role "Monitoring Reader" --scope "$(az group show --name <rg> --query id -o tsv)"
   ```

3. **Tell the app which resources to read:**

   ```sh
   az containerapp update --name <container-app> --resource-group <rg> --set-env-vars AZURE_MONITOR_REGION=<region> AZURE_MONITOR_CONTAINER_APP_ID="$(az containerapp show --name <container-app> --resource-group <rg> --query id -o tsv)" AZURE_MONITOR_APP_INSIGHTS_ID="$(az monitor app-insights component show --app wtm-prod-insights --resource-group <rg> --query id -o tsv)"
   ```

   `<region>` is the resources' region in lowercase with no spaces, for
   example `australiaeast`.

Role assignments can take a few minutes to apply. Until then the section
shows which items could not be loaded and why.

To use it while running the app locally, sign in with `az login` and set the
same three variables; the app then reads Azure Monitor with your own
account's access.

## One-time setup per environment

Do this for each environment you want to monitor (at minimum Production).
Use a separate Application Insights resource per environment so staging traffic
does not mix with production figures.

The commands use the Azure CLI. Replace the values in angle brackets. The
portal steps in brackets do the same thing.

1. **Add the Application Insights CLI extension** (first time only):

   ```sh
   az extension add --name application-insights
   ```

2. **Create a Log Analytics workspace** to store the telemetry
   (portal: *Log Analytics workspaces → Create*):

   ```sh
   az monitor log-analytics workspace create --resource-group <rg> --workspace-name wtm-prod-logs --location <region>
   ```

3. **Create the Application Insights resource** linked to that workspace
   (portal: *Application Insights → Create*, choose the workspace above):

   ```sh
   az monitor app-insights component create --app wtm-prod-insights --resource-group <rg> --location <region> --workspace "$(az monitor log-analytics workspace show --resource-group <rg> --workspace-name wtm-prod-logs --query id -o tsv)"
   ```

4. **Copy its connection string**
   (portal: the Application Insights resource's *Overview*):

   ```sh
   az monitor app-insights component show --app wtm-prod-insights --resource-group <rg> --query connectionString -o tsv
   ```

5. **Give it to the container app** as a secret, then expose the secret as the
   environment variable the app reads (portal: *Container App → Settings →
   Secrets*, then *Containers → Environment variables*, source *Reference a
   secret*):

   ```sh
   az containerapp secret set --name <container-app> --resource-group <rg> --secrets appinsights-connection="<connection string>"
   ```

   ```sh
   az containerapp update --name <container-app> --resource-group <rg> --set-env-vars APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-connection
   ```

   This creates a new revision. The setting persists across later deploys,
   because the pipeline only changes the image.

6. **Check data is arriving.** Use the app for a minute (log in, open
   meetings, find times), then open the Application Insights resource:
   *Live metrics* shows requests as they happen; *Performance* shows response
   times within a few minutes.

## Building the dashboard

Create one Azure dashboard (portal: *Dashboard → Create → Custom*) and pin
these charts to it. Each chart is made in *Metrics* on the named resource,
then **Pin to dashboard**.

From the **Container App** (*Monitoring → Metrics*, namespace *Container App
standard metrics*):

1. **CPU Usage Percentage**, aggregation *Max*.
2. **Memory Percentage**, aggregation *Max*.
3. **Network In Bytes** and **Network Out Bytes** on one chart, aggregation *Sum*.
4. **Requests**, aggregation *Sum*, split by *Status Code Category*.

From **Application Insights** (*Monitoring → Metrics*):

5. **Server response time**, aggregation *Avg* (add a second line with *Max*).
6. **Process IO rate**, aggregation *Avg* (namespace *Application Insights
   standard metrics*, under *Performance counters*).
7. **Dependency duration**, aggregation *Avg*: time spent in Cosmos DB calls.

For latency percentiles, open Application Insights *Logs*, run this query,
and pin the chart:

```kusto
requests
| where timestamp > ago(24h)
| summarize
    p50 = percentile(duration, 50),
    p95 = percentile(duration, 95),
    p99 = percentile(duration, 99)
    by bin(timestamp, 5m)
| render timechart
```

The slowest endpoints:

```kusto
requests
| where timestamp > ago(24h)
| summarize requests = sum(itemCount), avg_ms = avg(duration), p95_ms = percentile(duration, 95) by name
| order by p95_ms desc
```

## Alerts

The success metrics call for an alert when usage passes 90%. Create an action
group that emails the team, then metric alerts on the Container App:

```sh
az monitor action-group create --name wtm-team --resource-group <rg> --short-name wtm --action email team <team email>
```

```sh
az monitor metrics alert create --name wtm-prod-cpu-90 --resource-group <rg> --scopes "$(az containerapp show --name <container-app> --resource-group <rg> --query id -o tsv)" --condition "max CpuPercentage > 90" --window-size 5m --evaluation-frequency 1m --action wtm-team --description "CPU above 90%"
```

```sh
az monitor metrics alert create --name wtm-prod-memory-90 --resource-group <rg> --scopes "$(az containerapp show --name <container-app> --resource-group <rg> --query id -o tsv)" --condition "max MemoryPercentage > 90" --window-size 5m --evaluation-frequency 1m --action wtm-team --description "Memory above 90%"
```

## Cost

Container App metrics are free. Application Insights charges by the volume of
data ingested, so:

- The app keeps at most **5 traced requests per second** by default (the
  Azure Monitor distro's rate-limited sampler). Application Insights scales
  counts up to compensate, so totals and averages stay representative. To
  record every request during a demo, set `OTEL_TRACES_SAMPLER=always_on` on
  the container app, and remove it afterwards.
- Set a daily cap on the Log Analytics workspace (portal: *Log Analytics
  workspace → Usage and estimated costs → Daily cap*) so a traffic spike
  cannot run up a bill.

## Configuration reference

| Variable | Effect |
| --- | --- |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Enables telemetry and says which Application Insights resource receives it. Unset: telemetry off. |
| `OTEL_SERVICE_NAME` | Name shown in Application Insights (*cloud role name*). Defaults to `when-to-meet`. |
| `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG` | Change request sampling, e.g. `always_on`. |
| `AZURE_MONITOR_REGION` | Region of the monitored resources, for the monitoring page's metrics queries. |
| `AZURE_MONITOR_CONTAINER_APP_ID` | Resource ID of the Container App whose metrics the monitoring page shows. |
| `AZURE_MONITOR_APP_INSIGHTS_ID` | Resource ID of the Application Insights resource the monitoring page shows. |
