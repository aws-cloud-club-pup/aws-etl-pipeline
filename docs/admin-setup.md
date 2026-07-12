# Admin Pre-Workshop Setup

**Do this BEFORE the workshop, using your admin account (`785990773284`).**
Participants have read-only IAM (see [`participant-policy.json`](participant-policy.json)),
so they **cannot create roles**. You pre-create the two Lambda execution roles here;
participants only *select* them from the dropdown when creating their Lambdas.

Buckets MUST be named `etl-workshop-<name>` — the shared roles below grant S3
access by the `etl-workshop-*` prefix, so any bucket outside that pattern is
denied.

```bash
REGION=ap-southeast-1
```

---

## The two roles participants will select

The participant policy already whitelists these exact names for `iam:PassRole`:

- `etl-scraper-role`
- `etl-transformer-role`

> ⚠️ **Names must match exactly.** If you rename them, update the
> `PassPreCreatedRolesToLambdaOnly` block in `participant-policy.json` too.

---

## Create both roles (CloudShell, in the workshop account)

```bash
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

# Both roles are BUCKET-AGNOSTIC: they match any bucket named etl-workshop-*,
# so every participant's bucket works with no per-bucket policy edits.
# (Participant buckets MUST follow the etl-workshop-<name> naming convention.)

# --- scraper role: writes raw CSVs to S3 ---
aws iam create-role --role-name etl-scraper-role --assume-role-policy-document "$TRUST"
aws iam attach-role-policy --role-name etl-scraper-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name etl-scraper-role --policy-name scraper-s3-write \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::etl-workshop-*/raw/*"}]}'

# --- transformer role: S3 read raw / write processed + Redshift Data API + temp creds ---
aws iam create-role --role-name etl-transformer-role --assume-role-policy-document "$TRUST"
aws iam attach-role-policy --role-name etl-transformer-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name etl-transformer-role --policy-name transformer-access \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::etl-workshop-*/raw/*"},{"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::etl-workshop-*/processed/*"},{"Effect":"Allow","Action":["redshift-data:ExecuteStatement","redshift-data:DescribeStatement","redshift-data:GetStatementResult"],"Resource":"*"},{"Effect":"Allow","Action":"redshift:GetClusterCredentials","Resource":"*"}]}'
```

Verify:

```bash
aws iam get-role --role-name etl-scraper-role --query 'Role.Arn'
aws iam get-role --role-name etl-transformer-role --query 'Role.Arn'
```

---

## Complete role permissions reference

All three roles are **bucket-agnostic** — every S3 statement is scoped to the
`etl-workshop-*` name prefix, so any participant bucket following the convention
works with no per-bucket edits. Paste these JSON documents directly when creating
inline policies in the IAM console (**Add permissions → Create inline policy →
JSON**).

### `etl-scraper-role` — Lambda execution role (EXTRACT)

- **Managed:** `AWSLambdaBasicExecutionRole` (CloudWatch Logs — keep it)
- **Inline `scraper-s3-write`:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "WriteRaw", "Effect": "Allow", "Action": "s3:PutObject", "Resource": "arn:aws:s3:::etl-workshop-*/raw/*" }
  ]
}
```

### `etl-transformer-role` — Lambda execution role (TRANSFORM + LOAD)

Reads `raw/`, writes `processed/`, and fires the COPY via the Redshift Data API.
It does **not** need `iam:PassRole` for the COPY role — Redshift assumes that role
itself; the Lambda only names the ARN in SQL.

- **Managed:** `AWSLambdaBasicExecutionRole` (keep it)
- **Inline `transformer-access`:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "ReadRaw",        "Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::etl-workshop-*/raw/*" },
    { "Sid": "WriteProcessed", "Effect": "Allow", "Action": "s3:PutObject", "Resource": "arn:aws:s3:::etl-workshop-*/processed/*" },
    { "Sid": "RedshiftDataApi", "Effect": "Allow",
      "Action": ["redshift-data:ExecuteStatement", "redshift-data:DescribeStatement", "redshift-data:GetStatementResult"],
      "Resource": "*" },
    { "Sid": "RedshiftTempCreds", "Effect": "Allow", "Action": "redshift:GetClusterCredentials", "Resource": "*" }
  ]
}
```

### `etl-redshift-copy-role` — Redshift COPY role (assumed by the cluster, NOT a Lambda)

- **Trust policy:** principal `redshift.amazonaws.com`
- **Inline `redshift-copy-s3-read`:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "ListWorkshopBuckets", "Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::etl-workshop-*" },
    { "Sid": "GetWorkshopObjects",  "Effect": "Allow", "Action": "s3:GetObject",  "Resource": "arn:aws:s3:::etl-workshop-*/*" }
  ]
}
```

> ⚠️ `s3:ListBucket` must target the **bucket** ARN (no `/*`); `s3:GetObject`
> must target the **objects** (`/*`). Swapping these is the #1 cause of the COPY
> `s3:ListBucket ... not authorized` error.
>
> If a bucket uses SSE-KMS, also grant `kms:Decrypt` on the key ARN to this role.

---

## What participants do (instead of creating a role)

On the Lambda **Create function** page:

1. Expand **Change default execution role**.
2. Choose **Use an existing role**.
3. Select **`etl-scraper-role`** or **`etl-transformer-role`**.

---

## Clean up stray roles participants already created

If participants made their own roles before the guardrail was applied (e.g.
`etl-transformer-jeff-role-*`), remove them as admin. Inline policies must be
deleted first, then the role:

```bash
ROLE=etl-transformer-jeff-role-2p0886yz   # replace with the actual name

# delete inline policies
for p in $(aws iam list-role-policies --role-name "$ROLE" --query 'PolicyNames[]' --output text); do
  aws iam delete-role-policy --role-name "$ROLE" --policy-name "$p"
done
# detach managed policies
for a in $(aws iam list-attached-role-policies --role-name "$ROLE" --query 'AttachedPolicies[].PolicyArn' --output text); do
  aws iam detach-role-policy --role-name "$ROLE" --policy-arn "$a"
done
# delete the role
aws iam delete-role --role-name "$ROLE"
```

---

## Shared, bucket-agnostic COPY role

Redshift `COPY` runs **as the role named in `IAM_ROLE`**, a different principal
than the Lambda. Rather than every participant's cluster minting its own
`AmazonRedshift-CommandsAccessRole-…`, create **one shared role** whose S3
permissions match **any** workshop bucket by name prefix. Participants then all
point `REDSHIFT_COPY_ROLE_ARN` at this same ARN.

> 📛 **Bucket naming convention (required).** The role can only read buckets
> named `etl-workshop-*`. Every participant bucket must follow this pattern
> (e.g. `etl-workshop-jpc`) and their Lambda `BUCKET` env var must match.

```bash
CLUSTER=etl-workshop
REGION=ap-southeast-1

# Redshift trusts this role
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"redshift.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam create-role --role-name etl-redshift-copy-role \
  --assume-role-policy-document "$TRUST"

# Bucket-agnostic S3 read: any bucket named etl-workshop-*
# ListBucket must be on the BUCKET arn (no /*); GetObject on the OBJECTS (/*).
aws iam put-role-policy --role-name etl-redshift-copy-role \
  --policy-name redshift-copy-s3-read \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Sid":"ListWorkshopBuckets","Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::etl-workshop-*"},{"Sid":"GetWorkshopObjects","Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::etl-workshop-*/*"}]}'

# Attach to the shared cluster
ARN=$(aws iam get-role --role-name etl-redshift-copy-role --query 'Role.Arn' --output text)
aws redshift modify-cluster-iam-roles \
  --cluster-identifier "$CLUSTER" --add-iam-roles "$ARN" --region "$REGION"
echo "$ARN"
```

Every participant sets the **same** Lambda env var:

```
REDSHIFT_COPY_ROLE_ARN = arn:aws:iam::785990773284:role/etl-redshift-copy-role
```

> If the bucket uses SSE-KMS, also grant `kms:Decrypt` on the key to this role.

---

## Also pre-create (already done for this workshop)

- ✅ **Redshift cluster** `etl-workshop` (participants only query it).
- ✅ **COPY role** `etl-redshift-copy-role` (shared, bucket-agnostic) attached to the cluster.
- ⬜ **DB grants** — each participant's DB user needs SELECT on the tables:
  ```sql
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO <participant_db_user>;
  ```
- ⬜ **Cluster security group** allows Query Editor v2 connectivity.
