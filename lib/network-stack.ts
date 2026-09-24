import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

export interface NetworkStackProps extends cdk.StackProps {
  /**
   * CIDR sa koga je dozvoljen pristup portovima modela (8000/8001).
   * Tokom razvoja: javna IP adresa developera. Nikada 0.0.0.0/0.
   */
  readonly developerCidr: string;
}

/**
 * Mrezni sloj — lean verzija.
 *
 * Bez NAT Gateway-a i bez privatnih subnet-ova: GPU instanca ide u public
 * subnet, a izolaciju nosi restriktivna security group. Puna VPC izolacija
 * bi bila standardna praksa za produkciju sa realnim podacima — ovde je
 * korpus sinteticki i sistem postoji privremeno, pa se trosak NAT-a
 * (~0.045 USD/h) ne isplati.
 */
export class NetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  /** SG GPU instance koja servira modele (privatno hostovan inference sloj). */
  public readonly inferenceSg: ec2.SecurityGroup;
  /** SG Lambda funkcija koje pozivaju inference sloj preko mreze. */
  public readonly lambdaSg: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkStackProps) {
    super(scope, id, props);

    this.vpc = new ec2.Vpc(this, 'RagVpc', {
      // Tri zone, iako sistem koristi jednu instancu. Nije zbog dostupnosti
      // nego zbog KAPACITETA: g5.xlarge je oskudan i AWS ga nema u svakoj zoni
      // u svakom trenutku. Sa jednom zonom ASG nema gde da pokusa i dizanje
      // pada sa InsufficientInstanceCapacity — sto se i desilo u eu-central-1a.
      // Prazni public subnet-i ne kostaju nista, a NAT-a nema pa nema ni
      // troska po zoni.
      maxAzs: 3,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
      ],
    });

    // Lambde u ovom VPC-u nemaju izlaz na internet: nema NAT-a, a Lambda ENI
    // ne dobija javnu IP adresu ni u public subnet-u. Gateway endpointi su
    // jedini put do S3 i DynamoDB — i besplatni su, za razliku od interface
    // varijante. Preko S3 endpoint-a ide i odgovor CloudFormation custom
    // resource-a (PUT na presigned URL), pa bez njega deploy visi do timeout-a.
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

    // SG-to-SG: samo Lambde iz ovog VPC-a smeju na portove modela.
    for (const port of [8000, 8001]) {
      this.inferenceSg.addIngressRule(
        this.lambdaSg,
        ec2.Port.tcp(port),
        `Lambda ka model serving (${port})`,
      );
      // Razvoj: rucni curl sa developerove masine.
      this.inferenceSg.addIngressRule(
        ec2.Peer.ipv4(props.developerCidr),
        ec2.Port.tcp(port),
        `Developer ka model serving (${port})`,
      );
    }

    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId });
  }
}
