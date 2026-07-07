from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    """VPC for the Aurora Serverless v2 cluster.

    No NAT gateway: Lambda talks to Aurora over the RDS Data API (HTTPS,
    outside the VPC), so nothing in the private subnets needs outbound
    internet access. Keeping this isolated-only avoids paying for a NAT
    gateway on a low-traffic demo app.
    """

    def __init__(self, scope: Construct, construct_id: str, *, stage_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            vpc_name=f"prior-auth-{stage_name}",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )
