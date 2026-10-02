import argparse
import os
import sys
import json
import shutil
import boto3
import subprocess
from glob import glob
from dotenv import load_dotenv

# import settings 
from settings import NO_WORKERS, S3_SENTIMENT_OUTPUT_KEY, WORKER_ID, S3_BUCKET, S3_METADATA_KEY, DATA_DATE
from helper_funcs import logger
load_dotenv()
S3_CLIENT = boto3.client("s3")



def _parse_args():
    p = argparse.ArgumentParser(description="Score one worker's shard of a sentiment batch.")
    p.add_argument("--ingest", action="store_true",
                   help="Forward --ingest to main.py so it seeds the corpus store from "
                        "corpus.yaml when the store is empty or holds a different corpus.")
    return p.parse_args()


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_bool(key: str, default: bool) -> bool:
    return _env(key, str(default)).lower() in ("true", "1", "yes")


def _env_int(key: str, default: int) -> int:
    return int(_env(key, str(default)))


def s3_download_file(bucket_name, s3_key, local_path):
    # s3_client = boto3.client("s3")
    # local_path = f"{local_dir}/{s3_key.split('/')[-1]}"
    S3_CLIENT.download_file(bucket_name, s3_key, local_path)
    # return local_path

def s3_upload_file(bucket_name, s3_key, local_path):
    # s3_client = boto3.client("s3")
    S3_CLIENT.upload_file(local_path, bucket_name, s3_key)

def download_input_from_s3(bucket_name: str,
                           s3_metadata_key: str,
                           local_dir: str,
                           no_workers: int,
                           worker_id: int):
    logger.info(f"Downloading input from S3 for worker {worker_id} from S3 key {s3_metadata_key} to local dir {local_dir}")    
    # Download metadata file from S3
    s3_dir = os.path.dirname(s3_metadata_key)
    local_metadata_path = f"{local_dir}/metadata.json"
    s3_download_file(bucket_name, s3_metadata_key, local_metadata_path)
    with open(local_metadata_path, "r") as f:
        metadata = json.load(f)
    # Download input files for this worker based on metadata
    to_complete = []
    if os.path.exists(f"{local_dir}/flag.completed") and _env_bool("PIPELINE_SKIP_IF_EXISTS", False):
        return None
    for idx, transcript_name in enumerate(metadata):
        if idx % no_workers != worker_id - 1:
            continue
        s3_input_key = f"{s3_dir}/{transcript_name}"
        local_input_path = f"{local_dir}/{transcript_name}"
        s3_download_file(bucket_name, s3_input_key, local_input_path)
        with open(local_input_path, "r") as f:
            transcript_data = json.load(f)
        transcript_data["metadata"].update({
            "call_code": metadata[transcript_name]["call_code"],
            "closed_by": metadata[transcript_name]["closed_by"],
            "is_chinh_chu": metadata[transcript_name]["is_chinh_chu"],
            "queueid": metadata[transcript_name]["queueid"]
        })
        with open(local_input_path, "w") as f:
            json.dump(transcript_data, f, indent=2, ensure_ascii=False)
        to_complete.append(transcript_name)
    with open(f"{local_dir}/flag.completed", "w") as f:
        f.write("\n".join(to_complete))
    return None

def sentiment_mix_metadata(metadata_path: str, sentiment_output_dir: str):
    """ Mixing sentiment output with metadata

    Args:
        metadata_path (str): Path to the metadata file
        sentiment_output_dir (str): Directory containing sentiment output files

    Returns:
        str: Path to the merged sentiment output file
    """
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    result = {"data": []}
    for json_file in glob(f"{sentiment_output_dir}/*.json"):
        file_name = os.path.basename(json_file)
        if not file_name in metadata:
            logger.warning(f"Audio file {file_name} not found in metadata, skipping.")
            continue
        # qc_score_total_offset = 100
        with open(json_file, "r") as f:
            data = json.load(f)
        #     for item_key in data:
        #         for element in data[item_key]:
        #             qc_score_total_offset += element.get("Score_offset", 0)
        # qc_score_total_offset = max(0, min(100, qc_score_total_offset))
        # audio_name = os.path.basename(json_file).replace(".json", ".wav")
        qc_score_total_offset = data.get("qc_score_total_offset", 0)
        if metadata[file_name]["call_id"] is None:
            logger.warning(f"Call ID is missing for transcript {file_name}, skipping.")
            continue
        summary_sample = {"ovd_days": int(metadata[file_name]["ovd_days"]),
                        "file_name": str(metadata[file_name]["file_name"])[:225] if metadata[file_name]["file_name"] else None,
                        "call_id": str(metadata[file_name]["call_id"])[:50] if metadata[file_name]["call_id"] else "1",
                        "customerID": str(metadata[file_name]["customerID"])[:50] if metadata[file_name]["customerID"] else None,
                        "call_code": str(metadata[file_name]["call_code"])[:50] if metadata[file_name]["call_code"] else None,
                        "call_date": metadata[file_name]["call_date"],
                        "agent_username": str(metadata[file_name]["agent_username"])[:100] if metadata[file_name]["agent_username"] else None,
                        "phone_number": str(metadata[file_name]["phone_number"])[:15] if metadata[file_name]["phone_number"] else None,
                        "closed_by": str(metadata[file_name]["closed_by"])[:10] if metadata[file_name]["closed_by"] else None,
                        "queue_id": str(metadata[file_name]["queueid"])[:5] if metadata[file_name]["queueid"] else None,
                        "queue_name": str(metadata[file_name]["queuename"])[:50] if metadata[file_name]["queuename"] else None,
                        "call_duration": str(metadata[file_name]["call_duration"])[:20] if metadata[file_name]["call_duration"] else "00:00",
                        "qc_score_total_offset": int(qc_score_total_offset),
                        "call_scoring": data}
        result["data"].append(summary_sample)
    merged_output_path = f"{sentiment_output_dir}/merged_sentiment_output.json"
    with open(merged_output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return merged_output_path
    

def upload_output_to_s3(bucket_name: str,
                        local_output_dir: str,
                        s3_output_dir: str,
                        worker_id: int):
    local_path =  f"{local_output_dir}/merged_sentiment_output.json"
    s3_key = f"{s3_output_dir}/merged_sentiment_output_worker_{worker_id}.json"
    s3_upload_file(bucket_name, s3_key, local_path)
    # for filename in os.listdir(local_output_dir):
    #     local_path = f"{local_output_dir}/{filename}"
    #     s3_key = f"{s3_output_dir}/{filename}"
    #     s3_upload_file(bucket_name, s3_key, local_path)
        
def main(ingest: bool = False):
    # No banner here: main.py prints which model serves each stage, read
    # from models.yaml. No model download either — nothing runs locally.
    # import ipdb; ipdb.set_trace()
    data_dir = f"/data/sentiment/{DATA_DATE}/sentiment_inference/input_{WORKER_ID}"
    if os.path.exists(data_dir) and not _env_bool("PIPELINE_SKIP_IF_EXISTS", False):
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    
    download_input_from_s3(S3_BUCKET, S3_METADATA_KEY, data_dir, NO_WORKERS, WORKER_ID)
    output_dir = f"/data/sentiment/{DATA_DATE}/sentiment_inference/output_{WORKER_ID}"
    if os.path.exists(output_dir) and not _env_bool("PIPELINE_SKIP_IF_EXISTS", False):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Export the env vars main.py reads for input/output, then run main.py as a
    # subprocess. main.py owns the scoring run (selfcheck + pipeline.run) and
    # reads PIPELINE_INPUT_PATH / PIPELINE_OUTPUT_PATH from the environment.
    env = os.environ.copy()
    env["PIPELINE_INPUT_PATH"] = data_dir
    env["PIPELINE_OUTPUT_PATH"] = output_dir
    command = [sys.executable, "main.py"]
    if ingest:
        command.append("--ingest")
    subprocess.run(command, env=env, check=True)

    # s3_output_dir = f"sentiment/output/worker_{WORKER_ID}"
    merged_output_path = sentiment_mix_metadata(metadata_path=f"{data_dir}/metadata.json",
                                                sentiment_output_dir=output_dir)
    upload_output_to_s3(S3_BUCKET, output_dir, S3_SENTIMENT_OUTPUT_KEY, WORKER_ID)

if __name__ == "__main__":

    main(ingest=_parse_args().ingest)