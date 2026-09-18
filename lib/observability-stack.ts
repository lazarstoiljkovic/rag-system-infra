import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface ObservabilityStackProps extends cdk.StackProps {}

/**
 * CloudWatch dashboardi. Opciono, nije prioritet — i eksplicitno BEZ
 * auto-stop automatizacije (GPU instanca se gasi rucno).
 *
 * TODO (faza 6, ako ostane vremena).
 */
export class ObservabilityStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ObservabilityStackProps = {}) {
    super(scope, id, props);
  }
}
