#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ModelServingStack } from '../lib/model-serving-stack';
import { IngestionStack } from '../lib/ingestion-stack';
import { QueryStack } from '../lib/query-stack';
import { ObservabilityStack } from '../lib/observability-stack';

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: 'eu-central-1',
};

/**
 * Javna IP developera, za rucni curl ka portovima modela tokom razvoja.
 * Postavlja se u cdk.json (context) ili:  cdk deploy -c developerCidr=1.2.3.4/32
 * Podrazumevana vrednost namerno ne otvara nista.
 */
const developerCidr = app.node.tryGetContext('developerCidr') ?? '127.0.0.1/32';

const network = new NetworkStack(app, 'RagNetworkStack', { env, developerCidr });

const storage = new StorageStack(app, 'RagStorageStack', {
  env,
  // prebaciti na true pre finalne evaluacije
  retainData: false,
});

new ModelServingStack(app, 'RagModelServingStack', {
  env,
  vpc: network.vpc,
  inferenceSg: network.inferenceSg,
});

new IngestionStack(app, 'RagIngestionStack', {
  env,
  vpc: network.vpc,
  lambdaSg: network.lambdaSg,
  dataBucket: storage.dataBucket,
  ingestionLogTable: storage.ingestionLogTable,
  inferenceTagName: ModelServingStack.INFERENCE_TAG_NAME,
});

new QueryStack(app, 'RagQueryStack', {
  env,
  vpc: network.vpc,
  lambdaSg: network.lambdaSg,
  dataBucket: storage.dataBucket,
  queryLogTable: storage.queryLogTable,
  inferenceTagName: ModelServingStack.INFERENCE_TAG_NAME,
});

new ObservabilityStack(app, 'RagObservabilityStack', { env });

cdk.Tags.of(app).add('Project', 'privatno-hostovani-rag');
cdk.Tags.of(app).add('Purpose', 'diplomski-rad');

app.synth();
