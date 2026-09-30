import uuid
from functools import cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from config import (
    S3_ENDPOINT_URL,
    S3_ACCESS_KEY,
    S3_SECRET_KEY,
    S3_REGION,
    S3_SIGNATURE_VERSION,
    TESTCASE_BUCKET,
    SUBMISSION_BUCKET,
)


@cache
def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=Config(
            signature_version=S3_SIGNATURE_VERSION,
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )


class StorageServiceTestcases:

    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self.client = get_s3_client()

    def _generate_object_key(self, problem_id: str, filename: str):
        unique_id = uuid.uuid4().hex
        return f"problems/{problem_id}/{unique_id}-{filename}"

    def upload_bytes(self, problem_id: str, filename: str, data: bytes):

        object_key = self._generate_object_key(problem_id, filename)

        self.client.put_object(Bucket=self.bucket_name, Key=object_key, Body=data)

        return object_key

    def get_file(self, object_key: str):

        response = self.client.get_object(Bucket=self.bucket_name, Key=object_key)

        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    def file_exists(self, object_key: str):
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete_file(self, object_key: str):
        self.client.delete_object(Bucket=self.bucket_name, Key=object_key)

    def delete_problem_folder(self, problem_id: str):

        prefix = f"problems/{problem_id}/"

        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            objects = [{"Key": entry["Key"]} for entry in page.get("Contents", [])]
            if objects:
                result = self.client.delete_objects(
                    Bucket=self.bucket_name, Delete={"Objects": objects}
                )
                if result.get("Errors"):
                    raise RuntimeError("Some storage objects could not be deleted")


class StorageServiceSubmissionCode:

    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self.client = get_s3_client()

    def _generate_object_key(self, extension: str):
        unique_id = uuid.uuid4().hex
        return f"{unique_id}.{extension}"

    def upload_bytes(self, extension: str, data: bytes):

        object_key = self._generate_object_key(extension)

        self.client.put_object(Bucket=self.bucket_name, Key=object_key, Body=data)

        return object_key

    def get_file(self, object_key: str):
        response = self.client.get_object(Bucket=self.bucket_name, Key=object_key)

        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    def file_exists(self, object_key: str):
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete_file(self, object_key: str):
        self.client.delete_object(Bucket=self.bucket_name, Key=object_key)


@cache
def get_storage_testcases():
    return StorageServiceTestcases(TESTCASE_BUCKET)


@cache
def get_storage_submission_code():
    return StorageServiceSubmissionCode(SUBMISSION_BUCKET)
