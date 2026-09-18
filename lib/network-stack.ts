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
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
      ],
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
        `Lambda -> model serving (${port})`,
      );
      // Razvoj: rucni curl sa developerove masine.
      this.inferenceSg.addIngressRule(
        ec2.Peer.ipv4(props.developerCidr),
        ec2.Port.tcp(port),
        `Developer -> model serving (${port})`,
      );
    }

    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId });
  }
}
