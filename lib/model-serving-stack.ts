import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface ModelServingStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly inferenceSg: ec2.ISecurityGroup;
}

/**
 * Inference sloj — jedino mesto u sistemu gde postoji GPU.
 *
 * Lambda nema GPU podrsku, pa svaka funkcija koja dotice model (captioning,
 * embedding, generisanje) je tanak HTTP klijent ka ovoj instanci. To je
 * razlog cele podele na slojeve.
 *
 * ASG min=0/max=1, pali se i gasi RUCNO preko CLI-ja — bez EventBridge
 * automatizacije (FinOps optimizacija bez veze sa temom rada).
 *
 * Posledica ASG izbora koju treba imati na umu: svako paljenje pravi NOVU
 * instancu, pa se tezine modela (~8GB) skidaju iznova. Prvo dizanje traje
 * osetno duze od narednih restartova koje bi imala obicna stop/start instanca.
 * Ako to postane usko grlo tokom evaluacije, resenje je unapred pripremljen
 * AMI sa kesiranim modelima, ne menjanje zivotnog ciklusa.
 */
export class ModelServingStack extends cdk.Stack {
  /**
   * Tag po kome Lambda funkcije pronalaze IP instance preko
   * ec2:DescribeInstances — bez ALB-a i bez Parameter Store-a.
   */
  public static readonly INFERENCE_TAG_NAME = 'vllm-server';

  /** Port vLLM-a koji servira Qwen2.5-VL (captioning I generisanje). */
  public static readonly VLM_PORT = 8000;
  /** Port embedding servisa (bge-m3). */
  public static readonly EMBEDDING_PORT = 8001;

  /**
   * Deep Learning AMI preko javnog SSM parametra, a ne preko
   * `MachineImage.lookup`. Lookup bi zakucao konkretan AMI ID u
   * `cdk.context.json`, koji je u `.gitignore`-u, pa bi se na drugoj masini
   * razresio u nesto drugo. SSM parametar se razresava u trenutku deploy-a.
   *
   * Naziv obrasca je proveren: stari pattern `Deep Learning AMI GPU PyTorch*`
   * iz ranije dokumentacije ne vraca nijednu sliku.
   */
  private static readonly DLAMI_SSM_PARAM =
    '/aws/service/deeplearning/ami/x86_64/oss-nvidia-driver-gpu-pytorch-2.12-ubuntu-24.04/latest/ami-id';

  /**
   * Tipovi GPU instance po prioritetu. Oba nose ISTU karticu — 1x A10G, 24GB —
   * i razlikuju se samo u CPU-u i RAM-u (4 vCPU/16GB naspram 8 vCPU/32GB).
   * Merenja zato ostaju uporediva bez obzira koji tip ASG dobije.
   *
   * Razlog je kapacitet, ne performanse: 2026-09-24 `g5.xlarge` nije bio
   * dostupan ni u jednoj od tri zone preko pola sata
   * (`InsufficientInstanceCapacity`). AWS vodi svaki tip kao zaseban pool, pa
   * je `g5.2xlarge` ponekad slobodan kad `xlarge` nije — bez garancije, jer
   * dele istu vrstu hosta. Skuplji je, pa je drugi po redu.
   *
   * Drugi GPU (npr. `g6.xlarge`, L4) NAMERNO nije na listi: menjao bi hardver
   * opisan u radu i validiran u fazi 2, a pinovane CUDA/torch verzije na njemu
   * nisu proverene. Kvota L-DB2E81BA je 8 vCPU, pa oba tipa staju.
   */
  public static readonly INSTANCE_TYPES = ['g5.xlarge', 'g5.2xlarge'];

  public readonly autoScalingGroup: autoscaling.AutoScalingGroup;

  constructor(scope: Construct, id: string, props: ModelServingStackProps) {
    super(scope, id, props);

    const role = new iam.Role(this, 'InferenceInstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'GPU instanca koja servira privatno hostovane modele',
      managedPolicies: [
        // Session Manager: pristup ljusci bez SSH kljuca i bez otvaranja
        // porta 22. Jedini nacin da se udje na instancu za dijagnostiku.
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });

    // Instanca sama sebe taguje sa vllm-status=ready kad oba servisa odgovore.
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ec2:CreateTags'],
        resources: [
          cdk.Arn.format({ service: 'ec2', resource: 'instance', resourceName: '*' }, this),
        ],
      }),
    );

    const userData = ec2.UserData.custom(
      fs.readFileSync(
        path.join(__dirname, '..', 'ec2-userdata', 'vllm-bootstrap.sh'),
        'utf8',
      ),
    );

    const launchTemplate = new ec2.LaunchTemplate(this, 'VllmLaunchTemplate', {
      machineImage: ec2.MachineImage.fromSsmParameter(ModelServingStack.DLAMI_SSM_PARAM, {
        os: ec2.OperatingSystemType.LINUX,
      }),
      // Tip se ovde samo podrazumeva; stvarni izbor radi lista u ASG-u ispod.
      instanceType: new ec2.InstanceType(ModelServingStack.INSTANCE_TYPES[0]),
      // Javna IP: instanci treba internet da skine tezine modela, a NAT
      // Gateway je odbacen kao neopravdan trosak. Izolaciju nosi inferenceSg,
      // koji prima saobracaj samo sa Lambda SG-a.
      associatePublicIpAddress: true,
      securityGroup: props.inferenceSg,
      role,
      userData,
      requireImdsv2: true,
      blockDevices: [
        {
          deviceName: '/dev/sda1',
          // Osnovni AMI je 30GB. Na to dolaze venv sa vLLM-om i PyTorch-om
          // (~15GB) i tezine Qwen2.5-VL-AWQ i bge-m3 (~10GB), dakle ~55GB.
          // 100GB ostavlja rezervu za HF cache i logove. Volumen se brise sa
          // instancom, pa dok je ASG na nuli ne kosta nista.
          volume: ec2.BlockDeviceVolume.ebs(100, {
            volumeType: ec2.EbsDeviceVolumeType.GP3,
            encrypted: true,
            deleteOnTermination: true,
          }),
        },
      ],
    });

    this.autoScalingGroup = new autoscaling.AutoScalingGroup(this, 'VllmAsg', {
      vpc: props.vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      // Lista tipova po prioritetu umesto jednog tipa. ASG proba prvi, pa
      // sledeci tek kad prvog nema ni u jednoj zoni. Vidi INSTANCE_TYPES.
      mixedInstancesPolicy: {
        launchTemplate,
        launchTemplateOverrides: ModelServingStack.INSTANCE_TYPES.map((type) => ({
          instanceType: new ec2.InstanceType(type),
        })),
        instancesDistribution: {
          onDemandAllocationStrategy: autoscaling.OnDemandAllocationStrategy.PRIORITIZED,
          // Iskljucivo on-demand: spot instancu AWS sme da ugasi usred
          // evaluacije, a za GPU je spot kapacitet ionako jos oskudniji.
          onDemandBaseCapacity: 0,
          onDemandPercentageAboveBaseCapacity: 100,
        },
      },
      // Bez desiredCapacity: ASG tada krece od minCapacity, dakle od nule, i
      // ponovni deploy ne budi instancu koju si malopre rucno ugasio.
      minCapacity: 0,
      maxCapacity: 1,
    });

    // Tag po kome Lambde pronalaze instancu preko ec2:DescribeInstances.
    cdk.Tags.of(this.autoScalingGroup).add('Name', ModelServingStack.INFERENCE_TAG_NAME);

    new cdk.CfnOutput(this, 'AsgName', {
      value: this.autoScalingGroup.autoScalingGroupName,
      description: 'Ime ASG-a za rucno paljenje i gasenje GPU instance',
    });
    new cdk.CfnOutput(this, 'StartCommand', {
      value: `aws autoscaling set-desired-capacity --auto-scaling-group-name ${this.autoScalingGroup.autoScalingGroupName} --desired-capacity 1`,
    });
    new cdk.CfnOutput(this, 'StopCommand', {
      value: `aws autoscaling set-desired-capacity --auto-scaling-group-name ${this.autoScalingGroup.autoScalingGroupName} --desired-capacity 0`,
    });
  }
}
