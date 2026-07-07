from aws_cdk import Stack
from constructs import Construct


class AgentCoreStack(Stack):
    """Bedrock AgentCore Runtime agents (PA Evaluation Agent, Criteria-
    Authoring Agent), the AgentCore Gateway exposing our Lambda tools to
    them, and the Bedrock Knowledge Base (backed by pgvector on the Aurora
    cluster from DataStack) used by the authoring agent's retrieval step.

    An AgentCoreRuntime needs a built agent artifact (a container image
    built from the Strands agent code in the backend repo) to point at, and
    that doesn't exist yet -- this stack is a placeholder until the first
    vertical slice builds the actual agent code and its deployable image.
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # TODO (vertical slice):
        #   - aws_cdk.aws_bedrockagentcore.CfnRuntime for the PA Evaluation Agent
        #   - aws_cdk.aws_bedrockagentcore.CfnRuntime for the Criteria-Authoring Agent
        #   - aws_cdk.aws_bedrockagentcore.Gateway + CfnGatewayTarget per tool Lambda
        #   - Bedrock Knowledge Base construct pointed at the Aurora pgvector store
