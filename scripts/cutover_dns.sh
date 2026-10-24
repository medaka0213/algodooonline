#!/bin/sh
# Point the algodooonline.net apex record at the serverless app or back at the
# legacy CloudFront SPA. www is a CNAME to the apex and follows automatically.
#
#   sh scripts/cutover_dns.sh lambda   # cut over (reads targets from terraform output)
#   sh scripts/cutover_dns.sh legacy   # roll back to the legacy CloudFront distribution
#
# Prints the change batch and asks for confirmation before calling Route53.
set -eu

cd "$(dirname "$0")/.."

MODE="${1:-}"
DOMAIN=algodooonline.net
# Legacy SPA distribution E7E2GUMAI90BB; Z2FDTNDATAQYW2 is CloudFront's fixed alias zone.
LEGACY_TARGET=dn5duvazyc7i7.cloudfront.net
LEGACY_TARGET_ZONE=Z2FDTNDATAQYW2

ZONE_ID=$(terraform -chdir=infra/aws output -raw hosted_zone_id)

case "$MODE" in
  lambda)
    TARGETS=$(terraform -chdir=infra/aws output -json dns_targets)
    TARGET=$(printf '%s' "$TARGETS" | python3 -c "import json,sys; print(json.load(sys.stdin)['$DOMAIN']['target_domain_name'])")
    TARGET_ZONE=$(printf '%s' "$TARGETS" | python3 -c "import json,sys; print(json.load(sys.stdin)['$DOMAIN']['hosted_zone_id'])")
    ;;
  legacy)
    TARGET=$LEGACY_TARGET
    TARGET_ZONE=$LEGACY_TARGET_ZONE
    ;;
  *)
    echo "usage: $0 lambda|legacy" >&2
    exit 2
    ;;
esac

BATCH=$(cat <<JSON
{
  "Comment": "algodooonline cutover: $MODE",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "$DOMAIN.",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "$TARGET_ZONE",
          "DNSName": "$TARGET",
          "EvaluateTargetHealth": false
        }
      }
    }
  ]
}
JSON
)

echo "zone: $ZONE_ID"
echo "$BATCH"
printf 'apply this change? [y/N] '
read -r answer
[ "$answer" = "y" ] || { echo "aborted"; exit 1; }

aws route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" --change-batch "$BATCH" \
  --query 'ChangeInfo.[Id,Status]' --output text
