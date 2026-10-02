import sys
sys.path.insert(0, '.')
import boto3
import os
from app.config.settings import settings

s3 = boto3.client('s3', aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY, region_name=settings.AWS_REGION)

new_bucket = 'sparsh-erp-data-store-2026'

try:
    if settings.AWS_REGION == 'us-east-1':
        s3.create_bucket(Bucket=new_bucket)
    else:
        s3.create_bucket(Bucket=new_bucket, CreateBucketConfiguration={'LocationConstraint': settings.AWS_REGION})
    print('Bucket created successfully!')
except Exception as e:
    print('Error:', repr(e))
