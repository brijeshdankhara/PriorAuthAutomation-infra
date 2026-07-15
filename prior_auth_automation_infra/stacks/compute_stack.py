import pathlib

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

# Same sibling-repo layout as AgentCoreStack -- the Docker build context for
# the extraction Lambda has to be the backend repo root (uv workspace).
_BACKEND_ROOT = str(pathlib.Path(__file__).resolve().parents[3] / "PriorAuthAutomation-backend")


class ComputeStack(Stack):
    """The event-driven evaluation pipeline: SNS 'pa-request-created' fires a
    trigger Lambda that starts a Step Functions execution, which
    Textract-extracts any pending documents, hands off to the PA Evaluation
    Agent (Bedrock AgentCore Runtime, from AgentCoreStack), and publishes
    'pa-evaluation-complete' when done. This is the real async worker the
    synchronous /evaluate API endpoint stands in for during interactive use.
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
        documents_bucket_name: str,
        documents_kms_key: kms.IKey,
        evaluation_agent_runtime_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.pa_request_created_topic = sns.Topic(
            self,
            "PaRequestCreatedTopic",
            topic_name=f"prior-auth-{stage_name}-pa-request-created",
        )

        self.pa_evaluation_complete_topic = sns.Topic(
            self,
            "PaEvaluationCompleteTopic",
            topic_name=f"prior-auth-{stage_name}-pa-evaluation-complete",
        )

        self.criteria_set_published_topic = sns.Topic(
            self,
            "CriteriaSetPublishedTopic",
            topic_name=f"prior-auth-{stage_name}-criteria-set-published",
        )

        # -- Extraction step: Textract-extract any pending documents on the
        # request. Docker-based since it needs the full pa-tools/pa-db
        # dependency closure (sqlalchemy, the Data API dialect, boto3).
        extraction_fn = lambda_.DockerImageFunction(
            self,
            "ExtractionFunction",
            function_name=f"prior-auth-{stage_name}-extraction",
            code=lambda_.DockerImageCode.from_image_asset(
                _BACKEND_ROOT,
                file="apps/agents/Dockerfile.lambda",
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "AURORA_CLUSTER_ARN": aurora_cluster_arn,
                "AURORA_SECRET_ARN": aurora_secret_arn,
                "AURORA_DATABASE_NAME": aurora_database_name,
                "DOCUMENTS_BUCKET_NAME": documents_bucket_name,
            },
        )
        extraction_fn.add_to_role_policy(
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
        extraction_fn.add_to_role_policy(
            iam.PolicyStatement(actions=["secretsmanager:GetSecretValue"], resources=[aurora_secret_arn])
        )
        extraction_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"arn:aws:s3:::{documents_bucket_name}/*"],
            )
        )
        # Textract reads the S3 object under this function's role -- SSE-KMS
        # objects need an explicit decrypt grant on top of s3:GetObject.
        documents_kms_key.grant_decrypt(extraction_fn)
        extraction_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "textract:StartDocumentTextDetection",
                    "textract:GetDocumentTextDetection",
                ],
                resources=["*"],
            )
        )

        # -- Evaluation step: hand off to the PA Evaluation Agent on
        # AgentCore Runtime. Deliberately thin (boto3 only, inline code) --
        # all the actual judgment logic lives in the agent, not here.
        evaluation_invoke_fn = lambda_.Function(
            self,
            "EvaluationInvokeFunction",
            function_name=f"prior-auth-{stage_name}-evaluation-invoke",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.minutes(3),
            environment={"EVALUATION_AGENT_RUNTIME_ARN": evaluation_agent_runtime_arn},
            code=lambda_.Code.from_inline(
                """
import json, os, boto3

def handler(event, context):
    client = boto3.client("bedrock-agentcore")
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=os.environ["EVALUATION_AGENT_RUNTIME_ARN"],
        contentType="application/json",
        accept="application/json",
        payload=json.dumps({"pa_request_id": event["pa_request_id"]}).encode(),
    )
    body = resp["response"].read()
    result = json.loads(body)
    if resp["statusCode"] >= 400:
        raise RuntimeError(f"evaluation runtime returned {resp['statusCode']}: {result}")
    return result
""".strip()
            ),
        )
        evaluation_invoke_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                # The action is authorized against the endpoint sub-resource,
                # not the bare runtime ARN.
                resources=[
                    evaluation_agent_runtime_arn,
                    f"{evaluation_agent_runtime_arn}/runtime-endpoint/*",
                ],
            )
        )

        # -- The state machine: extract -> evaluate -> publish completion.
        extract_step = tasks.LambdaInvoke(
            self,
            "ExtractDocuments",
            lambda_function=extraction_fn,
            payload=sfn.TaskInput.from_object({"pa_request_id": sfn.JsonPath.string_at("$.pa_request_id")}),
            output_path="$.Payload",
        )
        evaluate_step = tasks.LambdaInvoke(
            self,
            "InvokeEvaluationAgent",
            lambda_function=evaluation_invoke_fn,
            payload=sfn.TaskInput.from_object({"pa_request_id": sfn.JsonPath.string_at("$.pa_request_id")}),
            output_path="$.Payload",
        )
        publish_step = tasks.SnsPublish(
            self,
            "PublishEvaluationComplete",
            topic=self.pa_evaluation_complete_topic,
            message=sfn.TaskInput.from_object(
                {
                    "pa_request_id": sfn.JsonPath.string_at("$.pa_request_id"),
                    "outcome": sfn.JsonPath.string_at("$.outcome"),
                    "review_mode": sfn.JsonPath.string_at("$.review_mode"),
                }
            ),
        )

        definition = extract_step.next(evaluate_step).next(publish_step)

        self.evaluation_state_machine = sfn.StateMachine(
            self,
            "EvaluationStateMachine",
            state_machine_name=f"prior-auth-{stage_name}-evaluation-pipeline",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(10),
        )

        # -- The trigger: SNS 'pa-request-created' -> start the pipeline.
        # Thin and boto3-only, same reasoning as evaluation_invoke_fn.
        trigger_fn = lambda_.Function(
            self,
            "PipelineTriggerFunction",
            function_name=f"prior-auth-{stage_name}-pipeline-trigger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.seconds(30),
            environment={"EVALUATION_STATE_MACHINE_ARN": self.evaluation_state_machine.state_machine_arn},
            code=lambda_.Code.from_inline(
                """
import json, os, boto3

def handler(event, context):
    sfn = boto3.client("stepfunctions")
    for record in event["Records"]:
        message = json.loads(record["Sns"]["Message"])
        sfn.start_execution(
            stateMachineArn=os.environ["EVALUATION_STATE_MACHINE_ARN"],
            input=json.dumps({"pa_request_id": message["pa_request_id"]}),
        )
""".strip()
            ),
        )
        self.evaluation_state_machine.grant_start_execution(trigger_fn)
        self.pa_request_created_topic.add_subscription(subs.LambdaSubscription(trigger_fn))

        CfnOutput(self, "PaRequestCreatedTopicArn", value=self.pa_request_created_topic.topic_arn)
        CfnOutput(self, "PaEvaluationCompleteTopicArn", value=self.pa_evaluation_complete_topic.topic_arn)
        CfnOutput(self, "CriteriaSetPublishedTopicArn", value=self.criteria_set_published_topic.topic_arn)
        CfnOutput(self, "EvaluationStateMachineArn", value=self.evaluation_state_machine.state_machine_arn)

        # TODO: API Lambda (FastAPI via Lambda Web Adapter) -- the API still
        # runs as a local process against deployed Beta resources for the
        # browser demo. AgentCore Gateway tool Lambdas (get_criteria_set,
        # get_document_extraction, validate_citation) remain a placeholder
        # too -- the authoring agent still queries SQL directly.
