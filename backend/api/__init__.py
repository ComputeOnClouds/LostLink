"""HTTP API request handlers and shared helpers for LostLink.

Handlers run behind API Gateway (HTTP API) with a Cognito JWT authorizer. The shared
modules here (auth, responses, s3urls) are reused by the individual-reporting handler
(Task 4), the staff-inventory handler (Task 5) and the claims handlers (Tasks 11-12).
"""
