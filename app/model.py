import os
from pathlib import Path
from threading import Lock

MODEL_ID = "amazon/chronos-bolt-tiny"
MODEL_REVISION = "a0e552de83495b5c28c14c71c374f3e33280b340"
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[1] / ".cache"))


class Forecaster:
    def __init__(self):
        self.pipeline = None
        self.lock = Lock()
        self.revision = None

    def predict(self, values, horizon):
        import torch
        from chronos import BaseChronosPipeline

        with self.lock:
            if self.pipeline is None:
                torch.set_num_threads(4)
                self.pipeline = BaseChronosPipeline.from_pretrained(
                    MODEL_ID, revision=MODEL_REVISION, device_map="cpu", torch_dtype=torch.float32
                )
                self.revision = MODEL_REVISION
            with torch.inference_mode():
                quantiles, mean = self.pipeline.predict_quantiles(
                    torch.tensor(values[-2048:], dtype=torch.float32),
                    prediction_length=horizon, quantile_levels=[0.1, 0.5, 0.9],
                )
            return quantiles[0].cpu().tolist(), mean[0].cpu().tolist()
