import os
import json
import boto3
import logging
import paramiko
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
s3_client = boto3.client("s3")

def _now_vn(): return datetime.now(timezone.utc) + timedelta(hours=7)

def s3_download_file(bucket_name: str, s3_key: str, local_path: str):
    """_summary_

    Args:
        bucket_name (str): _description_
        s3_key (str): _description_
        local_path (str): _description_
    """
    s3_client.download_file(bucket_name, s3_key, local_path)
    logger.info(f"Downloaded file from S3: s3://{bucket_name}/{s3_key} to {local_path}")

def sftp_upload_file(local_path: str,
                     remote_path: str,
                     host: str,
                     port: int,
                     username: str,
                     password: str):
    transport = paramiko.Transport((host, port))
    transport.connect(username=username, password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    sftp.put(local_path, remote_path)
    sftp.close()
    transport.close()
    logger.info(f"Uploaded file to SFTP: {local_path} to {remote_path} on {host}:{port}")

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

def init_flow_status(root_timeflow_dir, flow_id, flow_status_file, task_stages, task_order, data_date, sftp_trigger_file, ttl_days=2):
    now = _now_vn()
    status = {
        "flow_id": flow_id,
        "sftp_trigger_file": sftp_trigger_file,
        "data_date": data_date,
        "created_at": now.isoformat(),
        "ttl": (now + timedelta(days=ttl_days)).isoformat(),
        "tasks": {task: "pending" for task in task_order},
        "current_stage": 0,
        "current_tasks": task_stages[0],
        "updated_at": now.isoformat(),
    }
    status["tasks"][task_order[0]] = "success"
    path = os.path.join(root_timeflow_dir, flow_status_file)
    with open(path, "w") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
    logger.info(f"Initialized flow status file: {path}")

def check_task_status(root_timeflow_dir, flow_status_file, task_id):
    path = os.path.join(root_timeflow_dir, flow_status_file)
    with open(path) as f:
        status = json.load(f)
    return status["tasks"].get(task_id, "pending") == "success"


def update_flow_status(root_timeflow_dir, task_id, flow_status_file, task_stages, task_status="success"):
    path = os.path.join(root_timeflow_dir, flow_status_file)
    with open(path) as f:
        status = json.load(f)

    status["tasks"][task_id] = task_status
    status["updated_at"] = _now_vn().isoformat()

    current_stage_idx = status["current_stage"]
    current_stage_tasks = task_stages[current_stage_idx]
    all_done = all(
        status["tasks"].get(t) in ("success", "failed")
        for t in current_stage_tasks
    )
    if all_done and current_stage_idx + 1 < len(task_stages):
        status["current_stage"] = current_stage_idx + 1
        status["current_tasks"] = task_stages[current_stage_idx + 1]
    elif all_done:
        status["current_stage"] = -1
        status["current_tasks"] = []

    with open(path, "w") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
    logger.info(f"Updated flow status: task={task_id} status={task_status}")