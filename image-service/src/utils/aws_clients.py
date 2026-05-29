import os
import boto3

LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
USE_LOCALSTACK = os.environ.get("USE_LOCALSTACK", "false").lower() == "true"

S3_BUCKET = os.environ.get("S3_BUCKET", "image-service-bucket")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "image-service-metadata")


def _kwargs():
    if USE_LOCALSTACK:
        return {
            "endpoint_url": LOCALSTACK_ENDPOINT,
            "region_name": AWS_REGION,
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
        }
    return {"region_name": AWS_REGION}


def get_s3_client():
    return boto3.client("s3", **_kwargs())


def get_dynamodb_resource():
    return boto3.resource("dynamodb", **_kwargs())
