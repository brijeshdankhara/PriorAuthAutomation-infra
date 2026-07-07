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
        DataStack(self, "Data", stage_name=stage_name, vpc=network.vpc)
        IdentityStack(self, "Identity", stage_name=stage_name)
        AgentCoreStack(self, "AgentCore", stage_name=stage_name)
        ComputeStack(self, "Compute", stage_name=stage_name)
        EdgeStack(self, "Edge", stage_name=stage_name)
