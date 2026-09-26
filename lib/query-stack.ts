import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { PythonFunction, PythonLayerVersion } from '@aws-cdk/aws-lambda-python-alpha';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';
import { SearchStack } from './search-stack';
import { StorageStack } from './storage-stack';

export interface QueryStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly lambdaSg: ec2.ISecurityGroup;
  readonly dataBucket: s3.IBucket;
  readonly queryLogTable: dynamodb.ITable;
  readonly inferenceTagName: string;
}

/**
 * Query plane — sinhroni put pitanje -> odgovor.
 *
 * JEDNA Lambda, bez Step Functions: unutar jednog upita nema grananja ni
 * paralelizma, orkestracija bi bila cist overhead. Ova asimetrija u odnosu
 * na ingestion je namerna.
 *
 * Varijanta A: generator vidi samo tekst (caption umesto slike).
 * Varijanta B: uz caption se prosledjuje i originalna slika (preko image_ref).
 * Varijanta se salje kao parametar upita — to je ablacija koja nosi glavni
 * empirijski doprinos rada. Oblik pretrage (dense+BM25 ili +sparse) je drugi,
 * nezavisan parametar — sekundarni eksperiment nad retrieval-om.
 *
 * Kao i ingestion, NEMA cross-stack reference ka `search-stack`-u: endpoint i
 * ime indeksa se citaju iz SSM-a u vreme izvrsavanja, a imena pipeline-a su
 * obicne konstante. `cdk destroy RagSearchStack` ostaje moguc.
 */
export class QueryStack extends cdk.Stack {
  public readonly api: apigateway.RestApi;

  constructor(scope: Construct, id: string, props: QueryStackProps) {
    super(scope, id, props);

    const lambdaRoot = path.join(__dirname, '..', 'lambda');
    // Isto kao u ingestion-stack-u: Graviton, jer je razvojna masina Apple
    // Silicon, a Graviton je uz to jeftiniji.
    const ARCHITECTURE = lambda.Architecture.ARM_64;

    // Sopstvena kopija layer-a sa deljenim klijentom (`lambda/common`), a ne
    // referenca na onaj iz ingestion-stack-a: cross-stack zavisnost bi vezala
    // zivotne cikluse dva stack-a samo zbog jednog fajla. Izvor je isti
    // direktorijum, pa se klijenti ne mogu razici.
    const commonLayer = new PythonLayerVersion(this, 'CommonLayer', {
      entry: path.join(lambdaRoot, 'common'),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      compatibleArchitectures: [ARCHITECTURE],
      description: 'Deljeni klijent ka privatno hostovanim modelima',
    });

    const queryFn = new PythonFunction(this, 'QueryHandler', {
      entry: path.join(lambdaRoot, 'query_handler'),
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: ARCHITECTURE,
      index: 'handler.py',
      handler: 'handler',
      // 60s, a ne 29s: evaluaciona skripta zove Lambdu DIREKTNO i zaobilazi
      // limit API Gateway-a, pa sporo pitanje (npr. varijanta B sa cetiri
      // slike) i dalje dobije odgovor i zapis u query-log. Preko API-ja klijent
      // posle 29s dobije 504, ali se zapis svejedno upise.
      timeout: cdk.Duration.seconds(60),
      // Varijanta B drzi do cetiri slike u memoriji kao base64.
      memorySize: 512,
      layers: [commonLayer],
      environment: {
        DATA_BUCKET: props.dataBucket.bucketName,
        QUERY_LOG_TABLE: props.queryLogTable.tableName,
        INFERENCE_TAG_NAME: props.inferenceTagName,
        OPENSEARCH_ENDPOINT_PARAM: SearchStack.ENDPOINT_PARAM,
        INDEX_NAME_PARAM: SearchStack.INDEX_NAME_PARAM,
        PIPELINE_DENSE_BM25: SearchStack.PIPELINES.dense_bm25,
        PIPELINE_DENSE_BM25_SPARSE: SearchStack.PIPELINES.dense_bm25_sparse,
      },
      vpc: props.vpc,
      securityGroups: [props.lambdaSg],
      // Svesna odluka: nema NAT-a; EC2 i SSM API idu preko interface
      // endpointa iz search-stack-a, S3 i DynamoDB preko gateway endpointa.
      allowPublicSubnet: true,
      logGroup: new logs.LogGroup(this, 'QueryHandlerLogs', {
        retention: logs.RetentionDays.TWO_WEEKS,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    // --- dozvole ---------------------------------------------------------
    // Samo slike: varijanta B cita originale preko image_ref, nista drugo.
    props.dataBucket.grantRead(queryFn, `${StorageStack.IMAGES_PREFIX}*`);
    props.queryLogTable.grantWriteData(queryFn);
    queryFn.addToRolePolicy(new iam.PolicyStatement({
      // DescribeInstances ne podrzava ogranicenje po resursu; akcija je read-only.
      actions: ['ec2:DescribeInstances'],
      resources: ['*'],
    }));
    queryFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameter'],
      resources: [
        cdk.Arn.format({ service: 'ssm', resource: 'parameter', resourceName: 'rag/opensearch/*' }, this),
      ],
    }));
    queryFn.addToRolePolicy(new iam.PolicyStatement({
      // `_search` je POST; nista drugo nad domenom ova Lambda ne radi.
      actions: ['es:ESHttpPost'],
      resources: [cdk.Arn.format({ service: 'es', resource: 'domain', resourceName: '*' }, this)],
    }));

    // --- API ---------------------------------------------------------------
    this.api = new apigateway.RestApi(this, 'RagQueryApi', {
      restApiName: 'rag-query-api',
      description: 'Pitanja nad tehnickom dokumentacijom (privatno hostovan RAG)',
      deployOptions: {
        stageName: 'v1',
        // Niski limiti su namerni: iza API-ja je jedna GPU instanca, a javni
        // endpoint bez limita je otvoren racun.
        throttlingRateLimit: 5,
        throttlingBurstLimit: 10,
      },
      // UI iz faze 6 je staticka S3 stranica na drugom domenu.
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: ['POST', 'OPTIONS'],
        allowHeaders: ['Content-Type', 'x-api-key'],
      },
    });

    // Integration timeout je 29s — tvrd limit API Gateway-a, i podrazumevan.
    this.api.root.addResource('query').addMethod(
      'POST',
      new apigateway.LambdaIntegration(queryFn),
      { apiKeyRequired: true },
    );

    // API kljuc, jer je endpoint javan. Nije autentikacija korisnika nego
    // brana od slucajnog i automatskog saobracaja ka GPU-u.
    const apiKey = this.api.addApiKey('RagQueryApiKey');
    const plan = this.api.addUsagePlan('RagQueryUsagePlan', {
      throttle: { rateLimit: 5, burstLimit: 10 },
      quota: { limit: 2000, period: apigateway.Period.DAY },
    });
    plan.addApiKey(apiKey);
    plan.addApiStage({ stage: this.api.deploymentStage });

    // Greske koje vraca SAM API Gateway (403 bez kljuca, 429, 504 posle 29s)
    // ne prolaze kroz Lambdu, pa nemaju CORS zaglavlje. Pregledac bi tada
    // prijavio nejasnu mreznu gresku umesto "pogresan kljuc" ili "timeout".
    for (const [id, type] of [
      ['Default4xx', apigateway.ResponseType.DEFAULT_4XX],
      ['Default5xx', apigateway.ResponseType.DEFAULT_5XX],
    ] as const) {
      this.api.addGatewayResponse(id, {
        type,
        responseHeaders: { 'Access-Control-Allow-Origin': "'*'" },
      });
    }

    // --- UI ----------------------------------------------------------------
    // Staticka stranica na S3 website hosting-u (CloudFront je svesno
    // odbacen — vidi CLAUDE.md). ZASEBAN bucket, jer website hosting trazi
    // javno citanje, a bucket sa podacima mora ostati privatan: pravilo
    // "jedan bucket sa prefiksima" vazi za podatke, ne za javnu stranicu.
    //
    // API kljuc NIJE u stranici ni u config.json-u — stranica je javna, pa bi
    // i kljuc bio. Unosi se u polje i cuva samo u pregledacu.
    const uiBucket = new s3.Bucket(this, 'UiBucket', {
      websiteIndexDocument: 'index.html',
      publicReadAccess: true,
      blockPublicAccess: new s3.BlockPublicAccess({
        blockPublicAcls: true,
        ignorePublicAcls: true,
        blockPublicPolicy: false,
        restrictPublicBuckets: false,
      }),
      // Stranica je izvedena iz repoa i ponovo se postavlja deploy-om.
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    new s3deploy.BucketDeployment(this, 'UiDeployment', {
      destinationBucket: uiBucket,
      sources: [
        s3deploy.Source.asset(path.join(__dirname, '..', 'ui')),
        // Adresa API-ja se zna tek pri deploy-u; stranica je cita pri ucitavanju.
        s3deploy.Source.jsonData('config.json', { apiUrl: `${this.api.url}query` }),
        // Primeri pitanja sa ocekivanim odgovorima, za demo.
        s3deploy.Source.data('pitanja.json', fs.readFileSync(
          path.join(__dirname, '..', 'corpus', 'demo', 'pitanja.json'), 'utf8')),
      ],
    });

    new cdk.CfnOutput(this, 'UiUrl', { value: uiBucket.bucketWebsiteUrl });
    new cdk.CfnOutput(this, 'QueryUrl', { value: `${this.api.url}query` });
    new cdk.CfnOutput(this, 'QueryFunctionName', {
      value: queryFn.functionName,
      description: 'Za direktan poziv iz evaluacione skripte (bez limita od 29s)',
    });
    new cdk.CfnOutput(this, 'ApiKeyCommand', {
      value: `aws apigateway get-api-key --api-key ${apiKey.keyId} --include-value --query value --output text`,
      description: 'Vrednost API kljuca se ne upisuje u izlaz stack-a',
    });
  }
}
