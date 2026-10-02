import os
import json
import zipfile
from glob import glob
from pathlib import Path

from helper_funcs import check_task_status, update_flow_status, logger

FLOW_STATUS_FILE = os.environ.get("FLOW_STATUS_FILE", "flow.status")
TASK_ID = os.environ.get("TASK_ID", "04-unzip-by-datadate")
TASK_STAGES = json.loads(os.environ.get("TASK_STAGES", "[]"))


def main():
    root_timeflow_dir = os.environ["ROOT_TIMEFLOW_DIR"]
    data_date         = os.environ["DATA_DATE"]
    sftp_trigger_file = os.environ["SFTP_TRIGGER_FILE"]

    if check_task_status(root_timeflow_dir=root_timeflow_dir,
                         flow_status_file=FLOW_STATUS_FILE,
                         task_id=TASK_ID):
        logger.info(f"Task {TASK_ID} already success in flow.status, skipping.")
        return

    zip_dir    = os.path.join(root_timeflow_dir, "zip")
    audio_dir  = os.path.join(root_timeflow_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    local_trigger_file = os.path.join(zip_dir, os.path.basename(sftp_trigger_file))
    with open(local_trigger_file, "r") as f:
        lines = f.read().split("\n")
    zip_files = [os.path.join(zip_dir, line.strip()) for line in lines if line.strip()]

    for zip_file in zip_files:
        before = set(glob(f"{audio_dir}/*.wav"))
        with zipfile.ZipFile(zip_file, "r") as zf:
            # Safe extraction to prevent path traversal (Zip Slip vulnerability)
            dest_path = Path(audio_dir).resolve()
            for member in zf.infolist():
                target_path = (dest_path / member.filename).resolve()
                if not str(target_path).startswith(str(dest_path)):
                    raise Exception(f"Attempted Path Traversal in Zip File: {member.filename}")
            zf.extractall(dest_path)
        after = set(glob(f"{audio_dir}/*.wav"))
        logger.info(f"Extracted {zip_file}: +{len(after - before)} new WAV files")

    all_audio_names = [os.path.basename(f) for f in glob(f"{audio_dir}/*.wav")]
    logger.info(f"Total audio files after extraction: {len(all_audio_names)}")

    audios_completed_file = os.path.join(audio_dir, f"{data_date}.completed")
    with open(audios_completed_file, "w") as f:
        f.write("\n".join(all_audio_names))
    logger.info(f"Written completed file: {audios_completed_file}")

    update_flow_status(root_timeflow_dir=root_timeflow_dir,
                       flow_status_file=FLOW_STATUS_FILE,
                       task_id=TASK_ID,
                       task_stages=TASK_STAGES)


if __name__ == "__main__":
    main()