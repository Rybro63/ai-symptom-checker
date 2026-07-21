"""Authentication dependency.

API Gateway's JWT authorizer validates the Cognito token *before* the request
reaches Lambda, so by the time we're here the token is trusted. The verified
claims arrive in the Lambda event, which Mangum exposes via request.scope.
We just read the user's stable id (the `sub` claim).

In tests, this dependency is overridden to inject a fake user.
"""
from fastapi import HTTPException, Request


def get_current_user_id(request: Request) -> str:
    """Return the authenticated user's Cognito sub, or 401 if absent."""
    event = request.scope.get("aws.event") or {}
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return sub
