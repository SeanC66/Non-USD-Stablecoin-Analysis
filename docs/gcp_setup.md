# GCP setup for the daily pipeline

One-time setup so GitHub Actions can write to BigQuery without a stored key.
Run from a terminal signed in to the project owner account (`gcloud auth login`).

## 1. Variables

```bash
PROJECT_ID=crypto-504119
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SA_NAME=stablecoin-pipeline
SA="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
REPO_ID=1429199357   # numeric id of SeanC66/Non-USD-Stablecoin-Analysis; survives renames
```

## 2. Service account with the least access it needs

```bash
gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --project "$PROJECT_ID"

gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT_ID" \
  --display-name "Stablecoin monitor pipeline"

# Run queries (billed to the project)...
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$SA" --role roles/bigquery.jobUser

# ...and write only to this project's four datasets.
for ds in seeds staging marts; do
  bq mk --dataset --location=US "$PROJECT_ID:$ds" || true
done
for ds in raw seeds staging marts; do
  bq query --use_legacy_sql=false \
    "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`$PROJECT_ID.$ds\` TO 'serviceAccount:$SA'"
done
```

The pipeline also reads `bigquery-public-data`, which any authenticated
principal can query.

## 3. Workload Identity Federation (trust this repo only)

```bash
gcloud iam workload-identity-pools create github \
  --project "$PROJECT_ID" --location global --display-name "GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc stablecoin-repo \
  --project "$PROJECT_ID" --location global --workload-identity-pool github \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository_id=assertion.repository_id" \
  --attribute-condition "assertion.repository_id == '$REPO_ID'"

gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT_ID" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository_id/$REPO_ID"
```

## 4. GitHub repository secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `GCP_WIF_PROVIDER` | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/providers/stablecoin-repo` |
| `GCP_SERVICE_ACCOUNT` | `stablecoin-pipeline@crypto-504119.iam.gserviceaccount.com` |
| `BASE_RPC_URL` | Optional. A Base RPC URL from a provider's free tier (Alchemy, QuickNode, etc.). The public endpoint works but rate-limits `eth_getLogs`. |

## 5. Cost guardrails (console)

- **Budget alert:** Billing → Budgets & alerts → create a $1 budget on the
  billing account with email alerts at 50% and 100%.
- **Daily query cap:** IAM & Admin → Quotas → BigQuery API → "Query usage per
  day" → set to 50 GiB. The daily job scans about 1.3 GB, so this only trips
  on a mistake.

Code-level caps already apply: ingestion queries stop at 10 GB billed and dbt
queries at 5 GB (`transform/profiles.example.yml`).

## 6. First run

Trigger the workflow manually (Actions → Daily pipeline → Run workflow). The
first Base run backfills each contract from its deployment block. If the RPC
endpoint doesn't serve historical state, run it locally once with
`python -m ingest base --base-from-block <block>`.
