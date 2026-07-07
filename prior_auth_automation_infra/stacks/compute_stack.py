from aws_cdk import Stack
from aws_cdk import aws_sns as sns
from constructs import Construct


class ComputeStack(Stack):
    """SNS topics for the event-driven pipeline, plus (once the backend has
    deployable Lambda code) the API Lambda, the evaluation Step Functions
    workflow, and the Lambda functions backing the AgentCore Gateway tools.

    Left minimal for now -- there's no Lambda code to package yet. This gets
    filled in during the first vertical slice (see the build plan).
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage_name: str, **kwargs) -> None:
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

        # TODO (vertical slice): API Lambda (FastAPI via Lambda Web Adapter),
        # Textract-extraction Lambda, Step Functions state machine wiring
        # the evaluation pipeline, and the AgentCore Gateway tool Lambdas
        # (get_criteria_set, get_document_extraction, validate_citation).
