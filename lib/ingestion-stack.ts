import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

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
 * i paralelizam (Map state). Pet Lambdi, ne deset-petnaest: granularnost prati
 * prirodnu podelu posla (CPU-bound ekstrakcija / GPU-pozivajuci koraci /
 * I/O-bound indeksiranje).
 *
 * TODO (faza 4):
 *   1. ExtractAndPrepare  — PyMuPDF/python-docx, chunking 512/50,
 *                           serijalizacija tabela u Markdown (bez VLM poziva)
 *   2. Map state          — tip=="image" -> CaptionChunk (VLM), inace prosledi
 *   3. EmbedChunks        — BATCH poziv bge-m3, ne po chunk-u
 *   4. IndexChunks        — bulk indeksiranje u OpenSearch
 *   5. FinalizeIngestion  — status u ingestion-log
 */
export class IngestionStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: IngestionStackProps) {
    super(scope, id, props);
    // faza 4
  }
}
