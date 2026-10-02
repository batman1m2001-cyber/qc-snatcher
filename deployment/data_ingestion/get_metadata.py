import os
import json
import boto3
from botocore.exceptions import ClientError

from metadata import get_audio_info, databricks_query
from helper_funcs import check_task_status, update_flow_status, addmore_calltrace_infor, logger


FLOW_STATUS_FILE = os.environ.get("FLOW_STATUS_FILE", "flow.status")
TASK_ID = os.environ.get("TASK_ID", "05.2-get-metadata")
TASK_STAGES = json.loads(os.environ.get("TASK_STAGES", "[]"))

def get_secret(secretId):
    region_name = "ap-southeast-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secretId)
    except ClientError as e:
        raise e

    secret = get_secret_value_response["SecretString"]
    return secret


def main():
    
    root_timeflow_dir = os.environ["ROOT_TIMEFLOW_DIR"]
    data_date         = os.environ["DATA_DATE"]
    
    if check_task_status(root_timeflow_dir=root_timeflow_dir,
                         flow_status_file=FLOW_STATUS_FILE,
                         task_id=TASK_ID):
        logger.info(f"Task {TASK_ID} already success, skipping.")
        return

    S3_BUCKET = os.getenv("S3_BUCKET")
    S3_KEY = os.getenv("S3_KEY")
    # Get Secret values
    SECRET_ID = os.getenv("SECRET_ID")
    secrets = json.loads(get_secret(SECRET_ID))
    # Databricks Authentication details
    DATABRICKS_HOST = os.getenv("DATABRICKS_HOST")
    DATABRICKS_CLIENT_ID = secrets["databricks_client_id"]
    DATABRICKS_CLIENT_SECRET = secrets["databricks_client_secret"]
    DATABRICKS_SQL_HTTP_PATH = os.getenv("DATABRICKS_SQL_HTTP_PATH")
    # Audio files info
    AUDIOS_COMPLETED_FILE = os.getenv("AUDIOS_COMPLETED_FILE")
    QUEUEID2QUEUENAME_FILE = os.getenv("QUEUEID2QUEUENAME_FILE")
    # Get Databricks tables info
    DATABRICKS_CALLTRACE_TABLE = os.getenv("DATABRICKS_CALLTRACE_TABLE")
    DATABRICKS_CALLCODE_TABLE = os.getenv("DATABRICKS_CALLCODE_TABLE")
    DATABRICKS_TETHYS_ALLACTION_TABLE = os.getenv("DATABRICKS_TETHYS_ALLACTION_TABLE")
    DATABRICKS_TETHYS_ACTIONRESULT_TABLE = os.getenv("DATABRICKS_TETHYS_ACTIONRESULT_TABLE")
    DATABRICKS_CUSTOMER_CONTACT_TABLE = os.getenv("DATABRICKS_CUSTOMER_CONTACT_TABLE")
    
    with open(AUDIOS_COMPLETED_FILE, "r") as f:
        audio_names = f.read().split("\n")
    
    file2metadata = get_audio_info(audio_names=audio_names, 
                                   databricks_host=DATABRICKS_HOST, 
                                   databricks_client_id=DATABRICKS_CLIENT_ID, 
                                   databricks_client_secret=DATABRICKS_CLIENT_SECRET, 
                                   databricks_sql_http_path=DATABRICKS_SQL_HTTP_PATH, 
                                   databricks_calltrace_table=DATABRICKS_CALLTRACE_TABLE, 
                                   databricks_callcode_table=DATABRICKS_CALLCODE_TABLE, 
                                   databricks_tethys_allaction_table=DATABRICKS_TETHYS_ALLACTION_TABLE, 
                                   databricks_tethys_actionresult_table=DATABRICKS_TETHYS_ACTIONRESULT_TABLE, 
                                   databricks_customer_contact_table=DATABRICKS_CUSTOMER_CONTACT_TABLE, 
                                   queueid2queuename_file=QUEUEID2QUEUENAME_FILE)
    if "snapshot" in AUDIOS_COMPLETED_FILE:
        file2metadata = addmore_calltrace_infor(databricks_query=databricks_query,
                                                file2metadata=file2metadata,
                                                databricks_host=DATABRICKS_HOST,
                                                databricks_client_id=DATABRICKS_CLIENT_ID,
                                                databricks_client_secret=DATABRICKS_CLIENT_SECRET,
                                                databricks_sql_http_path=DATABRICKS_SQL_HTTP_PATH,
                                                databricks_calltrace_table=DATABRICKS_CALLTRACE_TABLE)
    local_metadata_file = AUDIOS_COMPLETED_FILE.replace(".completed", "_metadata.json")
    with open(local_metadata_file, "w") as f:
        json.dump(file2metadata, f, indent=4, ensure_ascii=False)
    s3_metadata_key = f"{S3_KEY}/{os.path.basename(local_metadata_file)}"
    s3 = boto3.client("s3")
    try:
        s3.upload_file(local_metadata_file, S3_BUCKET, s3_metadata_key)
        logger.info(f"Successfully uploaded metadata to s3://{S3_BUCKET}/{s3_metadata_key}")
    except ClientError as e:
        logger.error(f"Failed to upload metadata to s3://{S3_BUCKET}/{s3_metadata_key}: {e}")
        raise e
    
    update_flow_status(root_timeflow_dir=root_timeflow_dir,
                       flow_status_file=FLOW_STATUS_FILE,
                       task_id=TASK_ID,
                       task_stages=TASK_STAGES)
    logger.info(f"get_metadata completed. Total metadata entries: {len(file2metadata)}")

if __name__ == "__main__":
    main()