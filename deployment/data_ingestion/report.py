import os
import json

from helper_funcs import check_task_status, update_flow_status, logger


FLOW_STATUS_FILE = os.environ.get("FLOW_STATUS_FILE", "flow.status")
TASK_ID = os.environ.get("TASK_ID", "06-report")
TASK_STAGES = json.loads(os.environ.get("TASK_STAGES", "[]"))

def main():
    root_timeflow_dir = os.environ["ROOT_TIMEFLOW_DIR"]

    if check_task_status(root_timeflow_dir=root_timeflow_dir,
                         flow_status_file=FLOW_STATUS_FILE,
                         task_id=TASK_ID):
        logger.info(f"Task {TASK_ID} already success, skipping.")
        return

    update_flow_status(root_timeflow_dir=root_timeflow_dir,
                       flow_status_file=FLOW_STATUS_FILE,
                       task_id=TASK_ID,
                       task_stages=TASK_STAGES)
    logger.info("Data Ingestion DAG completed successfully.")

if __name__ == "__main__":
    main()