from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from constructs import Construct


class DataStack(Stack):
    """Aurora Serverless v2 (Postgres) for tenant data, plus S3 for uploaded
    documents and payer policy PDFs.

    The same Aurora cluster (with the pgvector extension enabled at
    migration time, not here) also backs the Bedrock Knowledge Base used by
    the criteria-authoring agent -- one database engine for both the
    relational data and the vector index.

    Lambda reaches this cluster over the RDS Data API rather than being
    VPC-attached, so there's no NAT gateway or ENI cold-start cost.
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage_name: str, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_beta = stage_name == "beta"
        removal_policy = RemovalPolicy.DESTROY if is_beta else RemovalPolicy.RETAIN

        self.kms_key = kms.Key(
            self,
            "DataKey",
            alias=f"prior-auth-{stage_name}-data",
            enable_key_rotation=True,
            removal_policy=removal_policy,
        )

        self.documents_bucket = s3.Bucket(
            self,
            "DocumentsBucket",
            bucket_name=f"prior-auth-{stage_name}-documents-{self.account}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            enforce_ssl=True,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=removal_policy,
            auto_delete_objects=is_beta,
        )

        self.policy_docs_bucket = s3.Bucket(
            self,
            "PolicyDocsBucket",
            bucket_name=f"prior-auth-{stage_name}-policy-docs-{self.account}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            enforce_ssl=True,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=removal_policy,
            auto_delete_objects=is_beta,
        )

        self.db_security_group = ec2.SecurityGroup(
            self,
            "DbSecurityGroup",
            vpc=vpc,
            description="Aurora Serverless v2 cluster for the prior-auth platform",
            allow_all_outbound=False,
        )

        self.cluster = rds.DatabaseCluster(
            self,
            "AuroraCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(version=rds.AuroraPostgresEngineVersion.VER_16_4),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[self.db_security_group],
            writer=rds.ClusterInstance.serverless_v2("Writer"),
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=2,
            enable_data_api=True,
            storage_encrypted=True,
            storage_encryption_key=self.kms_key,
            default_database_name="priorauth",
            backup=rds.BackupProps(retention=Duration.days(1 if is_beta else 7)),
            removal_policy=removal_policy,
        )
