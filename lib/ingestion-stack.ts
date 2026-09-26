import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { PythonFunction, PythonLayerVersion } from '@aws-cdk/aws-lambda-python-alpha';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import { Construct } from 'constructs';
import { SearchStack } from './search-stack';
import { StorageStack } from './storage-stack';

export interface IngestionStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly lambdaSg: ec2.ISecurityGroup;
  readonly dataBucket: s3.IBucket;
  readonly ingestionLogTable: dynamodb.ITable;
  readonly inferenceTagName: string;
}

/**
 * Control plane — orkestracija obrade dokumenata.
 *
 * Step Functions je opravdan jer tok stvarno ima grananje (tekst/tabela/slika)
 * i paralelizam. Pet Lambdi, ne deset-petnaest: granularnost prati prirodnu
 * podelu posla (CPU-bound ekstrakcija / GPU-pozivajuci koraci / I/O-bound
 * indeksiranje).
 *
 * NEMA cross-stack reference ka `search-stack`-u. Endpoint domena se cita iz
 * SSM-a u vreme izvrsavanja, da `cdk destroy RagSearchStack` ostane moguc dok
 * ovaj stack postoji.
 */
export class IngestionStack extends cdk.Stack {
  public readonly stateMachine: sfn.StateMachine;

  constructor(scope: Construct, id: string, props: IngestionStackProps) {
    super(scope, id, props);

    const lambdaRoot = path.join(__dirname, '..', 'lambda');

    // Deljeni klijent ka inference sloju. Layer, a ne kopija u svakom paketu:
    // tri kopije istog klijenta razisle bi se cim se promeni oblik odgovora.
    // ARM_64 (Graviton), ne x86_64.
    //
    // Razvojna masina je Apple Silicon, pa se x86 paketi grade kroz emulaciju —
    // sporo, i rizicno za pakete sa kompajliranim delovima kao PyMuPDF.
    // Provereno da PyMuPDF objavljuje `manylinux2014_aarch64` wheel, pa nema
    // gradnje iz izvora. Uz to je Graviton Lambda oko petine jeftinija.
    const ARCHITECTURE = lambda.Architecture.ARM_64;

    const commonLayer = new PythonLayerVersion(this, 'CommonLayer', {
      entry: path.join(lambdaRoot, 'common'),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_12],
      compatibleArchitectures: [ARCHITECTURE],
      description: 'Deljeni klijent ka privatno hostovanim modelima',
    });

    const commonEnv = {
      DATA_BUCKET: props.dataBucket.bucketName,
      INFERENCE_TAG_NAME: props.inferenceTagName,
    };

    /** Lambde su u VPC-u zbog SG-to-SG pristupa ka vLLM-u. */
    const vpcConfig = {
      vpc: props.vpc,
      securityGroups: [props.lambdaSg],
      // Svesna odluka: nema NAT-a, izlaz ide preko gateway endpointa za S3 i
      // DynamoDB. Bez ove zastavice CDK odbija synth.
      allowPublicSubnet: true,
    };

    const makeFunction = (
      id: string,
      entry: string,
      timeout: cdk.Duration,
      memory: number,
      env: Record<string, string> = {},
    ) =>
      new PythonFunction(this, id, {
        entry: path.join(lambdaRoot, entry),
        runtime: lambda.Runtime.PYTHON_3_12,
        architecture: ARCHITECTURE,
        index: 'handler.py',
        handler: 'handler',
        timeout,
        memorySize: memory,
        layers: [commonLayer],
        environment: { ...commonEnv, ...env },
        ...vpcConfig,
        logGroup: new logs.LogGroup(this, `${id}Logs`, {
          retention: logs.RetentionDays.TWO_WEEKS,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      });

    // Ekstrakcija je CPU-bound i jedina trazi eksterne pakete (PyMuPDF,
    // python-docx), pa je i jedina kojoj treba Docker build. Vise memorije
    // znaci i vise CPU-a u Lambdi, sto skracuje parsiranje PDF-a.
    const extractFn = makeFunction('ExtractAndPrepare', 'extract_and_prepare',
      cdk.Duration.minutes(10), 2048);

    // Ceka VLM: dva poziva po slici, svaki do par desetina sekundi.
    const captionFn = makeFunction('CaptionChunk', 'caption_chunk',
      cdk.Duration.minutes(5), 512);

    // Ceka embedding servis; batch od 32 chunka po pozivu.
    const embedFn = makeFunction('EmbedChunks', 'embed_chunks',
      cdk.Duration.minutes(10), 1024);

    const indexFn = makeFunction('IndexChunks', 'index_chunks',
      cdk.Duration.minutes(10), 1024, {
        OPENSEARCH_ENDPOINT_PARAM: SearchStack.ENDPOINT_PARAM,
        INDEX_NAME_PARAM: SearchStack.INDEX_NAME_PARAM,
      });

    const finalizeFn = makeFunction('FinalizeIngestion', 'finalize_ingestion',
      cdk.Duration.minutes(1), 256, {
        INGESTION_LOG_TABLE: props.ingestionLogTable.tableName,
      });

    // --- dozvole ---------------------------------------------------------
    props.dataBucket.grantReadWrite(extractFn);
    props.dataBucket.grantRead(captionFn);
    props.dataBucket.grantReadWrite(embedFn);
    props.dataBucket.grantRead(indexFn);
    props.ingestionLogTable.grantWriteData(finalizeFn);

    // Pronalazenje GPU instance po tagu — umesto ALB-a. DescribeInstances ne
    // podrzava ogranicenje po resursu, pa je `*` jedina opcija; akcija je
    // read-only i ne otkriva podatke iz dokumenata.
    for (const fn of [captionFn, embedFn]) {
      fn.addToRolePolicy(new iam.PolicyStatement({
        actions: ['ec2:DescribeInstances'],
        resources: ['*'],
      }));
    }

    indexFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameter'],
      resources: [
        cdk.Arn.format({ service: 'ssm', resource: 'parameter', resourceName: 'rag/opensearch/*' }, this),
      ],
    }));
    // Domen je u VPC-u i iza SG-a; `es:ESHttp*` je uz to vezano za IAM identitet.
    indexFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['es:ESHttpPost', 'es:ESHttpPut'],
      resources: [cdk.Arn.format({ service: 'es', resource: 'domain', resourceName: '*' }, this)],
    }));

    // --- tok -------------------------------------------------------------
    const extractTask = new tasks.LambdaInvoke(this, 'Ekstrakcija', {
      lambdaFunction: extractFn,
      payloadResponseOnly: true,
    });

    // Grananje po tipu chunka. Tabele su vec deterministicki serijalizovane u
    // Markdown, pa bi VLM poziv nad njima bio trosak GPU vremena za losiji
    // rezultat. Zato samo slike idu na captioning.
    const captionTask = new tasks.LambdaInvoke(this, 'CaptionSlike', {
      lambdaFunction: captionFn,
      payloadResponseOnly: true,
    });
    const passThrough = new sfn.Pass(this, 'ProslediBezIzmene');

    const perChunk = new sfn.Choice(this, 'JeLiSlika')
      .when(sfn.Condition.stringEquals('$.chunk_type', 'image'), captionTask)
      .otherwise(passThrough);

    // DistributedMap, ne obicni Map: lista chunkova se cita IZ S3, pa ne
    // prolazi kroz stanje. Obicni Map bi je nosio u payload-u i probio tvrd
    // limit Step Functions-a od 256KB na prvom ozbiljnijem dokumentu.
    const mapChunks = new sfn.DistributedMap(this, 'ObradiChunkove', {
      itemReader: new sfn.S3JsonItemReader({
        bucket: props.dataBucket,
        key: sfn.JsonPath.stringAt('$.chunksKey'),
      }),
      resultWriterV2: new sfn.ResultWriterV2({
        bucket: props.dataBucket,
        prefix: 'manifests/captioned/',
      }),
      // Jedna GPU instanca servira captioning. Preveliki paralelizam bi samo
      // pravio red na vLLM-u i rizikovao timeout Lambdi.
      maxConcurrency: 4,
      resultPath: '$.mapResult',
    });
    mapChunks.itemProcessor(perChunk);

    const embedTask = new tasks.LambdaInvoke(this, 'Vektorizacija', {
      lambdaFunction: embedFn,
      payloadResponseOnly: true,
      payload: sfn.TaskInput.fromObject({
        documentId: sfn.JsonPath.stringAt('$.documentId'),
        bucket: sfn.JsonPath.stringAt('$.bucket'),
        chunksKey: sfn.JsonPath.stringAt('$.chunksKey'),
        captionedKey: sfn.JsonPath.stringAt('$.mapResult.ResultWriterDetails.Key'),
      }),
      resultPath: '$.embedResult',
    });

    const indexTask = new tasks.LambdaInvoke(this, 'Indeksiranje', {
      lambdaFunction: indexFn,
      payloadResponseOnly: true,
      payload: sfn.TaskInput.fromObject({
        documentId: sfn.JsonPath.stringAt('$.documentId'),
        bucket: sfn.JsonPath.stringAt('$.bucket'),
        embeddedKey: sfn.JsonPath.stringAt('$.embedResult.embeddedKey'),
      }),
      resultPath: '$.indexResult',
    });

    const finalizeTask = new tasks.LambdaInvoke(this, 'Zavrsetak', {
      lambdaFunction: finalizeFn,
      payloadResponseOnly: true,
      payload: sfn.TaskInput.fromObject({
        documentId: sfn.JsonPath.stringAt('$.documentId'),
        sourceUri: sfn.JsonPath.stringAt('$.sourceUri'),
        total: sfn.JsonPath.numberAt('$.total'),
        counts: sfn.JsonPath.objectAt('$.counts'),
        indexed: sfn.JsonPath.numberAt('$.indexResult.indexed'),
        skipped: sfn.JsonPath.numberAt('$.embedResult.skipped'),
      }),
    });

    // Ponovni pokusaj kad Lambda odbije poziv zbog konkurentnosti. Nalog ima
    // limit od 10 istovremenih Lambdi (provereno 2026-09-26), a osam
    // dokumenata ubacenih odjednom, svaki sa Map-om od cetiri paralelna
    // captiona, ga probija — dva toka su pala sa 429 ("Rate Exceeded").
    // Podrazumevani retry LambdaInvoke-a ovu gresku NE pokriva. Jitter
    // rasipa ponovne pokusaje, da se svi ne vrate u istoj sekundi.
    for (const task of [extractTask, captionTask, embedTask, indexTask, finalizeTask]) {
      task.addRetry({
        errors: ['Lambda.TooManyRequestsException'],
        interval: cdk.Duration.seconds(2),
        backoffRate: 2,
        maxAttempts: 6,
        jitterStrategy: sfn.JitterType.FULL,
      });
    }

    this.stateMachine = new sfn.StateMachine(this, 'IngestionStateMachine', {
      definitionBody: sfn.DefinitionBody.fromChainable(
        extractTask.next(mapChunks).next(embedTask).next(indexTask).next(finalizeTask),
      ),
      timeout: cdk.Duration.hours(2),
      tracingEnabled: true,
    });

    // DistributedMap pokrece ugnjezdena izvrsavanja i cita/pise po S3.
    props.dataBucket.grantReadWrite(this.stateMachine);

    // --- okidac ----------------------------------------------------------
    // S3 -> EventBridge -> Step Functions, filtrirano na `raw/`. Bez filtera
    // bi i manifesti i slike koje sam tok upisuje ponovo okidali ingestion,
    // u beskonacnoj petlji.
    new events.Rule(this, 'RawUploadRule', {
      description: 'Novi dokument u raw/ pokrece ingestion',
      eventPattern: {
        source: ['aws.s3'],
        detailType: ['Object Created'],
        detail: {
          bucket: { name: [props.dataBucket.bucketName] },
          object: { key: [{ prefix: StorageStack.RAW_PREFIX }] },
        },
      },
      targets: [
        new targets.SfnStateMachine(this.stateMachine, {
          input: events.RuleTargetInput.fromObject({
            bucket: events.EventField.fromPath('$.detail.bucket.name'),
            key: events.EventField.fromPath('$.detail.object.key'),
          }),
        }),
      ],
    });

    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: this.stateMachine.stateMachineArn,
    });
  }
}
