import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { LostLinkConfig, resourceName } from './config';

/**
 * NotificationStack — Amazon SES configuration for email notifications.
 *
 * Creates a verified SES email identity for the sender (only when a real address is
 * configured via SENDER_EMAIL — the `.example` placeholder is skipped so deploys don't
 * fail). Notifications are deduplicated per report-item pair inside the worker's
 * SesNotifier (RATIONALE ADR-021). This stack exposes the sender address; the worker's
 * SES send permission is granted in MatchingStack.
 *
 * SES sandbox note: the sender must be verified (click the link SES emails), and
 * recipients must also be verified unless they are the mailbox simulator
 * (*@simulator.amazonses.com), which is always accepted.
 */
export interface NotificationStackProps extends cdk.StackProps {
  readonly config: LostLinkConfig;
}

export class NotificationStack extends cdk.Stack {
  public readonly senderEmail: string;

  constructor(scope: Construct, id: string, props: NotificationStackProps) {
    super(scope, id, props);

    this.senderEmail = props.config.senderEmail;

    // The sender identity is verified MANUALLY in the SES console (an email address, or
    // a domain). We deliberately do NOT create a CDK-managed ses.EmailIdentity here: in
    // the SES sandbox the address is verified by clicking a link, and a CDK identity for
    // an already-verified address would conflict. This stack just records the configured
    // sender; the worker/claims Lambdas use it (RATIONALE ADR-021/023).
    // (If you later move to a domain identity managed by CDK, add it here.)

    new cdk.CfnOutput(this, 'SenderEmail', {
      value: this.senderEmail,
      description: 'SES sender identity for notifications (verify it in the SES console)',
      exportName: resourceName('SenderEmail'),
    });
  }
}
