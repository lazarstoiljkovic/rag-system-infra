import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

export class NetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly inferenceSg: ec2.SecurityGroup;
  public readonly lambdaSg: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    this.vpc = new ec2.Vpc(this, 'RagVpc', {
      maxAzs: 3,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
      ],
    });

    this.vpc.addGatewayEndpoint('S3Endpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });
    this.vpc.addGatewayEndpoint('DynamoDbEndpoint', {
      service: ec2.GatewayVpcEndpointAwsService.DYNAMODB,
    });

    this.lambdaSg = new ec2.SecurityGroup(this, 'LambdaSg', {
      vpc: this.vpc,
      description: 'Lambda funkcije koje pozivaju privatno hostovane modele',
      allowAllOutbound: true,
    });

    this.inferenceSg = new ec2.SecurityGroup(this, 'InferenceSg', {
      vpc: this.vpc,
      description: 'GPU instanca: vLLM (8000) i embedding servis (8001)',
      allowAllOutbound: true,
    });

    for (const port of [8000, 8001]) {
      this.inferenceSg.addIngressRule(
        this.lambdaSg,
        ec2.Port.tcp(port),
        `Lambda ka model serving (${port})`,
      );
    }

    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId });
  }
}
