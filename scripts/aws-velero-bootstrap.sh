#!/usr/bin/env bash
# One command for Velero on AWS S3: private + encrypted bucket, least-privilege IAM user, key sealed straight into the repo.
# Needs the AWS CLI logged in as you (aws configure / aws sso login). The new access key is never printed or saved in plain text.
#   bash scripts/aws-velero-bootstrap.sh cloudkanata-homelab-backups ca-central-1
set -euo pipefail
BUCKET="${1:?usage: aws-velero-bootstrap.sh <bucket> [region]}"; REGION="${2:-ca-central-1}"; IAMUSER="velero-homelab"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
command -v aws >/dev/null || { echo "Install the AWS CLI first: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"; exit 1; }
aws sts get-caller-identity --query Arn --output text

echo "== Bucket s3://$BUCKET ($REGION): private, encrypted, versioned"
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" --create-bucket-configuration LocationConstraint="$REGION"; fi
fi
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration '{"Rules":[
  {"ID":"old-versions","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":14},
   "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}'

echo "== IAM user $IAMUSER (this bucket only)"
aws iam get-user --user-name "$IAMUSER" >/dev/null 2>&1 || aws iam create-user --user-name "$IAMUSER" >/dev/null
aws iam put-user-policy --user-name "$IAMUSER" --policy-name velero-homelab-s3 --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [
    {\"Effect\": \"Allow\", \"Action\": [\"s3:GetObject\", \"s3:DeleteObject\", \"s3:PutObject\", \"s3:AbortMultipartUpload\", \"s3:ListMultipartUploadParts\"],
     \"Resource\": \"arn:aws:s3:::$BUCKET/*\"},
    {\"Effect\": \"Allow\", \"Action\": [\"s3:ListBucket\"], \"Resource\": \"arn:aws:s3:::$BUCKET\"}
  ]}"
n="$(aws iam list-access-keys --user-name "$IAMUSER" --query 'length(AccessKeyMetadata)' --output text)"
[ "$n" -ge 2 ] && { echo "$IAMUSER already has 2 access keys; delete an old one in the IAM console first."; exit 1; }

echo "== New access key -> sealed secret (not shown)"
read -r VELERO_AK VELERO_SK < <(aws iam create-access-key --user-name "$IAMUSER" --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
export VELERO_AK VELERO_SK
bash "$REPO_DIR/scripts/setup-velero.sh" "$BUCKET" "$REGION"
unset VELERO_AK VELERO_SK
