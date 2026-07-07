# PriorAuthAutomation-infra

AWS CDK (Python) app for the Prior Authorization Automation Platform. See [ARCHITECTURE.md](../PriorAuthAutomation-docs/ARCHITECTURE.md) in the docs repo for the full design.

One CDK app deploys **two environments** in the same AWS account — `PriorAuth-Beta` and `PriorAuth-Prod` — each a `Stage` (`prior_auth_automation_infra/pipeline_stage.py`) bundling six stacks:

- **Network** — a VPC for Aurora, no NAT gateway (Lambda reaches the database over the RDS Data API, not by being in the VPC)
- **Data** — Aurora Serverless v2 (Postgres), S3 buckets for documents and policy PDFs, KMS
- **Identity** — Cognito User Pool (MFA required)
- **AgentCore** — Bedrock AgentCore Runtime agents, Gateway, and the Knowledge Base backing the criteria-authoring agent's retrieval step (placeholder until the backend has a deployable agent artifact)
- **Compute** — SNS topics now; the API Lambda, Step Functions evaluation workflow, and AgentCore Gateway tool Lambdas once the backend has code to deploy
- **Edge** — CloudFront + API Gateway (placeholder until the frontend has a build and the API Lambda exists)

## Setup

```
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt -r requirements-dev.txt
source .venv/bin/activate
```

## Useful commands

- `cdk ls` — list all stacks across both stages
- `cdk synth` — synthesize CloudFormation templates (no AWS credentials needed)
- `cdk deploy PriorAuth-Beta/<StackName>` — deploy one stack to Beta (requires AWS credentials; confirm before running — this is a billed AWS action)
- `cdk diff PriorAuth-Beta/<StackName>` — compare deployed state with current code
