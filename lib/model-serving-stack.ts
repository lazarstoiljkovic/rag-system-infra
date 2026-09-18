import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
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
 * TODO (faza 2): ASG + Launch Template (g5.xlarge, Deep Learning OSS Nvidia
 * Driver AMI GPU PyTorch, Ubuntu 24.04) + user-data ec2-userdata/vllm-bootstrap.sh
 * BLOKIRANO: kvota "Running On-Demand G and VT instances" = 0, zahtev PENDING.
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

  constructor(scope: Construct, id: string, props: ModelServingStackProps) {
    super(scope, id, props);
    // faza 2
  }
}
