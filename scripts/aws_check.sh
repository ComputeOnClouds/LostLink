#!/usr/bin/env bash
set -euo pipefail
aws configure set region ap-southeast-2
aws configure set output json
echo "region: $(aws configure get region)"
echo "identity:"
aws sts get-caller-identity
