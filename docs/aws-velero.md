# Velero backups to AWS S3 — one-time setup

**Last updated: 2026-11-19** · Run on your desktop with the AWS CLI logged in as your **admin IAM user** (not root).
Never paste access keys into chat, Git, or a file — `setup-velero.sh` asks for them and seals them.

## 1. Bucket (private, versioned, auto-cleaned)
```bash
B=cloudkanata-homelab-backups   # must be globally unique; change if taken
R=ca-central-1
aws s3api create-bucket --bucket $B --region $R --create-bucket-configuration LocationConstraint=$R
aws s3api put-public-access-block --bucket $B --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket $B --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket $B --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket $B --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-old","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":7},"Expiration":{"Days":40}}]}'
```

## 2. IAM user that can touch only this bucket
```bash
cat > /tmp/velero-policy.json <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetObject","s3:DeleteObject","s3:PutObject","s3:AbortMultipartUpload","s3:ListMultipartUploadParts"],"Resource":"arn:aws:s3:::$B/*"},
 {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::$B"}]}
JSON
aws iam create-user --user-name velero-homelab
aws iam put-user-policy --user-name velero-homelab --policy-name velero-s3-$B --policy-document file:///tmp/velero-policy.json
aws iam create-access-key --user-name velero-homelab --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text
rm /tmp/velero-policy.json
```
Keep that terminal open — the next step asks for those two values.

## 3. Turn Velero on
```bash
bash scripts/setup-velero.sh $B $R
git add -A && git commit -m "velero: on" && git push
```

## 4. Velero CLI + first test
```bash
V=v1.18.2; curl -sSL https://github.com/vmware-tanzu/velero/releases/download/$V/velero-$V-linux-amd64.tar.gz \
 | tar xz && sudo install -m 755 velero-$V-linux-amd64/velero /usr/local/bin/ && rm -rf velero-$V-linux-amd64
velero backup-location get                       # PHASE should be Available
velero backup create first-test --include-namespaces dev --wait
velero backup describe first-test --details
```

## Cost
A few GB of backups in S3 Standard ≈ well under $1/month. Set an **AWS Budget alert** first (Billing → Budgets → $5).

## Restore (after a rebuild)
1. Restore the Sealed Secrets key **before** bootstrapping Argo CD:
   `kubectl apply -f sealed-secrets-key.yaml` (from your password manager), then run `bootstrap-argocd.sh`.
2. Once Velero is Synced: `velero restore create --from-backup <name> --include-namespaces dev,prod --wait`.
3. Load the databases back: `bash scripts/velero-restore-db.sh dev` (and `prod` if used).

## Why databases need step 3
The lab's local-path disks are `hostPath` volumes, which Velero's file copy skips. So every database pod
(sitekit-db, civic-hub-db) and the ParkingClub lab carry a **pre-backup hook**: right before a backup,
`pg_dump` (or `tar` for ParkingClub's KV) writes into a small emptyDir called `backup`, which Velero does copy.
A restore brings the apps back with empty disks plus that dump; step 3 loads it.
This goes away once the lab moves to NFS (or another storage Velero can copy).
