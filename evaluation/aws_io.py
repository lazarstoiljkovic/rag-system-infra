"""
Jedini modul u `evaluation/` koji zna za AWS.

Adrese resursa se citaju iz izlaza stack-ova, a ne upisuju u kod: repo je
javan, a imena resursa sadrze nasumicne sufikse koje CloudFormation dodeli.
Nalog se bira profilom (AWS_PROFILE=lazar-private), kao i za CDK.
"""

import base64
import json
import os
from decimal import Decimal
from typing import Any, Dict, List

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

REGION = "eu-central-1"

_session = boto3.Session(region_name=REGION)


def stack_outputs(stack_name: str) -> Dict[str, str]:
    cfn = _session.client("cloudformation")
    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def invoke_query(function_name: str, request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Direktan poziv QueryHandler-a, mimo API Gateway-a (bez limita od 29 s).
    Vraca telo HTTP odgovora koje Lambda pravi, plus statusni kod.
    """
    # Lambda ima 60 s; citanje mora cekati duze od toga. Bez ponavljanja:
    # ponovljen poziv bi napravio drugi zapis u query-log-u za isto pitanje.
    client = _session.client("lambda", config=Config(
        read_timeout=90, connect_timeout=10, retries={"max_attempts": 0}))
    response = client.invoke(FunctionName=function_name,
                             Payload=json.dumps(request).encode("utf-8"))
    payload = json.loads(response["Payload"].read())
    if "FunctionError" in response:
        return {"statusCode": 500, "error": payload.get("errorMessage", str(payload))}
    body = json.loads(payload.get("body") or "{}")
    body["statusCode"] = payload.get("statusCode")
    return body


def _plain(value: Any) -> Any:
    """DynamoDB vraca Decimal; za JSON i racun treba float/int."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def query_log_items(table_name: str, eval_run_id: str) -> List[Dict[str, Any]]:
    """Svi zapisi jednog evaluacionog prolaza, preko GSI-ja `byEvalRun`."""
    table = _session.resource("dynamodb").Table(table_name)
    items: List[Dict[str, Any]] = []
    kwargs = {"IndexName": "byEvalRun",
              "KeyConditionExpression": Key("evalRunId").eq(eval_run_id)}
    while True:
        page = table.query(**kwargs)
        items.extend(_plain(i) for i in page["Items"])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


_CONTENT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                  "gif": "image/gif", "webp": "image/webp"}


def image_data_uri(bucket: str, key: str, cache_dir: str) -> str:
    """
    Originalna slika kao data URI, za sudiju koji vidi slike.
    Kesira se lokalno, da ponovljeno ocenjivanje ne cita S3 iznova.
    """
    local = os.path.join(cache_dir, key.replace("/", "__"))
    if not os.path.exists(local):
        os.makedirs(cache_dir, exist_ok=True)
        data = _session.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        with open(local, "wb") as f:
            f.write(data)
    with open(local, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    mime = _CONTENT_TYPES.get(key.rsplit(".", 1)[-1].lower(), "image/png")
    return "data:{};base64,{}".format(mime, encoded)
