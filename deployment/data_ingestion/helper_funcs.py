import os
import json
import logging
from datetime import datetime, timedelta, timezone

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

def _now_vn(): return datetime.now(timezone.utc) + timedelta(hours=7)

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
    
def addmore_calltrace_infor(databricks_query: callable,
                            file2metadata: dict,
                            databricks_host: str,
                            databricks_client_id: str,
                            databricks_client_secret: str,
                            databricks_sql_http_path: str,
                            databricks_calltrace_table: str) -> dict:
    logger.info("Adding more calltrace info for SNAPSHOT with call_id...")
    call_ids = [
        meta["call_id"]
        for meta in file2metadata.values()
        if meta.get("call_id")
    ]
    if not call_ids:
        return file2metadata

    ids_str = ", ".join(f"'{cid}'" for cid in call_ids)
    query = f"""
        SELECT calltraceid, ringduration, incomingcalltime, callcode, calltype, dialerresult
        FROM {databricks_calltrace_table}
        WHERE calltraceid IN ({ids_str})
    """
    df = databricks_query(
        databricks_host=databricks_host,
        databricks_client_id=databricks_client_id,
        databricks_client_secret=databricks_client_secret,
        databricks_sql_http_path=databricks_sql_http_path,
        query=query,
    )
    df = df.astype(str)
    # calltrace_map = df.set_index("calltraceid").to_dict(orient="index")
    calltrace_map = (
        df.drop_duplicates(subset="calltraceid")
        .set_index("calltraceid")
        .to_dict(orient="index")
    )

    for filename, meta in file2metadata.items():
        call_id = meta.get("call_id")
        if call_id and call_id in calltrace_map:
            meta.update(calltrace_map[call_id])

    return file2metadata