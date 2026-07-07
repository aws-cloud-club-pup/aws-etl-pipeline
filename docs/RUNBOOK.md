# Workshop Runbook — Serverless ETL on AWS (Console)

Follow these steps **in order** in the AWS Console. Use a **single region throughout**
(e.g. `ap-southeast-1` Singapore, closest to PH) — S3, Redshift, and both Lambdas must
all be in the same region or the Redshift Data API COPY will fail. Names in
`<angle brackets>` are yours to choose — write them down as you go.

> 💡 **Cost warning.** S3 and Lambda are effectively free for this workshop, but a
> single-node `ra3.large` Redshift cluster bills **~$0.65/hour** the whole time it exists
> (not just while querying). **Delete it the same day** — see [Teardown](#7-teardown-do-this).

---

## Pre-flight checklist (before you start)

- [ ] You're signed into the AWS Console with an account you can create **IAM roles** in
      (admin or a role with `iam:CreateRole` + `iam:AttachRolePolicy`). Most workshop
      blockers are missing IAM permissions.
- [ ] You've picked ONE region and will stay in it. Confirm it in the top-right menu.
- [ ] The account has a **default VPC** in that region with at least one **public subnet**
      (a subnet whose route table has a `0.0.0.0/0` route to an Internet Gateway). New
      accounts have this by default. If someone deleted it, Redshift "publicly accessible"
      won't actually be reachable — see [Troubleshooting](#troubleshooting).
- [ ] You know your own public IP (search "what is my IP") for the Redshift security-group rule.

---

## 0. Values you'll fill in

| Name | Example | Yours |
|------|---------|-------|
| Region | `ap-southeast-1` | |
| S3 bucket | `etl-workshop-<yourname>` | |
| Redshift cluster id | `etl-workshop` | |
| Redshift database | `dev` | |
| Redshift master user | `admin` | |
| COPY IAM role ARN | `arn:aws:iam::...:role/RedshiftCopyRole` | |

---

## 1. Create the S3 bucket (the data lake)

1. S3 → **Create bucket**.
2. Name it `etl-workshop-<yourname>` (globally unique). **Same region** as everything else.
3. Keep defaults (block public access ON). Create.
4. Note the name — it's the `BUCKET` env var for both Lambdas.

---

## 2. Create the Redshift cluster

1. Amazon Redshift → **Provisioned clusters** → **Create cluster**.
2. Cluster identifier: `etl-workshop`. Node type: **`ra3.large`, 1 node**.
   > `dc2.large` has been retired from the new-cluster console. The current types are
   > **RG** and **RA3** — pick the cheapest single node, `ra3.large` (~$0.65/hr). Do **not**
   > pick the default `rg.4xlarge` ($3.6/hr) — it's massive overkill for this data.
3. Admin user name `admin` (default may show `awsuser` — either is fine, just match it in
   the env vars later). Set an admin password and **save it** — you'll need it for the
   Query Editor.
   > **Database name** isn't on the main page. It defaults to **`dev`**, which is what this
   > runbook uses — just leave it. To see or change it, turn off **"Use defaults"** under
   > **Additional configurations → Database configurations → Database name**.
4. **Additional configurations → Network and security → Publicly accessible: ON.**
   Leave the default VPC / subnet group selected.
5. Create. Wait until status is **Available** (~5 min).

### 2a. IAM role for COPY (S3 → Redshift)

**Easiest — do it right on the create-cluster page.** In the **Cluster permissions**
section (scroll down while creating the cluster):

1. Click **Create IAM role**.
2. When asked about S3 access, choose **Any S3 bucket** (or your `etl-workshop-<yourname>`
   bucket). It attaches `AmazonRedshiftAllCommandsFullAccess` — covers COPY + S3 read.
3. It creates the role **and sets it as the cluster default automatically** — no separate
   IAM step needed.
4. After the cluster is created, find this role's **ARN** (IAM → Roles, or the cluster's
   Properties → Associated IAM roles) → that's your `REDSHIFT_COPY_ROLE_ARN`.

> This built-in role uses a broad policy — fine for a throwaway workshop cluster. For a
> long-lived cluster you'd scope it to S3 read on just your bucket.

**Manual alternative** (if you skipped the button, or want a tighter policy):

1. IAM → **Roles → Create role** → trusted entity **AWS service → Redshift → Redshift - Customizable**.
2. Attach `AmazonS3ReadOnlyAccess` (or scope to your bucket). Name it `RedshiftCopyRole`.
   Create and **copy its ARN**.
3. Redshift → your cluster → **Actions → Manage IAM roles** → **Associate**
   `RedshiftCopyRole` → **Save changes**.

> ⏱️ Either way, association can take **1–2 minutes to propagate**. If a COPY fails
> immediately after with a role error, wait a minute and re-run.

### 2b. Allow your access (security group)

- Redshift → cluster → **Properties → Network and security → VPC security group** → open it →
  **Inbound rules → Edit** → add: type `Redshift` / port `5439` / source **My IP**.
  (Needed so the Query Editor and any local tools can reach the cluster.)

---

## 3. Create the tables

1. Redshift → **Query editor v2**.
   > First time only: it may ask to **configure the account** (creates a KMS key) — accept.
2. In the left tree, click your `etl-workshop` cluster → **Create connection** →
   authenticate with **Database user name and password** (`admin` + the password from 2.3),
   database `dev`.
3. Paste and run the contents of [`sql/ddl.sql`](../sql/ddl.sql).
   Creates `public.weather`, `public.air_quality`, `public.earthquakes`.

---

## 4. Scraper Lambda (EXTRACT)

1. Lambda → **Create function** → Author from scratch. Name `etl-scraper`,
   runtime **Python 3.12**, architecture `x86_64`.
2. In the code editor, **rename the default `lambda_function.py` file to `main.py`** (or
   create `main.py`) and paste [`etl/scraper/main.py`](../etl/scraper/main.py).
3. **Runtime settings → Edit → Handler:** `main.handler`. Save.
4. Click **Deploy** (Ctrl/Cmd+S saves; **Deploy** is what actually ships the code).
5. **Configuration → Environment variables:** `BUCKET = <your bucket>`.
6. **Configuration → General configuration → Edit → Timeout:** 30s
   (it hits three APIs across three cities).
7. **Configuration → Permissions → execution role** (opens IAM in a new tab) →
   **Add permissions → Create inline policy** allowing:
   - `s3:PutObject` on `arn:aws:s3:::<bucket>/raw/*`
   > The role already has `AWSLambdaBasicExecutionRole` (CloudWatch Logs) attached by
   > default when Lambda creates it — keep it, or you'll have no logs to debug with.
8. **Test** with an empty `{}` event. Confirm **three** files appear in S3, one under each
   of `raw/weather/`, `raw/air_quality/`, `raw/earthquakes/`.

### 4a. EventBridge schedule

1. Lambda → `etl-scraper` → **Add trigger → EventBridge (CloudWatch Events)**.
2. Create a new rule, schedule expression `rate(15 minutes)`. Add.

---

## 5. Transformer Lambda (TRANSFORM + LOAD)

1. Lambda → **Create function**. Name `etl-transformer`, runtime **Python 3.12**.
2. Create/rename to `main.py`, paste [`etl/transformer/main.py`](../etl/transformer/main.py).
   **Runtime settings → Handler:** `main.handler`. **Deploy**.
3. **General configuration → Timeout:** 60s.
4. **Environment variables:**
   - `BUCKET = <bucket>`
   - `REDSHIFT_CLUSTER_ID = etl-workshop`
   - `REDSHIFT_DB = dev`
   - `REDSHIFT_USER = admin`
   - `REDSHIFT_COPY_ROLE_ARN = <RedshiftCopyRole ARN>`
5. **Execution role** → keep `AWSLambdaBasicExecutionRole` (logs) and add an inline policy allowing:
   - `s3:GetObject` + `s3:PutObject` on `arn:aws:s3:::<bucket>/*`
   - `redshift-data:ExecuteStatement`, `redshift-data:DescribeStatement`,
     `redshift-data:GetStatementResult`
   - `redshift:GetClusterCredentials` on the cluster, plus its `dbuser` and `dbname`
     resources. Simplest for a workshop: allow these three actions on `Resource: "*"`.
6. **Add trigger → S3:** bucket = yours, event type **All object create events**,
   **prefix `raw/`**.
   > ⚠️ Create the trigger from **this Lambda's "Add trigger" page**, not from the S3
   > bucket's Properties → Event notifications. The Lambda path auto-adds the
   > resource-based permission that lets S3 invoke the function; the S3-side path does
   > not, and the trigger silently never fires.
   >
   > A single `raw/` trigger covers all three datasets — the transformer reads the key
   > and routes each file to the matching table. One scraper run fires it three times.
   > Acknowledge the recursive-invocation warning — safe here because output goes to
   > `processed/`, not `raw/`.

---

## 6. Run it end-to-end

1. Lambda → `etl-scraper` → **Test** (or wait for the schedule).
2. S3 → confirm new objects under all three `raw/<dataset>/` **and** `processed/<dataset>/` prefixes.
3. CloudWatch → **Log groups** → `/aws/lambda/etl-transformer` → latest stream → confirm
   three JSON result lines (one per dataset), each with `rows_loaded`.
4. Redshift Query editor:
   ```sql
   SELECT COUNT(*) FROM public.weather;
   SELECT COUNT(*) FROM public.air_quality;
   SELECT event_id, magnitude, place FROM public.earthquakes ORDER BY occurred_at DESC LIMIT 10;
   ```
   You should see rows in each. 🎉

---

## 7. Teardown (do this!)

1. **Delete the EventBridge schedule first** (Lambda `etl-scraper` → Configuration →
   Triggers → select the rule → Delete) so no new runs fire during teardown.
2. Redshift → cluster → **Actions → Delete** (skip final snapshot for the workshop).
   This is the only thing that meaningfully bills — do it first if you're in a hurry.
3. S3 → **Empty** the bucket, then **Delete** it.
4. Delete Lambda functions `etl-scraper`, `etl-transformer`.
5. IAM → delete `RedshiftCopyRole` and the two Lambda execution roles (named
   `etl-scraper-role-*` / `etl-transformer-role-*`) if created just for this.
6. (Optional, tidiness) CloudWatch → Log groups → delete `/aws/lambda/etl-scraper` and
   `/aws/lambda/etl-transformer`.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| No CloudWatch logs at all for a function | Execution role is missing `AWSLambdaBasicExecutionRole` — reattach it |
| Transformer runs but no rows in Redshift | COPY role not associated to cluster, wrong ARN, or ran before IAM propagated (wait 1–2 min, re-run) |
| `S3ServiceException Access Denied` in COPY | `RedshiftCopyRole` can't read the bucket, or bucket in a different region than the cluster |
| Transformer never fires on new files | Trigger created from S3 side (no invoke permission), or prefix isn't `raw/`, or wrong bucket |
| Scraper `AccessDenied` writing to S3 | Inline policy missing `s3:PutObject` on `.../raw/*` |
| Data API `AccessDenied` | Lambda role missing `redshift-data:*` or `redshift:GetClusterCredentials` |
| Data API `... could not connect` / region error | Lambda and Redshift cluster are in **different regions** — recreate in the same region |
| Query Editor can't connect / times out | Cluster not `Available` yet, security group missing your-IP:5439 rule, or wrong password |
| Cluster shows `Available` but nothing can reach it | Subnet isn't public (no IGW route). Move cluster to a public subnet group, or use a VPC with an Internet Gateway |
| Scraper timeout | An upstream API is slow — bump timeout to 60s, or reduce cities |
