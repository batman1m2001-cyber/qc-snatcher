"""BGE-M3 dense embedding on CPU, as a Triton python-backend model.

TEXT (BYTES, [batch, 1]) -> sentence_embedding (FP32, [batch, 1024]).

Dense head only: the [CLS] hidden state of the last layer, L2-normalised —
what BGE-M3's own `BGEM3FlagModel(...).encode(...)["dense_vecs"]` and its
sentence-transformers config (CLS pooling + Normalize) produce. The server
tokenises and truncates at `max_length` (1024, matching the deployed
endpoint resources.yaml points at), so clients send raw text.

The weights come from the Hugging Face hub on first start and are kept in
HF_HOME (a docker volume), so a restart loads from disk.
"""
import json
import os

import numpy as np
import torch
import triton_python_backend_utils as pb_utils
from huggingface_hub import snapshot_download
from transformers import AutoModel, AutoTokenizer

# Only what the dense head needs: skips the 2 GB onnx/ copy and the
# colbert/sparse heads that the repo also ships.
_FILES = ["config.json", "pytorch_model.bin", "sentencepiece.bpe.model",
          "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json"]


class TritonPythonModel:
    def initialize(self, args):
        cfg = json.loads(args["model_config"])
        params = {k: v["string_value"] for k, v in cfg.get("parameters", {}).items()}
        name = params.get("hf_model", "BAAI/bge-m3")
        self.max_length = int(params.get("max_length", "1024"))
        torch.set_num_threads(int(os.environ.get("EMBED_THREADS", "6")))
        path = snapshot_download(name, allow_patterns=_FILES)
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModel.from_pretrained(path, torch_dtype=torch.float32).eval()
        pb_utils.Logger.log_info(f"bge_m3_embed: loaded {name} from {path} on CPU, "
                                 f"max_length={self.max_length}, threads={torch.get_num_threads()}")

    @torch.inference_mode()
    def _embed(self, texts):
        enc = self.tokenizer(texts, padding=True, truncation=True,
                             max_length=self.max_length, return_tensors="pt")
        cls = self.model(**enc).last_hidden_state[:, 0]
        return torch.nn.functional.normalize(cls, p=2, dim=-1).numpy().astype(np.float32)

    def execute(self, requests):
        # Dynamic batching hands several requests over at once: embed them
        # as one padded batch, then split the rows back out.
        texts, sizes = [], []
        for req in requests:
            arr = pb_utils.get_input_tensor_by_name(req, "TEXT").as_numpy().reshape(-1)
            batch = [t.decode("utf-8") if isinstance(t, bytes) else str(t) for t in arr]
            texts.extend(batch)
            sizes.append(len(batch))
        vecs = self._embed(texts) if texts else np.zeros((0, 1024), np.float32)
        out, i = [], 0
        for n in sizes:
            tensor = pb_utils.Tensor("sentence_embedding", vecs[i:i + n])
            out.append(pb_utils.InferenceResponse(output_tensors=[tensor]))
            i += n
        return out
