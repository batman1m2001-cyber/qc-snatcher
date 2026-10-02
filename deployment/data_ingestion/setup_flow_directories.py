import os
import json
import shutil

from helper_funcs import init_flow_status, update_flow_status, logger



FLOW_STATUS_FILE = os.environ.get("FLOW_STATUS_FILE", "flow.status")
TASK_ID = os.environ.get("TASK_ID", "01-setup-flow-directories")
TASK_STAGES = json.loads(os.environ.get("TASK_STAGES", "[]"))
TASK_ORDER = [task for stage in TASK_STAGES for task in stage]


def main():
    root_timeflow_dir = os.environ["ROOT_TIMEFLOW_DIR"]
    run_mode          = os.environ["RUN_MODE"]
    sftp_trigger_file = os.environ["SFTP_TRIGGER_FILE"]
    data_date         = os.environ["DATA_DATE"]
    ca_data_ingest_time = os.environ["CA_DATA_INGEST_TIME"]

    if run_mode == "fresh":
        if os.path.exists(root_timeflow_dir):
            shutil.rmtree(root_timeflow_dir, ignore_errors=True)
            logger.info(f"Deleted existing folder for fresh run: {root_timeflow_dir}")

    os.makedirs(root_timeflow_dir, exist_ok=True)

    flow_status_path = os.path.join(root_timeflow_dir, FLOW_STATUS_FILE)
    if os.path.exists(flow_status_path):
        logger.info(f"Flow status file already exists: {flow_status_path}")
    else:
        init_flow_status(
            root_timeflow_dir=root_timeflow_dir,
            flow_id=f"flow_{ca_data_ingest_time}",
            data_date=data_date,
            sftp_trigger_file=sftp_trigger_file,
            flow_status_file=FLOW_STATUS_FILE,
            task_stages=TASK_STAGES,
            task_order=TASK_ORDER,
        )

    update_flow_status(
        root_timeflow_dir=root_timeflow_dir,
        task_id=TASK_ID,
        flow_status_file=FLOW_STATUS_FILE,
        task_stages=TASK_STAGES,
    )
    logger.info(f"Setup flow directories completed: {root_timeflow_dir}")


if __name__ == "__main__":
    main()