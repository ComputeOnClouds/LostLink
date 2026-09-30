import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';
import { LostLinkConfig, resourceName } from './config';
import { AuthStack } from './auth-stack';
import { ApiStack } from './api-stack';
import { DataStack } from './data-stack';

/**
 * FrontendStack — S3 static hosting + CloudFront for the React app.
 *
 * The React app is built to `frontend/dist` and deployed to the DataStack frontend
 * bucket. A `config.json` is generated from the deployed stack values (API URL, Cognito
 * ids, region) and deployed alongside, so the same build works against any deployment
 * (see frontend/src/config.ts). CloudFront serves the private bucket via Origin Access
 * Identity; SPA deep links fall back to index.html.
 *
 * Depends on: DataStack (frontend bucket), AuthStack (Cognito ids), ApiStack (API URL).
 */
export interface FrontendStackProps extends cdk.StackProps {
  readonly config: LostLinkConfig;
  readonly auth: AuthStack;
  readonly api: ApiStack;
  readonly data: DataStack;
}

export class FrontendStack extends cdk.Stack {
  public readonly distributionDomainName: string;

  constructor(scope: Construct, id: string, props: FrontendStackProps) {
    super(scope, id, props);

    // Hosting bucket lives here (not DataStack) so the CloudFront read grant, which
    // mutates the bucket policy, does not create a cross-stack dependency cycle.
    const frontendBucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `${resourceName('frontend').toLowerCase()}-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // Modern Origin Access Control (OAC); S3Origin+OAI is deprecated.
    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: resourceName('Frontend'),
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(frontendBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      // SPA fallback: serve index.html for client-side routes / missing keys.
      errorResponses: [
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html' },
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' },
      ],
    });
    this.distributionDomainName = distribution.distributionDomainName;

    // Deploy the built app + a generated runtime config.json, then invalidate the CDN.
    new s3deploy.BucketDeployment(this, 'DeployFrontend', {
      destinationBucket: frontendBucket,
      distribution,
      distributionPaths: ['/*'],
      sources: [
        s3deploy.Source.asset(path.join(__dirname, '..', '..', 'frontend', 'dist')),
        s3deploy.Source.jsonData('config.json', {
          apiUrl: props.api.httpApi.apiEndpoint,
          region: this.region,
          userPoolId: props.auth.userPool.userPoolId,
          userPoolClientId: props.auth.userPoolClient.userPoolClientId,
        }),
      ],
    });

    new cdk.CfnOutput(this, 'CloudFrontUrl', {
      value: `https://${distribution.distributionDomainName}`,
      description: 'LostLink web app URL',
      exportName: resourceName('CloudFrontUrl'),
    });
  }
}
