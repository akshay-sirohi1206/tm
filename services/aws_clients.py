import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("BharatBot.aws")

AWS_REGION       = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
S3_BUCKET        = os.getenv("S3_BUCKET_NAME", "aether-dev-data")
S3_PREFIX        = "sfl-practice/tm-audio"
BEDROCK_KB_ID    = os.getenv("BEDROCK_KB_ID", "")

import boto3

_boto_kwargs: dict = dict(region_name=AWS_REGION)
if os.getenv("AWS_ACCESS_KEY_ID"):
    _boto_kwargs["aws_access_key_id"]     = os.getenv("AWS_ACCESS_KEY_ID")
    _boto_kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY")
if os.getenv("AWS_SESSION_TOKEN"):
    _boto_kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")

bedrock       = boto3.client("bedrock-runtime",       **_boto_kwargs)
bedrock_agent = boto3.client("bedrock-agent-runtime", **_boto_kwargs)
translate     = boto3.client("translate",             **_boto_kwargs)
transcribe    = boto3.client("transcribe",            **_boto_kwargs)
polly         = boto3.client("polly",                 **_boto_kwargs)
s3            = boto3.client("s3",                    **_boto_kwargs)
comprehend    = boto3.client("comprehend",            **_boto_kwargs)
