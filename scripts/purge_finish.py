#!/usr/bin/env python3
"""Fast finish of the data purge: batch-delete remaining Matches rows + delete Cognito
users. Uses DynamoDB batch_writer (25/req) so it's far faster than per-item CLI calls."""
import os
import subprocess
import boto3

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")


def cfn(stack, export):
    return subprocess.run(
        ["aws", "cloudformation", "describe-stacks", "--region", REGION,
         "--stack-name", stack, "--query",
         f"Stacks[0].Outputs[?ExportName=='{export}'].OutputValue", "--output", "text"],
        capture_output=True, text=True).stdout.strip()


ddb = boto3.resource("dynamodb", region_name=REGION)
matches = ddb.Table(cfn("LostLink-Data", "LostLink-MatchesTableName"))

print("Batch-deleting remaining Matches rows...")
n = 0
scan = matches.scan(ProjectionExpression="queryItemId,candidateItemId")
with matches.batch_writer() as bw:
    while True:
        for it in scan.get("Items", []):
            bw.delete_item(Key={"queryItemId": it["queryItemId"],
                                "candidateItemId": it["candidateItemId"]})
            n += 1
        if "LastEvaluatedKey" not in scan:
            break
        scan = matches.scan(ProjectionExpression="queryItemId,candidateItemId",
                            ExclusiveStartKey=scan["LastEvaluatedKey"])
print(f"  deleted {n} matches")

pool = cfn("LostLink-Auth", "LostLink-UserPoolId")
cog = boto3.client("cognito-idp", region_name=REGION)
users = cog.list_users(UserPoolId=pool).get("Users", [])
for u in users:
    cog.admin_delete_user(UserPoolId=pool, Username=u["Username"])
    print(f"  deleted user {u['Username']}")
print("Done.")
