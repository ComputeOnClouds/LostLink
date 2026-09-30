import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as apigwv2int from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as apigwv2auth from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { Construct } from 'constructs';
import { LostLinkConfig, resourceName } from './config';
import { AuthStack } from './auth-stack';
import { DataStack } from './data-stack';

/**
 * ApiStack — API Gateway (HTTP API v2) + request Lambdas + Cognito JWT authorizer.
 *
 * Task 4 adds the individual lost-item reporting handler and its routes. The HTTP API
 * and the shared JWT authorizer are exposed as public props so later tasks (staff
 * inventory Task 5, claims Tasks 11-12) attach more routes to the same API.
 *
 * Depends on: AuthStack (user pool + client for the authorizer), DataStack
 * (Items table + photos bucket). Exposes: apiUrl output, plus httpApi/authorizer props.
 */
export interface ApiStackProps extends cdk.StackProps {
  readonly config: LostLinkConfig;
  readonly auth: AuthStack;
  readonly data: DataStack;
}

export class ApiStack extends cdk.Stack {
  public readonly httpApi: apigwv2.HttpApi;
  public readonly authorizer: apigwv2auth.HttpUserPoolAuthorizer;
  public claimsFn!: lambda.Function;
  public claimsIntegration!: apigwv2int.HttpLambdaIntegration;

  /** Path to the backend Python code bundled into every handler Lambda. */
  private readonly backendPath = path.join(__dirname, '..', '..', 'backend');

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    // ---- HTTP API + Cognito JWT authorizer ----------------------------------------
    this.httpApi = new apigwv2.HttpApi(this, 'HttpApi', {
      apiName: resourceName('Api'),
      corsPreflight: {
        allowOrigins: ['*'], // tighten to the CloudFront origin in Task 6 if desired
        allowMethods: [apigwv2.CorsHttpMethod.ANY],
        allowHeaders: ['Content-Type', 'Authorization'],
      },
    });

    this.authorizer = new apigwv2auth.HttpUserPoolAuthorizer(
      'JwtAuthorizer',
      props.auth.userPool,
      { userPoolClients: [props.auth.userPoolClient] }
    );

    // ---- Individual lost-item reporting handler (Task 4) --------------------------
    const reportsFn = this.pythonHandler('ReportsFn', 'api.reports_handler.handler', {
      ITEMS_TABLE: props.data.itemsTable.tableName,
      PHOTOS_BUCKET: props.data.photosBucket.bucketName,
      MATCH_QUEUE_URL: props.data.matchQueue.queueUrl,
    });

    // Permissions: read/write items, presign against the photos bucket, enqueue matches.
    props.data.itemsTable.grantReadWriteData(reportsFn);
    props.data.photosBucket.grantReadWrite(reportsFn);
    props.data.matchQueue.grantSendMessages(reportsFn);

    const reportsIntegration = new apigwv2int.HttpLambdaIntegration(
      'ReportsIntegration',
      reportsFn
    );

    const routes: Array<[apigwv2.HttpMethod, string]> = [
      [apigwv2.HttpMethod.POST, '/uploads'],
      [apigwv2.HttpMethod.POST, '/reports'],
      [apigwv2.HttpMethod.GET, '/reports'],
      [apigwv2.HttpMethod.GET, '/reports/{itemId}'],
      [apigwv2.HttpMethod.PATCH, '/reports/{itemId}'],
      [apigwv2.HttpMethod.DELETE, '/reports/{itemId}'],
    ];
    for (const [method, routePath] of routes) {
      this.httpApi.addRoutes({
        path: routePath,
        methods: [method],
        integration: reportsIntegration,
        authorizer: this.authorizer,
      });
    }

    // ---- Staff inventory management handler (Task 5) ------------------------------
    const staffFn = this.pythonHandler('StaffFn', 'api.staff_handler.handler', {
      ITEMS_TABLE: props.data.itemsTable.tableName,
      PHOTOS_BUCKET: props.data.photosBucket.bucketName,
      MATCH_QUEUE_URL: props.data.matchQueue.queueUrl,
      CLAIMS_TABLE: props.data.claimsTable.tableName, // withdrawal -> notify claimants
      SENDER_EMAIL: props.config.senderEmail,
    });
    props.data.itemsTable.grantReadWriteData(staffFn);
    props.data.photosBucket.grantReadWrite(staffFn);
    props.data.matchQueue.grantSendMessages(staffFn);
    props.data.claimsTable.grantReadWriteData(staffFn); // reject claims on withdrawal
    staffFn.addToRolePolicy(
      new iam.PolicyStatement({ actions: ['ses:SendEmail'], resources: ['*'] })
    );

    const staffIntegration = new apigwv2int.HttpLambdaIntegration(
      'StaffIntegration',
      staffFn
    );

    const staffRoutes: Array<[apigwv2.HttpMethod, string]> = [
      [apigwv2.HttpMethod.POST, '/items/uploads'],
      [apigwv2.HttpMethod.POST, '/items'],
      [apigwv2.HttpMethod.GET, '/items'],
      [apigwv2.HttpMethod.GET, '/items/{itemId}'],
      [apigwv2.HttpMethod.PATCH, '/items/{itemId}'],
      [apigwv2.HttpMethod.DELETE, '/items/{itemId}'],
    ];
    for (const [method, routePath] of staffRoutes) {
      this.httpApi.addRoutes({
        path: routePath,
        methods: [method],
        integration: staffIntegration,
        authorizer: this.authorizer,
      });
    }

    // ---- Claims handler (Tasks 11 individual + 12 staff) --------------------------
    const claimsFn = this.pythonHandler('ClaimsFn', 'api.claims_handler.handler', {
      ITEMS_TABLE: props.data.itemsTable.tableName,
      MATCHES_TABLE: props.data.matchesTable.tableName,
      CLAIMS_TABLE: props.data.claimsTable.tableName,
      PHOTOS_BUCKET: props.data.photosBucket.bucketName,
      SENDER_EMAIL: props.config.senderEmail, // claim-decision notifications (Task 12)
    });
    props.data.itemsTable.grantReadWriteData(claimsFn); // read items; T12 updates status
    props.data.matchesTable.grantReadData(claimsFn);
    props.data.claimsTable.grantReadWriteData(claimsFn);
    props.data.photosBucket.grantReadWrite(claimsFn); // evidence uploads
    claimsFn.addToRolePolicy(
      new iam.PolicyStatement({ actions: ['ses:SendEmail'], resources: ['*'] })
    );

    const claimsIntegration = new apigwv2int.HttpLambdaIntegration(
      'ClaimsIntegration',
      claimsFn
    );

    const claimsRoutes: Array<[apigwv2.HttpMethod, string]> = [
      // Individual (Task 11)
      [apigwv2.HttpMethod.GET, '/matches'],
      [apigwv2.HttpMethod.POST, '/claims/uploads'],
      [apigwv2.HttpMethod.POST, '/claims'],
      [apigwv2.HttpMethod.GET, '/claims'],
      [apigwv2.HttpMethod.GET, '/claims/{claimId}'],
      [apigwv2.HttpMethod.POST, '/claims/{claimId}/respond'],
      [apigwv2.HttpMethod.POST, '/claims/{claimId}/cancel'],
      // Staff (Task 12)
      [apigwv2.HttpMethod.GET, '/org/claims'],
      [apigwv2.HttpMethod.GET, '/org/claims/{claimId}'],
      [apigwv2.HttpMethod.POST, '/org/claims/{claimId}/request-info'],
      [apigwv2.HttpMethod.POST, '/org/claims/{claimId}/approve'],
      [apigwv2.HttpMethod.POST, '/org/claims/{claimId}/reject'],
      [apigwv2.HttpMethod.POST, '/org/claims/{claimId}/reserve'],
      [apigwv2.HttpMethod.POST, '/org/claims/{claimId}/handover'],
    ];
    for (const [method, routePath] of claimsRoutes) {
      this.httpApi.addRoutes({
        path: routePath,
        methods: [method],
        integration: claimsIntegration,
        authorizer: this.authorizer,
      });
    }
    // Keep a handle so Task 12 can add staff claim routes to the same function.
    this.claimsFn = claimsFn;
    this.claimsIntegration = claimsIntegration;

    new cdk.CfnOutput(this, 'ApiUrl', {
      value: this.httpApi.apiEndpoint,
      description: 'Base URL of the LostLink HTTP API',
      exportName: resourceName('ApiUrl'),
    });
  }

  /**
   * Creates a Python 3.12 Lambda bundling the whole `backend/` directory.
   *
   * boto3/botocore are provided by the Lambda runtime, so the plain code asset needs no
   * bundling step for these handlers (numpy-dependent code lives in the worker, Task 8).
   */
  private pythonHandler(
    id: string,
    handler: string,
    environment: Record<string, string>
  ): lambda.Function {
    return new lambda.Function(this, id, {
      functionName: resourceName(id),
      runtime: lambda.Runtime.PYTHON_3_12,
      handler,
      code: lambda.Code.fromAsset(this.backendPath, {
        exclude: ['.venv', 'tests', '**/__pycache__', '*.md', '.pytest_cache'],
      }),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment,
    });
  }
}
