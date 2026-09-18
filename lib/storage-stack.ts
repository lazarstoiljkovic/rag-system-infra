import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface StorageStackProps extends cdk.StackProps {
  /**
   * true pre finalne evaluacije — cuva bucket i tabele od `cdk destroy`,
   * da se ne izgubi indeksirani korpus i izmereni rezultati.
   */
  readonly retainData?: boolean;
}

/**
 * Storage sloj.
 *
 * Jedan bucket sa tri prefiksa umesto tri bucket-a: odvojeni bucket-i imaju
 * smisla kada razliciti timovi imaju razlicite IAM politike, sto ovde ne
 * postoji.
 *
 *   raw/     originalni PDF/DOCX upload — okidac za ingestion
 *   images/  slike izvucene pri ekstrakciji, referencirane preko image_ref
 *   eval/    RAGAS rezultati i benchmark izvestaji
 */
export class StorageStack extends cdk.Stack {
  public readonly dataBucket: s3.Bucket;
  public readonly ingestionLogTable: dynamodb.Table;
  /** Direktan izvor podataka za RAGAS evaluaciju, ne samo debug log. */
  public readonly queryLogTable: dynamodb.Table;

  public static readonly RAW_PREFIX = 'raw/';
  public static readonly IMAGES_PREFIX = 'images/';
  public static readonly EVAL_PREFIX = 'eval/';

  constructor(scope: Construct, id: string, props: StorageStackProps = {}) {
    super(scope, id, props);

    const retain = props.retainData ?? false;
    const removalPolicy = retain
      ? cdk.RemovalPolicy.RETAIN
      : cdk.RemovalPolicy.DESTROY;

    this.dataBucket = new s3.Bucket(this, 'DataBucket', {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: false,
      eventBridgeEnabled: true, // S3 -> EventBridge -> Step Functions
      removalPolicy,
      autoDeleteObjects: !retain,
    });

    this.ingestionLogTable = new dynamodb.Table(this, 'IngestionLogTable', {
      partitionKey: { name: 'documentId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'startedAt', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });

    this.queryLogTable = new dynamodb.Table(this, 'QueryLogTable', {
      partitionKey: { name: 'queryId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy,
    });

    // Povlacenje celog benchmark runa (svi upiti jedne varijante) u jednom upitu.
    this.queryLogTable.addGlobalSecondaryIndex({
      indexName: 'byEvalRun',
      partitionKey: { name: 'evalRunId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'createdAt', type: dynamodb.AttributeType.STRING },
    });

    new cdk.CfnOutput(this, 'DataBucketName', { value: this.dataBucket.bucketName });
    new cdk.CfnOutput(this, 'QueryLogTableName', { value: this.queryLogTable.tableName });
  }
}
