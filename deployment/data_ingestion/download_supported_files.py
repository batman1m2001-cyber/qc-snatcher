import os
import json
import paramiko
from time import sleep

from helper_funcs import check_task_status, update_flow_status, logger


FLOW_STATUS_FILE = os.environ.get("FLOW_STATUS_FILE", "flow.status")
TASK_ID = os.environ.get("TASK_ID", "02-download-supported-files")
TASK_STAGES = json.loads(os.environ.get("TASK_STAGES", "[]"))


def sftp_get_file(sftp, remote_path, local_path, retry=3):
    """Download file từ SFTP server dùng paramiko, có retry và size-check."""
    try:
        sftp.stat(remote_path)
    except FileNotFoundError:
        raise Exception(f"Remote file not found: {remote_path}")

    if os.path.exists(local_path):
        local_size = os.path.getsize(local_path)
        remote_size = sftp.stat(remote_path).st_size
        if local_size == remote_size:
            logger.info(f"Already downloaded (size match), skipping: {local_path}")
            return

    for attempt in range(1, retry + 1):
        try:
            sftp.get(remote_path, local_path)
            logger.info(f"Downloaded: {remote_path} -> {local_path}")
            return
        except Exception as e:
            logger.warning(f"Attempt {attempt}/{retry} failed: {e}")
            if attempt == retry:
                raise Exception(f"Failed after {retry} attempts: {remote_path} | {e}")
            sleep(5)


def main():
    root_timeflow_dir        = os.environ["ROOT_TIMEFLOW_DIR"]
    sftp_trigger_file        = os.environ["SFTP_TRIGGER_FILE"]
    sftp_queueid2queuename_file = os.environ.get("SFTP_QUEUEID2QUEUENAME_FILE", "").strip()
    sftp_host                = os.environ["SFTP_HOST"]
    sftp_username            = os.environ["SFTP_USERNAME"]
    sftp_password            = os.environ["SFTP_PASSWORD"]
    sftp_port                = int(os.environ.get("SFTP_PORT", "22"))

    if check_task_status(root_timeflow_dir=root_timeflow_dir,
                         flow_status_file=FLOW_STATUS_FILE,
                         task_id=TASK_ID):
        logger.info(f"Task {TASK_ID} already success in flow.status, skipping.")
        return

    zip_dir = os.path.join(root_timeflow_dir, "zip")
    os.makedirs(zip_dir, exist_ok=True)

    transport = paramiko.Transport((sftp_host, sftp_port))
    transport.connect(username=sftp_username, password=sftp_password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    try:
        # Download queue mapping file
        if sftp_queueid2queuename_file:
            local_queue_file = os.path.join(root_timeflow_dir, os.path.basename(sftp_queueid2queuename_file))
            sftp_get_file(sftp, sftp_queueid2queuename_file, local_queue_file)
        else:
            raise ValueError("SFTP_QUEUEID2QUEUENAME_FILE is required but not provided.")

        # Download trigger file
        local_trigger_file = os.path.join(zip_dir, os.path.basename(sftp_trigger_file))
        sftp_get_file(sftp, sftp_trigger_file, local_trigger_file)
    finally:
        sftp.close()
        transport.close()

    update_flow_status(root_timeflow_dir=root_timeflow_dir,
                       flow_status_file=FLOW_STATUS_FILE,
                       task_id=TASK_ID,
                       task_stages=TASK_STAGES)
    logger.info("download_supported_files completed.")


if __name__ == "__main__":
    main()