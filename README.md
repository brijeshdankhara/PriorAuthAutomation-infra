# PriorAuthAutomation-infra

> Part of a 4-repo portfolio project: **infra** (this repo) · [backend](https://github.com/brijeshdankhara/PriorAuthAutomation-backend) · [frontend](https://github.com/brijeshdankhara/PriorAuthAutomation-frontend) · [docs](https://github.com/brijeshdankhara/PriorAuthAutomation-docs)
>
> This is a portfolio/demo project (synthetic data only, no real patients or providers). Live demo: `www.brijeshdankhara.com/auto-pa-test`.

AWS CDK (Python) app for the Prior Authorization Automation Platform — an AI-assisted system that reviews prior-authorization requests against payer criteria and drafts new criteria checklists from payer policy documents. See [docs/ARCHITECTURE.md](https://github.com/brijeshdankhara/PriorAuthAutomation-docs/blob/main/ARCHITECTURE.md) for the full design and [docs/PROMOTION.md](https://github.com/brijeshdankhara/PriorAuthAutomation-docs/blob/main/PROMOTION.md) for the Beta→Prod procedure this repo implements.

## Environments

One CDK app deploys **two environments in the same AWS account**: `PriorAuth-Beta` and `PriorAuth-Prod`. Each is a `Stage` (`prior_auth_automation_infra/pipeline_stage.py`) that instantiates the same six stacks with `stage_name` parameterized — Beta and Prod are structurally identical infrastructure, just separate resources (separate Aurora clusters, separate Cognito pools, separate everything) kept apart by stage-prefixed names, not by separate AWS accounts.

The standing rule: every change is built and verified in Beta first, then promoted to Prod. See `docs/PROMOTION.md`.

## The six stacks

- **Network** — a VPC for Aurora with no NAT gateway. Lambda talks to Aurora over the RDS Data API (HTTPS), so nothing needs outbound internet access from inside the VPC.
- **Data** — Aurora Serverless v2 (Postgres, `serverless_v2_min_capacity=0` so it pauses to near-zero cost when idle), S3 buckets for uploaded documents and payer policy PDFs (both SSE-KMS encrypted), and the KMS key itself.
- **Identity** — a Cognito User Pool for login. MFA is optional in both stages (this only ever holds synthetic demo data). Prod's app client only allows SRP auth (the password never transits to the server); Beta's client also allows password-based auth flows, to keep scripted testing simple.
- **AgentCore** — the two AI agents (PA Evaluation Agent, Criteria-Authoring Agent), each hosted as its own ARM64 container on **Bedrock AgentCore Runtime** (`AWS::BedrockAgentCore::Runtime`), built directly from the backend repo's `apps/agents/Dockerfile`.
- **Compute** — the async evaluation pipeline: an SNS topic (`pa-request-created`) triggers a Lambda that starts a Step Functions execution (Textract-extract pending documents → invoke the PA Evaluation Agent on AgentCore Runtime → publish `pa-evaluation-complete`).
- **Edge** — the REST API itself, running as a Lambda container (FastAPI via the AWS Lambda Web Adapter) behind a CloudFront distribution. CloudFront exists specifically to get AWS Shield Standard (free DDoS protection) and a place to attach a WAF Web ACL — a bare Lambda Function URL can't have WAF attached directly. The WAF Web ACL combines AWS managed rule groups (core rule set, known-bad-inputs) with two rate-based rules (a general per-IP limit, plus a tighter one scoped to the guest-token-minting endpoint). A `reserved_concurrent_executions` cap on the API Lambda is a second, structural ceiling on cost/load independent of WAF.

Why Step Functions and not LangChain: Step Functions orchestrates infrastructure-level steps (extract → evaluate → notify) with retries and visibility — it does no AI reasoning itself. The actual agent logic is a single `bedrock.converse()` call per decision with everything the model needs in the prompt; there's no dynamic multi-step reasoning loop for something like LangChain to orchestrate, so it isn't used here.

## Setup

```
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt -r requirements-dev.txt
source .venv/bin/activate
```

This repo assumes it's checked out as a sibling directory of `PriorAuthAutomation-backend` (`../PriorAuthAutomation-backend`) — the Docker-based stacks (AgentCore, Compute's extraction Lambda, Edge's API Lambda) build their images directly from that repo's source, so both repos need to be cloned side by side:

```
some-folder/
  PriorAuthAutomation-infra/
  PriorAuthAutomation-backend/
```

## Useful commands

- `cdk ls` — list all stacks across both stages
- `cdk synth` — synthesize CloudFormation templates (no AWS credentials needed)
- `cdk deploy PriorAuth-Beta/<StackName>` — deploy one stack to Beta (requires AWS credentials; this is a billed AWS action)
- `cdk deploy PriorAuth-Prod/<StackName>` — deploy one stack to Prod, only after the same change is verified in Beta
- `cdk diff PriorAuth-Beta/<StackName>` — compare deployed state with current code

## Notes

- `cdk.context.json` is gitignored — it caches CDK's lookups (availability zones, etc.) and can contain the AWS account ID, so it isn't committed.
- Model IDs (`BEDROCK_EVALUATION_MODEL_ID`, `BEDROCK_DRAFTING_MODEL_ID`) are read from the deploying shell's environment with a sensible default baked in — always confirm these are exported before a real deploy, since a stale/missing export silently redeploys with the default.
