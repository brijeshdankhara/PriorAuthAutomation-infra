import os
import pathlib

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from constructs import Construct

# The infra and backend repos are sibling checkouts, e.g.
# .../PriorAuthAutomation/PriorAuthAutomation-infra and .../PriorAuthAutomation-backend.
# The Docker build context has to be the backend repo root, not apps/agents,
# because it's a uv workspace with path-based dependencies on packages/*.
_BACKEND_ROOT = str(pathlib.Path(__file__).resolve().parents[3] / "PriorAuthAutomation-backend")


class AgentCoreStack(Stack):
    """The two agents -- PA Evaluation Agent and Criteria-Authoring Agent --
    hosted on Bedrock AgentCore Runtime, each as its own container image
    built from apps/agents/Dockerfile in the backend repo (same image,
    different RUNTIME_MODULE build arg selecting which FastAPI app to run).

    The API server invokes these over bedrock-agentcore's
    InvokeAgentRuntime rather than importing pa_agents in-process (see
    pa_api/agentcore_client.py) -- that's what makes this "hosted on
    AgentCore" rather than just library code the API happens to call.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_name: str,
        aurora_cluster_arn: str,
        aurora_secret_arn: str,
        aurora_database_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        execution_role = iam.Role(
            self,
            "AgentExecutionRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Converse"],
                resources=["*"],
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:ExecuteStatement",
                    "rds-data:BatchExecuteStatement",
                    "rds-data:BeginTransaction",
                    "rds-data:CommitTransaction",
                    "rds-data:RollbackTransaction",
                ],
                resources=[aurora_cluster_arn],
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[aurora_secret_arn],
            )
        )

        common_env = {
            "AURORA_CLUSTER_ARN": aurora_cluster_arn,
            "AURORA_SECRET_ARN": aurora_secret_arn,
            "AURORA_DATABASE_NAME": aurora_database_name,
            # Opus 4.8 is the real target (see the model-selection rationale in
            # the docs); overridable here the same way the local scripts are,
            # for the window while a new account's Bedrock access propagates.
            "BEDROCK_EVALUATION_MODEL_ID": os.environ.get(
                "BEDROCK_EVALUATION_MODEL_ID", "us.anthropic.claude-opus-4-8"
            ),
            "BEDROCK_DRAFTING_MODEL_ID": os.environ.get(
                "BEDROCK_DRAFTING_MODEL_ID", "us.anthropic.claude-opus-4-8"
            ),
        }

        self.evaluation_runtime = agentcore.Runtime(
            self,
            "EvaluationAgentRuntime",
            runtime_name=f"prior_auth_{stage_name}_evaluation",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_asset(
                _BACKEND_ROOT,
                file="apps/agents/Dockerfile",
                build_args={"RUNTIME_MODULE": "pa_agents.runtime_evaluation"},
                display_name=f"prior-auth-{stage_name}-evaluation-agent",
                # AgentCore Runtime requires ARM64 images regardless of the
                # host architecture doing the build.
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            execution_role=execution_role,
            environment_variables=common_env,
            description="Judges submitted PA documentation against each criterion in the "
            "request's active criteria_set, with a citation to the evidence relied on.",
        )

        self.authoring_runtime = agentcore.Runtime(
            self,
            "AuthoringAgentRuntime",
            runtime_name=f"prior_auth_{stage_name}_authoring",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_asset(
                _BACKEND_ROOT,
                file="apps/agents/Dockerfile",
                build_args={"RUNTIME_MODULE": "pa_agents.runtime_authoring"},
                display_name=f"prior-auth-{stage_name}-authoring-agent",
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            execution_role=execution_role,
            environment_variables=common_env,
            description="Drafts a criteria checklist from an ingested payer policy document "
            "for a human curator to review and publish.",
        )

        CfnOutput(self, "EvaluationAgentRuntimeArn", value=self.evaluation_runtime.agent_runtime_arn)
        CfnOutput(self, "AuthoringAgentRuntimeArn", value=self.authoring_runtime.agent_runtime_arn)

        # TODO (task #7): AgentCore Gateway + CfnGatewayTarget per tool Lambda
        # (get_criteria_set, get_document_extraction, validate_citation), and
        # the Bedrock Knowledge Base backed by pgvector on the Aurora cluster,
        # once the authoring agent moves off direct SQL retrieval.
