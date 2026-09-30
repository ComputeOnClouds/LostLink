#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../infra"
T=cdk.out/LostLink-Auth.template.json
echo "Cognito resource types:"
grep -oE 'AWS::Cognito::[A-Za-z]+' "$T" | sort | uniq -c
echo "Key tokens present:"
for tok in organisationId Individual Staff EmailOnly USER_PASSWORD; do
  n=$(grep -oc "$tok" "$T" || true)
  echo "  $tok: $n"
done
