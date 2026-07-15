import pathlib

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct

# Same sibling-repo layout as the other Docker-based stacks.
_BACKEND_ROOT = str(pathlib.Path(__file__).resolve().parents[3] / "PriorAuthAutomation-backend")


class EdgeStack(Stack):
    """The API, deployed as a Lambda container (via the AWS Lambda Web
    Adapter) behind a CloudFront distribution -- CloudFront gets it AWS
    Shield Standard (free DDoS protection) and the ability to attach a WAF
    Web ACL, neither of which a bare Lambda Function URL supports directly.

    This CloudFront distribution uses its own default domain -- it is
    backend-only plumbing. The real public domain (e.g.
    www.brijeshdankhara.com) is presented by Vercel, which proxies
    /auto-pa-test/api/* to this distribution's domain.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_name: str,
        aurora_cluster_arn: str,
        aurora_secret_arn: str,
        aurora_app_runtime_secret_arn: str,
        aurora_database_name: str,
        documents_bucket_name: str,
        documents_kms_key: kms.IKey,
        cognito_user_pool_id: str,
        cognito_client_id: str,
        pa_request_created_topic_arn: str,
        public_guest_tenant_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        guest_token_secret = secretsmanager.Secret(
            self,
            "GuestTokenSecret",
            secret_name=f"prior-auth-{stage_name}-guest-token",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True, password_length=40
            ),
        )

        api_execution_role = iam.Role(
            self, "ApiExecutionRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )
        api_execution_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )
        api_execution_role.add_to_policy(
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
        api_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[aurora_secret_arn, aurora_app_runtime_secret_arn],
            )
        )
        api_execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject", "s3:GetObject"],
                resources=[f"arn:aws:s3:::{documents_bucket_name}/*"],
            )
        )
        # A presigned PUT is signed by this role, and IAM evaluates the
        # eventual upload as if this role performed it -- so it needs
        # encrypt permission on the bucket's SSE-KMS key too, not just
        # s3:PutObject, or every presigned upload 403s the moment someone
        # actually uses the URL.
        documents_kms_key.grant_encrypt_decrypt(api_execution_role)
        api_execution_role.add_to_policy(
            iam.PolicyStatement(actions=["sns:Publish"], resources=[pa_request_created_topic_arn])
        )
        guest_token_secret.grant_read(api_execution_role)

        api_fn = lambda_.DockerImageFunction(
            self,
            "ApiFunction",
            function_name=f"prior-auth-{stage_name}-api",
            code=lambda_.DockerImageCode.from_image_asset(
                _BACKEND_ROOT,
                file="apps/api/Dockerfile",
                platform=ecr_assets.Platform.LINUX_ARM64,
            ),
            architecture=lambda_.Architecture.ARM_64,
            role=api_execution_role,
            memory_size=512,
            timeout=Duration.seconds(30),
            # A hard, structural cost/load ceiling: under any traffic burst
            # (legitimate or not), this bounds how many requests run at
            # once. Excess requests get a clean 429 instead of the account
            # scaling (and paying for) unbounded concurrency.
            reserved_concurrent_executions=10,
            environment={
                "AURORA_CLUSTER_ARN": aurora_cluster_arn,
                "AURORA_SECRET_ARN": aurora_secret_arn,
                "AURORA_APP_RUNTIME_SECRET_ARN": aurora_app_runtime_secret_arn,
                "AURORA_DATABASE_NAME": aurora_database_name,
                "DOCUMENTS_BUCKET_NAME": documents_bucket_name,
                "COGNITO_USER_POOL_ID": cognito_user_pool_id,
                "COGNITO_CLIENT_ID": cognito_client_id,
                "PA_REQUEST_CREATED_TOPIC_ARN": pa_request_created_topic_arn,
                "PUBLIC_GUEST_ENABLED": "true",
                "PUBLIC_GUEST_TENANT_ID": public_guest_tenant_id,
                # A CloudFormation dynamic reference, not the literal value --
                # resolved securely by the Lambda service at deploy time.
                "GUEST_TOKEN_SECRET": guest_token_secret.secret_value.unsafe_unwrap(),
                # Deliberately omitted: DEV_LOGIN_ENABLED. That shortcut is
                # for running the API directly on a laptop only.
            },
        )
        fn_url = api_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        web_acl = wafv2.CfnWebACL(
            self,
            "ApiWebAcl",
            scope="CLOUDFRONT",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloud_watch_metrics_enabled=True,
                metric_name=f"prior-auth-{stage_name}-api-waf",
            ),
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedCoreRuleSet",
                    priority=0,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS", name="AWSManagedRulesCommonRuleSet"
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"prior-auth-{stage_name}-core-rules",
                    ),
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedKnownBadInputs",
                    priority=1,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS", name="AWSManagedRulesKnownBadInputsRuleSet"
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"prior-auth-{stage_name}-known-bad-inputs",
                    ),
                ),
                # General rate limit: any single IP hammering the API.
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitPerIp",
                    priority=2,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=600,  # requests per 5-minute window per IP
                            aggregate_key_type="IP",
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"prior-auth-{stage_name}-rate-limit",
                    ),
                ),
                # Tighter limit specifically on guest-token minting, to stop
                # token-issuance abuse independent of the general rate limit.
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitGuestToken",
                    priority=3,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=60,
                            aggregate_key_type="IP",
                            scope_down_statement=wafv2.CfnWebACL.StatementProperty(
                                byte_match_statement=wafv2.CfnWebACL.ByteMatchStatementProperty(
                                    search_string="/auth/guest-token",
                                    field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(uri_path={}),
                                    positional_constraint="STARTS_WITH",
                                    text_transformations=[
                                        wafv2.CfnWebACL.TextTransformationProperty(priority=0, type="NONE")
                                    ],
                                )
                            ),
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"prior-auth-{stage_name}-rate-limit-guest-token",
                    ),
                ),
            ],
        )

        distribution = cloudfront.Distribution(
            self,
            "ApiDistribution",
            web_acl_id=web_acl.attr_arn,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.FunctionUrlOrigin(fn_url),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
        )

        CfnOutput(self, "ApiDistributionDomainName", value=distribution.distribution_domain_name)
        CfnOutput(self, "ApiFunctionUrl", value=fn_url.url)
