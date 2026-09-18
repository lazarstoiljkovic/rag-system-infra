import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

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
 * empirijski doprinos rada.
 *
 * PAZNJA: API Gateway integration timeout je 29s, tvrd limit.
 *
 * TODO (faza 5): API Gateway REST (POST /query) + QueryHandler Lambda.
 */
export class QueryStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: QueryStackProps) {
    super(scope, id, props);
    // faza 5
  }
}
