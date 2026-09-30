import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import { Construct } from 'constructs';
import { LostLinkConfig, resourceName } from './config';

/**
 * AuthStack — Amazon Cognito user pool and app client.
 *
 * Defines:
 *  - a user pool with email sign-in + email verification (code),
 *  - a custom `organisationId` attribute (used by Staff to bind them to an org),
 *  - two groups: `Individual` and `Staff` (role is carried by group membership, which
 *    appears in the token as the `cognito:groups` claim),
 *  - a public SPA app client (no secret) supporting SRP and USER_PASSWORD auth flows.
 *
 * Exposes: userPoolId, userPoolClientId — consumed by ApiStack (JWT authorizer) and
 * FrontendStack (login config). See ARCHITECTURE.md section 1.1.
 */
export interface AuthStackProps extends cdk.StackProps {
  readonly config: LostLinkConfig;
}

/** Group names. Kept as constants so Lambdas/tests reference the same literals. */
export const GROUP_INDIVIDUAL = 'Individual';
export const GROUP_STAFF = 'Staff';

export class AuthStack extends cdk.Stack {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;

  constructor(scope: Construct, id: string, props: AuthStackProps) {
    super(scope, id, props);

    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: resourceName('Users'),
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: {
        email: { required: true, mutable: true },
      },
      // Staff carry the organisation they belong to. Mutable so an admin can reassign.
      // Individuals simply leave it empty.
      customAttributes: {
        organisationId: new cognito.StringAttribute({ mutable: true }),
      },
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      userVerification: {
        emailSubject: 'Verify your LostLink account',
        emailBody: 'Your LostLink verification code is {####}',
        emailStyle: cognito.VerificationEmailStyle.CODE,
      },
      // Prototype: allow full teardown. Change to RETAIN for production.
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.userPoolClient = this.userPool.addClient('WebClient', {
      userPoolClientName: resourceName('WebClient'),
      generateSecret: false, // public SPA client
      authFlows: {
        userSrp: true,
        userPassword: true, // used by the seed script and simple frontend login
      },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
      preventUserExistenceErrors: true,
    });

    new cognito.CfnUserPoolGroup(this, 'IndividualGroup', {
      userPoolId: this.userPool.userPoolId,
      groupName: GROUP_INDIVIDUAL,
      description: 'Individuals who report lost items and submit claims.',
    });

    new cognito.CfnUserPoolGroup(this, 'StaffGroup', {
      userPoolId: this.userPool.userPoolId,
      groupName: GROUP_STAFF,
      description: 'Organisation staff who manage found-item inventory and claims.',
    });

    new cdk.CfnOutput(this, 'UserPoolId', {
      value: this.userPool.userPoolId,
      description: 'Cognito user pool id',
      exportName: resourceName('UserPoolId'),
    });

    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: this.userPoolClient.userPoolClientId,
      description: 'Cognito app client id (public SPA client)',
      exportName: resourceName('UserPoolClientId'),
    });

    new cdk.CfnOutput(this, 'Region', {
      value: this.region,
      description: 'Region the user pool is deployed in',
    });
  }
}
