import hmac
import time
import httpx
from fastapi import HTTPException, Request
from jose import jwt, JWTError

class Security:
    def __init__(self, settings):
        self.settings = settings
        self.keys = None
        self.expires = 0

    def staff(self, request: Request, capture=False, owner=False):
        s = self.settings
        if s.auth_mode == 'local':
            if owner and request.headers.get('X-Demo-User') == 'mechanic':
                raise HTTPException(403, 'Owner access is required')
            return 'local-mechanic' if request.headers.get('X-Demo-User') == 'mechanic' else 'local-owner'
        token = request.headers.get('Authorization', '')
        if not token.startswith('Bearer '):
            raise HTTPException(401, 'Sign in to continue')
        try:
            if self.keys is None or time.monotonic() > self.expires:
                r = httpx.get(s.cognito_issuer.rstrip('/') + '/.well-known/jwks.json', timeout=4)
                r.raise_for_status()
                self.keys = r.json()
                self.expires = time.monotonic() + 300
            claims = jwt.decode(token[7:], self.keys, algorithms=['RS256'], issuer=s.cognito_issuer,
                                options={'verify_aud': False, 'require_exp': True, 'require_iat': True})
            if claims.get('token_use') != 'access' or claims.get('client_id') not in s.cognito_client_ids.split(','):
                raise JWTError('Wrong token use/client')
            groups = set(claims.get('cognito:groups', []))
            if owner and 'OWNER' not in groups:
                raise HTTPException(403, 'Owner access is required')
            if not groups.intersection({'OWNER', 'MECHANIC'}):
                if not capture or 'stocklane/capture' not in claims.get('scope', '').split():
                    raise HTTPException(403, 'Staff access is required')
            return claims.get('sub') or claims['client_id']
        except HTTPException:
            raise
        except (JWTError, ValueError, httpx.HTTPError):
            raise HTTPException(401, 'Session is invalid or expired') from None

    def internal(self, request: Request):
        if self.settings.auth_mode!='local' and (request.method!='GET' or not request.url.path.startswith('/internal/captures/')):
            raise HTTPException(403,'This internal HTTP capability is disabled; events use IAM-authenticated SQS')
        required=self.settings.internal_token if self.settings.auth_mode=='local' else self.settings.vision_read_token
        if not hmac.compare_digest(request.headers.get('X-Internal-Token', ''), required):
            raise HTTPException(401, 'Invalid service identity')
