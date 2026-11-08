"""Create LostLink's AWS resources in moto and seed the demo users (idempotent).

The local equivalent of the Data + Auth CDK stacks (infra/lib/data-stack.ts,
auth-stack.ts) and scripts/seed_demo.sh; keep in sync. server.py runs it on start.
"""

import json
import os

import boto3
from botocore.exceptions import ClientError

DEMO_USERS = [  # same as scripts/seed_demo.sh
    ("user@lostlink.example", "User!Pass123", "Individual", None),
    ("user2@lostlink.example", "User2!Pass123", "Individual", None),
    ("staff@lostlink.example", "Staff!Pass123", "Staff", "org-nus"),
    ("staff2@lostlink.example", "Staff2!Pass123", "Staff", "org-other"),
]


def _create(call, exists_code, **kwargs):
    """Call a create API, treating 'already exists' as success."""
    try:
        call(**kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != exists_code:
            raise


def _table(ddb, name, keys, indexes=()):
    attrs = {k for k, _ in keys} | {pk for _, pk in indexes} | ({"createdAt"} if indexes else set())
    gsis = [{
        "IndexName": index,
        "KeySchema": [{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": "createdAt", "KeyType": "RANGE"}],
        "Projection": {"ProjectionType": "ALL"},
    } for index, pk in indexes]
    _create(
        ddb.create_table, "ResourceInUseException",
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in keys],
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in attrs],
        **({"GlobalSecondaryIndexes": gsis} if gsis else {}),
    )


def run():
    """Returns (user pool id, app client id)."""
    ddb, s3, sqs, cognito = (boto3.client(s) for s in ("dynamodb", "s3", "sqs", "cognito-idp"))
    _table(ddb, os.environ["ITEMS_TABLE"], [("itemId", "HASH")],
           [("by-owner", "ownerId"), ("by-org-type", "orgType"), ("by-type", "itemType")])
    _table(ddb, os.environ["CLAIMS_TABLE"], [("claimId", "HASH")],
           [("by-owner", "claimantId"), ("by-org-type", "organisationId")])
    _table(ddb, os.environ["MATCHES_TABLE"], [("queryItemId", "HASH"), ("candidateItemId", "RANGE")])
    _create(s3.create_bucket, "BucketAlreadyOwnedByYou", Bucket=os.environ["PHOTOS_BUCKET"],
            CreateBucketConfiguration={"LocationConstraint": os.environ["AWS_REGION"]})

    dlq = sqs.create_queue(QueueName="LostLink-match-dlq")["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sqs.create_queue(QueueName=os.environ["MATCH_QUEUE_URL"].rsplit("/", 1)[1], Attributes={
        "VisibilityTimeout": "180",
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}),
    })
    boto3.client("ses").verify_email_identity(EmailAddress=os.environ["SENDER_EMAIL"])
    if os.environ.get("ONEMAP_EMAIL"):
        _create(boto3.client("secretsmanager").create_secret, "ResourceExistsException",
                Name=os.environ["ONEMAP_SECRET_ARN"], SecretString=json.dumps(
                    {"email": os.environ["ONEMAP_EMAIL"], "password": os.environ["ONEMAP_PASSWORD"]}))

    pools = [p["Id"] for p in cognito.list_user_pools(MaxResults=60)["UserPools"] if p["Name"] == "LostLink-Users"]
    pool_id = pools[0] if pools else cognito.create_user_pool(
        PoolName="LostLink-Users",
        UsernameAttributes=["email"],
        AutoVerifiedAttributes=["email"],
        Policies={"PasswordPolicy": {"MinimumLength": 8, "RequireLowercase": True, "RequireUppercase": True,
                                     "RequireNumbers": True, "RequireSymbols": False}},
        Schema=[{"Name": "organisationId", "AttributeDataType": "String", "Mutable": True}],
    )["UserPool"]["Id"]
    clients = cognito.list_user_pool_clients(UserPoolId=pool_id, MaxResults=60)["UserPoolClients"]
    client_id = clients[0]["ClientId"] if clients else cognito.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName="LostLink-WebClient",
        ExplicitAuthFlows=["ALLOW_USER_SRP_AUTH", "ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
    )["UserPoolClient"]["ClientId"]
    for group in ("Individual", "Staff"):
        _create(cognito.create_group, "GroupExistsException", UserPoolId=pool_id, GroupName=group)

    for email, password, group, org in DEMO_USERS:
        attrs = [{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}]
        attrs += [{"Name": "custom:organisationId", "Value": org}] if org else []
        _create(cognito.admin_create_user, "UsernameExistsException", UserPoolId=pool_id, Username=email,
                MessageAction="SUPPRESS", UserAttributes=attrs)
        cognito.admin_set_user_password(UserPoolId=pool_id, Username=email, Password=password, Permanent=True)
        cognito.admin_add_user_to_group(UserPoolId=pool_id, Username=email, GroupName=group)

    print(f"Bootstrap done: user pool {pool_id}, {len(DEMO_USERS)} demo users", flush=True)
    return pool_id, client_id
