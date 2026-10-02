# NVIDIA Triton (CPU) + the python packages the bge_m3_embed python-backend
# model needs. Built by seminar/docker-compose.yml; the model repository and
# the HF weight cache are mounted, not baked in.
ARG TRITON_IMAGE=nvcr.io/nvidia/tritonserver:25.08-py3
FROM ${TRITON_IMAGE}
RUN pip install --no-cache-dir --break-system-packages \
        --index-url https://download.pytorch.org/whl/cpu "torch==2.8.*" \
 && pip install --no-cache-dir --break-system-packages \
        "transformers>=4.44,<5" "huggingface_hub>=0.24" sentencepiece
