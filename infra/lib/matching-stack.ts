import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { Construct } from 'constructs';
import { LostLinkConfig, resourceName } from './config';
import { DataStack } from './data-stack';
import { NotificationStack } from './notification-stack';

/**
 * MatchingStack — the async matching worker Lambda.
 *
 * The SQS match-job queue (+ DLQ) lives in DataStack (created first, referenced by both
 * the request-Lambda producers and this consumer — RATIONALE ADR-019). This stack adds
 * the worker Lambda that consumes the queue and runs the pipeline
 * (DescriptionSource -> Embedder -> CandidateRetriever -> Scorer -> Notifier), plus its
 * IAM: Bedrock invoke, DynamoDB RW, S3 read (photos), SQS consume.
 *
 * Match weights + threshold and the retriever selector are injected as environment
 * variables from config (RATIONALE ADR-005).
 */
export interface MatchingStackProps extends cdk.StackProps {
  readonly config: LostLinkConfig;
  readonly data: DataStack;
  readonly notification: NotificationStack;
}

export class MatchingStack extends cdk.Stack {
  public readonly worker: lambda.Function;

  private readonly backendPath = path.join(__dirname, '..', '..', 'backend');

  constructor(scope: Construct, id: string, props: MatchingStackProps) {
    super(scope, id, props);

    const m = props.config.match;

    this.worker = new lambda.Function(this, 'MatchWorker', {
      functionName: resourceName('MatchWorker'),
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'pipeline.lambda_worker.handler',
      code: lambda.Code.fromAsset(this.backendPath, {
        exclude: ['.venv', 'tests', '**/__pycache__', '*.md', '.pytest_cache', 'api'],
      }),
      timeout: cdk.Duration.seconds(30),
      memorySize: 512, // headroom for embeddings + brute-force cosine
      // NOTE: we would cap the worker with reservedConcurrentExecutions to stop the
      // async matcher starving the interactive API Lambdas, but this AWS account has a
      // total Lambda concurrency limit of 10, and AWS requires >=10 unreserved to remain,
      // so any reservation is rejected. Documented in RATIONALE ADR-024; the fix on a
      // normal account (limit 1000) is `reservedConcurrentExecutions: <n>` here.
      environment: {
        ITEMS_TABLE: props.data.itemsTable.tableName,
        MATCHES_TABLE: props.data.matchesTable.tableName,
        PHOTOS_BUCKET: props.data.photosBucket.bucketName,
        BEDROCK_REGION: this.region,
        // Retriever selector (bruteforce | ann) — RATIONALE ADR-006.
        RETRIEVER: m.retriever,
        // Scoring weights + threshold — RATIONALE ADR-004/005.
        WEIGHT_TEXT: m.weightText,
        WEIGHT_IMAGE: m.weightImage,
        WEIGHT_LOCATION: m.weightLocation,
        WEIGHT_TIME: m.weightTime,
        MATCH_THRESHOLD: m.threshold,
        // Notifications (Task 10). SENDER_EMAIL must be a verified SES identity.
        SENDER_EMAIL: props.notification.senderEmail,
        CLOUDFRONT_URL: props.config.cloudFrontUrl, // linked in the match email
      },
    });

    // ---- Permissions --------------------------------------------------------------
    props.data.itemsTable.grantReadWriteData(this.worker); // cache desc + vectors
    props.data.matchesTable.grantReadWriteData(this.worker); // persist matches
    props.data.photosBucket.grantRead(this.worker); // read photos for description
    props.data.matchQueue.grantConsumeMessages(this.worker);

    // Bedrock: invoke the Titan embedding model + the Claude inference profile.
    // Inference-profile invocation also needs invoke on the underlying foundation
    // model ARNs it routes to, so we grant InvokeModel broadly on bedrock resources in
    // this account/region (prototype scope). RATIONALE ADR-018.
    this.worker.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel'],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/*`,
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
        ],
      })
    );

    // SES send permission for notifications (Task 10). Scoped to ses:SendEmail; the
    // sandbox still restricts actual delivery to verified/simulator addresses.
    this.worker.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['ses:SendEmail', 'ses:SendRawEmail'],
        resources: ['*'],
      })
    );

    // ---- SQS trigger --------------------------------------------------------------
    this.worker.addEventSource(
      new SqsEventSource(props.data.matchQueue, {
        batchSize: 5,
        reportBatchItemFailures: true, // partial-batch response from lambda_worker
      })
    );

    new cdk.CfnOutput(this, 'MatchWorkerName', {
      value: this.worker.functionName,
      description: 'Matching worker Lambda function name',
      exportName: resourceName('MatchWorkerName'),
    });
  }
}
