import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import { LostLinkConfig, resourceName } from './config';

/**
 * DataStack — DynamoDB tables and S3 buckets.
 *
 * Design notes (see RATIONALE ADR-012):
 *  - A single Items table holds BOTH lost reports and found items (they share the
 *    matching pipeline and shape; ItemType distinguishes them). GSIs support the three
 *    access patterns: an individual's own reports, a staff org's inventory, and the
 *    cross-org candidate retrieval used by matching.
 *  - The organisation id is a first-class key component (orgType GSI PK) so staff-scoped
 *    queries cannot cross the org boundary at the data layer.
 *  - Claims, Matches and Organisations are separate tables.
 *  - Two buckets: item photos (private) and frontend hosting (Task 6).
 *
 * Exposes: table + bucket handles as public readonly props for cross-stack references,
 * and their names as stack outputs.
 */
export interface DataStackProps extends cdk.StackProps {
  readonly config: LostLinkConfig;
}

export class DataStack extends cdk.Stack {
  public readonly itemsTable: dynamodb.Table;
  public readonly claimsTable: dynamodb.Table;
  public readonly matchesTable: dynamodb.Table;
  public readonly organisationsTable: dynamodb.Table;
  public readonly photosBucket: s3.Bucket;
  public readonly matchQueue: sqs.Queue;
  public readonly matchDlq: sqs.Queue;

  // GSI names, exported as constants so Lambdas reference the same literals.
  public static readonly GSI_BY_OWNER = 'by-owner';
  public static readonly GSI_BY_ORG_TYPE = 'by-org-type';
  public static readonly GSI_BY_TYPE = 'by-type';

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    const removalPolicy = cdk.RemovalPolicy.DESTROY; // prototype: allow teardown

    // ---- Items table (lost reports + found items) ---------------------------------
    this.itemsTable = new dynamodb.Table(this, 'ItemsTable', {
      tableName: resourceName('Items'),
      partitionKey: { name: 'itemId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST, // free-tier friendly, no idle cost
      removalPolicy,
      pointInTimeRecovery: false,
    });

    // Individual lists their own reports: PK ownerId, sorted by createdAt.
    this.itemsTable.addGlobalSecondaryIndex({
      indexName: DataStack.GSI_BY_OWNER,
      partitionKey: { name: 'ownerId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Staff lists/searches their org inventory: PK orgType = "<orgId>#<itemType>".
    // Encoding the org in the PK keeps staff queries inside their org boundary.
    this.itemsTable.addGlobalSecondaryIndex({
      indexName: DataStack.GSI_BY_ORG_TYPE,
      partitionKey: { name: 'orgType', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Cross-org candidate retrieval for matching: PK itemType ("lost"|"found").
    // The BruteForceRetriever queries all "found" (or "lost") items across every org.
    this.itemsTable.addGlobalSecondaryIndex({
      indexName: DataStack.GSI_BY_TYPE,
      partitionKey: { name: 'itemType', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ---- Claims table -------------------------------------------------------------
    this.claimsTable = new dynamodb.Table(this, 'ClaimsTable', {
      tableName: resourceName('Claims'),
      partitionKey: { name: 'claimId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });
    // A claimant's own claims.
    this.claimsTable.addGlobalSecondaryIndex({
      indexName: DataStack.GSI_BY_OWNER,
      partitionKey: { name: 'claimantId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });
    // Staff review: claims against a given organisation.
    this.claimsTable.addGlobalSecondaryIndex({
      indexName: DataStack.GSI_BY_ORG_TYPE,
      partitionKey: { name: 'organisationId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ---- Matches table ------------------------------------------------------------
    // PK = queryItemId (the lost report), SK = candidateItemId (the found item).
    // Lets us read all candidate matches for a report, and upsert per pair. The
    // per-pair notification dedup flag (Task 10) lives on these items.
    this.matchesTable = new dynamodb.Table(this, 'MatchesTable', {
      tableName: resourceName('Matches'),
      partitionKey: { name: 'queryItemId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'candidateItemId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });

    // ---- Organisations table ------------------------------------------------------
    this.organisationsTable = new dynamodb.Table(this, 'OrganisationsTable', {
      tableName: resourceName('Organisations'),
      partitionKey: { name: 'organisationId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });

    // ---- S3 buckets ---------------------------------------------------------------
    // Private bucket for item photos. Browser uploads/downloads use presigned URLs, so
    // the bucket stays fully private with CORS allowing PUT/GET from the SPA.
    this.photosBucket = new s3.Bucket(this, 'PhotosBucket', {
      bucketName: `${resourceName('photos').toLowerCase()}-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy,
      autoDeleteObjects: true, // prototype teardown convenience
      cors: [
        {
          allowedMethods: [s3.HttpMethods.PUT, s3.HttpMethods.GET, s3.HttpMethods.HEAD],
          allowedOrigins: ['*'], // tightened to the CloudFront origin in Task 6
          allowedHeaders: ['*'],
          maxAge: 3000,
        },
      ],
    });

    // NOTE: the frontend hosting bucket lives in FrontendStack, not here. Co-locating
    // it with the CloudFront distribution avoids a cross-stack bucket-policy dependency
    // cycle (the OAI read grant mutates the bucket policy). Nothing else uses it.

    // ---- SQS match-job queue (+ DLQ) ----------------------------------------------
    // Lives here (created before Api + Matching, depended on by both) so the producers
    // (request Lambdas) and the consumer (worker) reference one queue without a
    // cross-stack cycle. See RATIONALE ADR-019.
    this.matchDlq = new sqs.Queue(this, 'MatchDlq', {
      queueName: resourceName('match-dlq'),
      retentionPeriod: cdk.Duration.days(14),
    });
    this.matchQueue = new sqs.Queue(this, 'MatchQueue', {
      queueName: resourceName('match-jobs'),
      visibilityTimeout: cdk.Duration.seconds(180), // >= 6x worker timeout (30s)
      deadLetterQueue: { queue: this.matchDlq, maxReceiveCount: 3 },
    });

    // ---- Outputs ------------------------------------------------------------------
    const out = (idName: string, value: string, exportName: string) =>
      new cdk.CfnOutput(this, idName, { value, exportName: resourceName(exportName) });

    out('ItemsTableName', this.itemsTable.tableName, 'ItemsTableName');
    out('ClaimsTableName', this.claimsTable.tableName, 'ClaimsTableName');
    out('MatchesTableName', this.matchesTable.tableName, 'MatchesTableName');
    out('OrganisationsTableName', this.organisationsTable.tableName, 'OrganisationsTableName');
    out('PhotosBucketName', this.photosBucket.bucketName, 'PhotosBucketName');
    out('MatchQueueUrl', this.matchQueue.queueUrl, 'MatchQueueUrl');
  }
}
