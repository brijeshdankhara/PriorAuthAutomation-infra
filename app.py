#!/usr/bin/env python3
import os

import aws_cdk as cdk

from prior_auth_automation_infra.pipeline_stage import PriorAuthStage

app = cdk.App()

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region=os.getenv("CDK_DEFAULT_REGION", "us-east-1"),
)

PriorAuthStage(app, "PriorAuth-Beta", stage_name="beta", env=env)
PriorAuthStage(app, "PriorAuth-Prod", stage_name="prod", env=env)

app.synth()
