import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as opensearch from 'aws-cdk-lib/aws-opensearchservice';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';

export interface SearchStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly lambdaSg: ec2.ISecurityGroup;
}
export class SearchStack extends cdk.Stack {
  public readonly domain: opensearch.Domain;
  public readonly domainSg: ec2.SecurityGroup;

  public static readonly INDEX_NAME = 'rag-chunks';
  public static readonly VECTOR_DIM = 1024;

  public static readonly PIPELINES = {
    dense_bm25: 'rag-hybrid-dense-bm25',
    dense_bm25_sparse: 'rag-hybrid-dense-bm25-sparse',
    dense_bm25_rrf: 'rag-hybrid-dense-bm25-rrf',
    dense_bm25_lex: 'rag-hybrid-dense-bm25-lex',
  };

  public static readonly ENDPOINT_PARAM = '/rag/opensearch/endpoint';
  public static readonly INDEX_NAME_PARAM = '/rag/opensearch/index-name';

  constructor(scope: Construct, id: string, props: SearchStackProps) {
    super(scope, id, props);

    this.domainSg = new ec2.SecurityGroup(this, 'DomainSg', {
      vpc: props.vpc,
      description: 'OpenSearch domen: HTTPS samo iz Lambda SG-a',
      allowAllOutbound: true,
    });
    this.domainSg.addIngressRule(
      props.lambdaSg,
      ec2.Port.tcp(443),
      'Lambda ka OpenSearch (HTTPS)',
    );

    for (const [id, service] of [
      ['Ec2ApiEndpoint', ec2.InterfaceVpcEndpointAwsService.EC2],
      ['SsmApiEndpoint', ec2.InterfaceVpcEndpointAwsService.SSM],
    ] as const) {
      new ec2.InterfaceVpcEndpoint(this, id, {
        vpc: props.vpc,
        service,
        subnets: { subnets: [props.vpc.publicSubnets[0]] },
        privateDnsEnabled: true,
      });
    }

    this.domain = new opensearch.Domain(this, 'RagDomain', {
      // 2.19, a ne 3.x: hibridni search je ovde zreo i dokumentovan
      // (normalization processor postoji od 2.10), a opensearch-py
      // kompatibilnost je bezbolna.
      version: opensearch.EngineVersion.OPENSEARCH_2_19,
      capacity: {
        dataNodes: 1,
        dataNodeInstanceType: 't3.small.search',
        multiAzWithStandbyEnabled: false,
      },
      ebs: { volumeSize: 10, volumeType: ec2.EbsDeviceVolumeType.GP3 },
      vpc: props.vpc,
      // VPC ima tri subnet-a (zbog GPU kapaciteta), ali domen sa jednim
      // cvorom i bez zoneAwareness sme da bude u tacno jednom. Prvi je
      // eu-central-1a.
      vpcSubnets: [{ subnets: [props.vpc.publicSubnets[0]] }],
      securityGroups: [this.domainSg],
      zoneAwareness: { enabled: false },
      encryptionAtRest: { enabled: true },
      nodeToNodeEncryption: true,
      enforceHttps: true,
      // Indeks je izveden podatak — sme da nestane sa stack-om.
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Domen je u VPC-u i iza SG-a, ali pristup se dodatno vezuje za IAM:
    // saobracaj mora biti SigV4-potpisan identitetom iz ovog naloga.
    this.domain.addAccessPolicies(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.AccountRootPrincipal()],
        actions: ['es:ESHttp*'],
        resources: [`${this.domain.domainArn}/*`],
      }),
    );

    // Sema indeksa nastaje zajedno sa domenom. Bez eksternih zavisnosti
    // (botocore + urllib iz runtime-a), pa nema Docker build-a.
    const indexInit = new lambda.Function(this, 'IndexInitFunction', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda', 'index_init')),
      timeout: cdk.Duration.minutes(5),
      vpc: props.vpc,
      securityGroups: [props.lambdaSg],
      // Svesna odluka, ne previd: CDK ovde upozorava da Lambda u public
      // subnet-u nema internet. Tacno tako i jeste — izlaz ide preko gateway
      // endpointa za S3 i DynamoDB iz network-stack-a, a do OpenSearch-a se
      // stize unutar VPC-a. NAT bi resio isto, ali kosta ~0.045 USD/h.
      // Sve Lambde u fazama 4 i 5 trebace istu zastavicu.
      allowPublicSubnet: true,
      environment: {
        OPENSEARCH_ENDPOINT: this.domain.domainEndpoint,
        INDEX_NAME: SearchStack.INDEX_NAME,
        VECTOR_DIM: String(SearchStack.VECTOR_DIM),
      },
      logGroup: new logs.LogGroup(this, 'IndexInitLogs', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });
    this.domain.grantReadWrite(indexInit);

    // Promena `schemaVersion` tera CloudFormation da ponovo pozove resource
    // kad se sema promeni. Kreiranje je idempotentno.
    const indexInitResource = new cdk.CustomResource(this, 'IndexInit', {
      serviceToken: indexInit.functionArn,
      // 2: dodati search pipeline-i za hibridnu pretragu (faza 5).
      // 3: eksperimentalni pipeline-i RRF i lex, za poredjenje oblika pretrage.
      //    Menja samo pipeline-e; mapping postojeceg indeksa se ne dira.
      properties: { schemaVersion: '3' },
    });

    // Bez ove linije CloudFormation sme da pokrene IndexInit pre nego sto se
    // access policy primeni. CDK access policy pravi zasebnim custom
    // resource-om (UpdateDomainConfig), pa domen kratko postoji bez ijedne
    // dozvole i zahtev bi se vratio kao 403. Zavisnost od `domain` pokriva i
    // taj resource, jer je on dete Domain konstrukta.
    indexInitResource.node.addDependency(this.domain);

    // Endpoint ide kroz SSM, a NE kao cross-stack referenca (props).
    //
    // Referenca bi endpoint upisala u env promenljive Lambdi u trenutku
    // deploy-a. Domen se rusi tokom pauza, a svako novo podizanje daje NOVI
    // endpoint (ime domena generise CloudFormation), pa bi posle svakog
    // podizanja morali ponovo da se deploy-uju i ingestion i query. Uz to bi
    // CDK zabelezio zavisnost, pa bi `cdk deploy RagQueryStack` bez `-e`
    // povlacio i skupi domen.
    //
    // CloudFormation brisanje ovde NE bi blokirao: `cdk.json` ima
    // `@aws-cdk/core:defaultCrossStackReferences: weak`, pa CDK umesto
    // Export/ImportValue pravi `Fn::GetStackOutput`, koji ne zakljucava izvorni
    // stack. Uz podrazumevane (strong) reference bio bi i to razlog.
    //
    // Lambde citaju ovaj parametar u vreme IZVRSAVANJA, pa izmedju stack-ova
    // nema nikakve veze ni u deploy-u ni u brisanju.
    new ssm.StringParameter(this, 'DomainEndpointParam', {
      parameterName: SearchStack.ENDPOINT_PARAM,
      stringValue: this.domain.domainEndpoint,
      description: 'Endpoint privatno hostovanog OpenSearch domena',
    });
    new ssm.StringParameter(this, 'IndexNameParam', {
      parameterName: SearchStack.INDEX_NAME_PARAM,
      stringValue: SearchStack.INDEX_NAME,
      description: 'Ime indeksa sa hibridnom semom',
    });

    new cdk.CfnOutput(this, 'DomainEndpoint', { value: this.domain.domainEndpoint });
    new cdk.CfnOutput(this, 'IndexName', { value: SearchStack.INDEX_NAME });
  }
}
