#!/usr/bin/env node
/**
 * LostLink CDK app entry point.
 *
 * Instantiates the six independent stacks and wires their cross-stack dependencies.
 * See ARCHITECTURE.md section 1.4 for the dependency graph.
 */
import * as cdk from 'aws-cdk-lib';
import { config, resourceName } from '../lib/config';
import { AuthStack } from '../lib/auth-stack';
import { DataStack } from '../lib/data-stack';
import { ApiStack } from '../lib/api-stack';
import { MatchingStack } from '../lib/matching-stack';
import { NotificationStack } from '../lib/notification-stack';
import { FrontendStack } from '../lib/frontend-stack';

const app = new cdk.App();

const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: config.region,
};

const auth = new AuthStack(app, resourceName('Auth'), { config, env });
const data = new DataStack(app, resourceName('Data'), { config, env });
const notification = new NotificationStack(app, resourceName('Notification'), { config, env });

const api = new ApiStack(app, resourceName('Api'), { config, auth, data, env });
const matching = new MatchingStack(app, resourceName('Matching'), {
  config,
  data,
  notification,
  env,
});
const frontend = new FrontendStack(app, resourceName('Frontend'), {
  config,
  auth,
  api,
  data,
  env,
});

// Cross-stack dependencies are enforced automatically once stacks reference each
// other's resources (Tasks 2-10). The props wiring above already documents intent.
// Reference the constructed stacks so linters don't flag them as unused.
void [auth, data, notification, api, matching, frontend];

app.synth();
