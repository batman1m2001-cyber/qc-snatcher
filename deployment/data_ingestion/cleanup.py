import os
import json
import shutil
from glob import glob
from datetime import datetime, timezone

from helper_funcs import update_flow_status, logger


MOUNT_PATH = os.environ.get("MOUNT_PATH", "/mnt/data")
FLOW_STATUS_FILE = os.environ.get("FLOW_STATUS_FILE", "flow.status")
TASK_ID = os.environ.get("TASK_ID", "07-cleanup")
TASK_STAGES = json.loads(os.environ.get("TASK_STAGES", "[]"))

def main():
    root_timeflow_dir = os.environ["ROOT_TIMEFLOW_DIR"]
    now = datetime.now(tz=timezone.utc)

    all_status_files = glob(f"{MOUNT_PATH}/**/{FLOW_STATUS_FILE}", recursive=True)
    for status_file in all_status_files:
        flow_dir = os.path.dirname(status_file)
        try:
            with open(status_file) as f:
                status = json.load(f)
            ttl_dt = datetime.fromisoformat(status.get("ttl"))
            if now > ttl_dt:
                shutil.rmtree(flow_dir)
                logger.info(f"Cleaned up expired flow: {flow_dir}")
        except Exception as e:
            logger.warning(f"Skipping {status_file}: {e}")

    # Nếu current flow chưa bị xóa (TTL chưa hết) thì update status
    if os.path.exists(os.path.join(root_timeflow_dir, FLOW_STATUS_FILE)):
        update_flow_status(root_timeflow_dir=root_timeflow_dir,
                           flow_status_file=FLOW_STATUS_FILE,
                           task_id=TASK_ID,
                           task_stages=TASK_STAGES)

    logger.info("Cleanup completed.")

if __name__ == "__main__":
    main()