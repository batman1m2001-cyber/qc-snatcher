import os
import re
import json
import boto3

from metadata import parser_filenames
from helper_funcs import check_task_status, update_flow_status, logger


FLOW_STATUS_FILE = os.environ.get("FLOW_STATUS_FILE", "flow.status")
TASK_ID = os.environ.get("TASK_ID", "05.1-audios-to-s3")
TASK_STAGES = json.loads(os.environ.get("TASK_STAGES", "[]"))


def build_mock_metadata(audio_names: list) -> dict:
    """Build mock metadata keyed by audio filename.

    Chỉ điền các field parse được từ tên file; những trường vốn lấy từ Databricks
    (customerID, call_code, call_duration, is_chinh_chu, kqhd, tethys_*) để None.
    Cấu trúc dict giống hệt metadata.dataframe2metadata để downstream dùng ngay;
    task 05.2 (get_metadata) sẽ ghi đè bằng metadata thật khi chạy.
    """
    df_audio, parse_failures = parser_filenames(audio_names)
    if parse_failures:
        logger.warning(f"{len(parse_failures)} filenames failed to parse "
                       f"(samples: {parse_failures[:3]})")

    file2metadata = {}
    for _, row in df_audio.iterrows():
        audio_name = row["audio_name"]
        agent_match = re.match(r"E_(.+?)_D_", audio_name)
        calltraceid = row["calltraceid_from_name"]
        if not calltraceid:
            raise ValueError(f"calltraceid not found in filename {audio_name}")
        file2metadata[audio_name] = {
            "call_id": str(calltraceid),
            "customerID": None,
            "call_code": None,
            "call_date": row["answertime"] if row["answertime"] else None,
            "agent_username": agent_match.group(1) if agent_match else None,
            "file_name": audio_name,
            "phone_number": str(row["rawphone"]) if row["rawphone"] else None,
            "closed_by": row["closedby"],
            "queueid": str(row["queueid"]) if row["queueid"] else None,
            "call_duration": None,
            "ovd_days": 100,  # mock value
            "queuename": None,
            "is_chinh_chu": None,
            "kqhd": None,
            "tethys_actiondate": None,
            "tethys_time_diff_sec": None,
        }
    logger.info(f"Mock metadata prepared for {len(file2metadata)} audio files.")
    return file2metadata


def main():
    root_timeflow_dir = os.environ["ROOT_TIMEFLOW_DIR"]
    data_date         = os.environ["DATA_DATE"]
    s3_bucket         = os.environ["S3_BUCKET"]
    dest_s3_key       = os.environ["DEST_S3_KEY"]

    if check_task_status(root_timeflow_dir=root_timeflow_dir,
                         flow_status_file=FLOW_STATUS_FILE,
                         task_id=TASK_ID):
        logger.info(f"Task {TASK_ID} already success, skipping.")
        return

    audio_dir             = os.path.join(root_timeflow_dir, "audio")
    audios_completed_file = os.path.join(audio_dir, f"{data_date}.completed")

    with open(audios_completed_file) as f:
        lines = f.read().split("\n")
    audio_names = [line.strip() for line in lines if line.strip()]
    files_to_push = [os.path.join(audio_dir, name) for name in audio_names]
    files_to_push.append(audios_completed_file)

    s3 = boto3.client("s3")
    for idx, local_path in enumerate(files_to_push):
        s3_key = f"{dest_s3_key}/{os.path.basename(local_path)}"
        s3.upload_file(local_path, s3_bucket, s3_key)
        if (idx + 1) % 10 == 0 or (idx + 1) == len(files_to_push):
            logger.info(f"Uploaded {idx + 1}/{len(files_to_push)} files")

    # Mock metadata: cho phép downstream (sentiment) chạy ngay mà không phải chờ
    # 05.2-get-metadata (bị hold tới 5h sáng). Ghi cùng key với 05.2 để khi task đó
    # chạy sẽ ghi đè bằng metadata thật từ Databricks.
    mock_metadata = build_mock_metadata(audio_names)
    local_metadata_file = os.path.join(audio_dir, f"{data_date}_metadata.json")
    with open(local_metadata_file, "w") as f:
        json.dump(mock_metadata, f, indent=4, ensure_ascii=False)
    metadata_s3_key = f"{dest_s3_key}/{os.path.basename(local_metadata_file)}"
    s3.upload_file(local_metadata_file, s3_bucket, metadata_s3_key)
    logger.info(f"Uploaded mock metadata to s3://{s3_bucket}/{metadata_s3_key}")

    update_flow_status(root_timeflow_dir=root_timeflow_dir,
                       flow_status_file=FLOW_STATUS_FILE,
                       task_id=TASK_ID,
                       task_stages=TASK_STAGES)
    logger.info(f"audios_to_s3 completed. Total: {len(files_to_push)} files.")

if __name__ == "__main__":
    main()