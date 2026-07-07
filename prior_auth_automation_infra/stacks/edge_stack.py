from aws_cdk import Stack
from constructs import Construct


class EdgeStack(Stack):
    """CloudFront distribution serving the React frontend (built assets in
    an S3 bucket) plus the API Gateway front door for the FastAPI backend.

    Placeholder until the frontend has a production build and the backend
    API Lambda exists to route to.
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # TODO (vertical slice): S3 + CloudFront for the frontend build,
        # API Gateway HTTP API in front of the ComputeStack's API Lambda.
