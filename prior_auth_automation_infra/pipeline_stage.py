import os

from aws_cdk import Stage
from constructs import Construct

from prior_auth_automation_infra.stacks.agentcore_stack import AgentCoreStack
from prior_auth_automation_infra.stacks.compute_stack import ComputeStack
from prior_auth_automation_infra.stacks.data_stack import DataStack
from prior_auth_automation_infra.stacks.edge_stack import EdgeStack
from prior_auth_automation_infra.stacks.identity_stack import IdentityStack
from prior_auth_automation_infra.stacks.network_stack import NetworkStack


class PriorAuthStage(Stage):
    """One full environment (Beta or Prod) as a set of CloudFormation stacks.

    Both stages are deployed from this same app into the same AWS account;
    they're kept apart by stage-prefixed stack/resource names, not by
    separate accounts.
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        network = NetworkStack(self, "Network", stage_name=stage_name)
        data = DataStack(self, "Data", stage_name=stage_name, vpc=network.vpc)
        identity = IdentityStack(self, "Identity", stage_name=stage_name)
        agentcore = AgentCoreStack(
            self,
            "AgentCore",
            stage_name=stage_name,
            aurora_cluster_arn=data.cluster.cluster_arn,
            aurora_secret_arn=data.cluster.secret.secret_arn,
            aurora_database_name="priorauth",
        )
        compute = ComputeStack(
            self,
            "Compute",
            stage_name=stage_name,
            aurora_cluster_arn=data.cluster.cluster_arn,
            aurora_secret_arn=data.cluster.secret.secret_arn,
            aurora_database_name="priorauth",
            documents_bucket_name=data.documents_bucket.bucket_name,
            documents_kms_key=data.kms_key,
            evaluation_agent_runtime_arn=agentcore.evaluation_runtime.agent_runtime_arn,
        )
        EdgeStack(
            self,
            "Edge",
            stage_name=stage_name,
            aurora_cluster_arn=data.cluster.cluster_arn,
            aurora_secret_arn=data.cluster.secret.secret_arn,
            aurora_app_runtime_secret_arn=data.app_runtime_secret.secret_arn,
            aurora_database_name="priorauth",
            documents_bucket_name=data.documents_bucket.bucket_name,
            documents_kms_key=data.kms_key,
            cognito_user_pool_id=identity.user_pool.user_pool_id,
            cognito_client_id=identity.user_pool_client.user_pool_client_id,
            pa_request_created_topic_arn=compute.pa_request_created_topic.topic_arn,
            # The demo practice's id isn't known to CDK -- it's seeded data,
            # not an infra resource -- so it comes in via env var, set once
            # the practice has actually been created (see scripts/).
            public_guest_tenant_id=os.environ.get("PUBLIC_GUEST_TENANT_ID", ""),
        )
