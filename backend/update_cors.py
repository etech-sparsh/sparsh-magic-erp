import sys
sys.path.insert(0, '.')
import boto3
from app.config.settings import settings

def update_s3_cors():
    s3 = boto3.client(
        's3', 
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID, 
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY, 
        region_name=settings.AWS_REGION
    )
    
    bucket_name = settings.S3_BUCKET_NAME
    
    cors_configuration = {
        'CORSRules': [{
            'AllowedHeaders': ['*'],
            'AllowedMethods': ['GET', 'HEAD', 'PUT', 'POST', 'DELETE'],
            'AllowedOrigins': ['*'],
            'ExposeHeaders': ['ETag']
        }]
    }
    
    try:
        s3.put_bucket_cors(Bucket=bucket_name, CORSConfiguration=cors_configuration)
        print(f"Successfully updated CORS for {bucket_name}")
    except Exception as e:
        print(f"Error updating CORS: {e}")

if __name__ == "__main__":
    update_s3_cors()
