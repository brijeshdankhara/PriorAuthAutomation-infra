from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from constructs import Construct


class IdentityStack(Stack):
    """Cognito User Pool for login. Tenant/role authorization itself lives in
    Postgres (practice_membership table), not in Cognito groups -- see
    ARCHITECTURE.md.

    MFA is optional in both stages -- this only ever holds synthetic demo
    data, so requiring TOTP enrollment is unnecessary friction rather than
    a real security need. The password auth flows are still stage-gated:
    beta test scripts authenticate with admin-set passwords; prod allows
    only SRP (password never transits to the server) -- that split is about
    keeping scripted testing easy in beta, independent of the MFA choice.
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_beta = stage_name == "beta"

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"prior-auth-{stage_name}",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.DESTROY if is_beta else RemovalPolicy.RETAIN,
        )

        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            auth_flows=cognito.AuthFlow(
                user_srp=True,
                user_password=is_beta,
                admin_user_password=is_beta,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
            ),
        )

        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id)
