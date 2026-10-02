import os
import json
import paramiko
from time import sleep

from helper_funcs import check_task_status, update_flow_status, logger

FLOW_STATUS_FILE = os.environ.get("FLOW_STATUS_FILE", "flow.status")
TASK_ID = os.environ.get("TASK_ID", "03-download-audio-zips")
TASK_STAGES = json.loads(os.environ.get("TASK_STAGES", "[]"))


def sftp_get_file(sftp, remote_path, local_path, retry=3):
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
    root_timeflow_dir = os.environ["ROOT_TIMEFLOW_DIR"]
    sftp_trigger_file = os.environ["SFTP_TRIGGER_FILE"]
    sftp_host         = os.environ["SFTP_HOST"]
    sftp_username     = os.environ["SFTP_USERNAME"]
    sftp_password     = os.environ["SFTP_PASSWORD"]
    sftp_port         = int(os.environ.get("SFTP_PORT", "22"))

    if check_task_status(root_timeflow_dir=root_timeflow_dir,
                         flow_status_file=FLOW_STATUS_FILE,
                         task_id=TASK_ID):
        logger.info(f"Task {TASK_ID} already success in flow.status, skipping.")
        return

    # Tính local_trigger_file từ root_timeflow_dir + basename (không cần XCom từ task 02)
    zip_dir = os.path.join(root_timeflow_dir, "zip")
    local_trigger_file = os.path.join(zip_dir, os.path.basename(sftp_trigger_file))
    remote_dir = os.path.dirname(sftp_trigger_file)

    with open(local_trigger_file, "r") as f:
        lines = f.read().split("\n")
    remote_zip_files = [f"{remote_dir}/{line.strip()}" for line in lines if line.strip()]
    logger.info(f"Found {len(remote_zip_files)} ZIP files to download.")

    transport = paramiko.Transport((sftp_host, sftp_port))
    transport.connect(username=sftp_username, password=sftp_password)
    sftp = paramiko.SFTPClient.from_transport(transport)

    try:
        for remote_zip_file in remote_zip_files:
            local_zip_file = os.path.join(zip_dir, os.path.basename(remote_zip_file))
            sftp_get_file(sftp, remote_zip_file, local_zip_file)
    finally:
        sftp.close()
        transport.close()

    logger.info(f"Downloaded all {len(remote_zip_files)} ZIP files.")
    update_flow_status(root_timeflow_dir=root_timeflow_dir,
                       flow_status_file=FLOW_STATUS_FILE,
                       task_id=TASK_ID,
                       task_stages=TASK_STAGES)


if __name__ == "__main__":
    main()