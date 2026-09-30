/**
 * Cognito authentication via amazon-cognito-identity-js (USER_PASSWORD flow).
 *
 * Kept small: sign in, sign out, current session (with token refresh), and decoding the
 * role/org claims from the ID token. This is the auth layer the portals depend on.
 */
import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserSession,
} from 'amazon-cognito-identity-js';
import { RuntimeConfig } from './config';

export interface Identity {
  email: string | null;
  groups: string[];
  organisationId: string | null;
  idToken: string;
}

let pool: CognitoUserPool | null = null;

function userPool(cfg: RuntimeConfig): CognitoUserPool {
  if (!pool) {
    pool = new CognitoUserPool({
      UserPoolId: cfg.userPoolId,
      ClientId: cfg.userPoolClientId,
    });
  }
  return pool;
}

function parseGroups(claim: unknown): string[] {
  if (Array.isArray(claim)) return claim as string[];
  if (typeof claim === 'string') {
    return claim.replace(/[[\]]/g, '').split(/[ ,]+/).filter(Boolean);
  }
  return [];
}

function identityFromSession(session: CognitoUserSession): Identity {
  const payload = session.getIdToken().decodePayload();
  return {
    email: (payload['email'] as string) ?? null,
    groups: parseGroups(payload['cognito:groups']),
    organisationId: (payload['custom:organisationId'] as string) ?? null,
    idToken: session.getIdToken().getJwtToken(),
  };
}

export function signIn(cfg: RuntimeConfig, email: string, password: string): Promise<Identity> {
  const user = new CognitoUser({ Username: email, Pool: userPool(cfg) });
  const details = new AuthenticationDetails({ Username: email, Password: password });
  return new Promise((resolve, reject) => {
    user.authenticateUser(details, {
      onSuccess: (session) => resolve(identityFromSession(session)),
      onFailure: (err) => reject(new Error(err.message || 'Sign-in failed')),
      // A fresh seeded user could be in FORCE_CHANGE_PASSWORD; our seed sets permanent
      // passwords, so this path is not expected, but handle it defensively.
      newPasswordRequired: () => reject(new Error('Password change required.')),
    });
  });
}

export function currentIdentity(cfg: RuntimeConfig): Promise<Identity | null> {
  const user = userPool(cfg).getCurrentUser();
  if (!user) return Promise.resolve(null);
  return new Promise((resolve) => {
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) {
        resolve(null);
        return;
      }
      resolve(identityFromSession(session));
    });
  });
}

export function signOut(cfg: RuntimeConfig): void {
  userPool(cfg).getCurrentUser()?.signOut();
}
