from dataclasses import asdict, dataclass, replace
from itertools import product

import numpy as np
from pydantic import BaseModel, Field

from .replay import seasonal_naive


class EvolutionConfig(BaseModel):
    seed: int = Field(default=2026, ge=0, le=2**32 - 1)
    generations: int = Field(default=4, ge=1, le=8)
    validation_origins: int = Field(default=4, ge=2, le=8)


WIDTHS = (4, 8, 12, 16)
STRIDES = (1, 2, 3)
TOPOLOGIES = ("ring", "dense")
MIN_TRAIN_WINDOWS = 16
MAX_TRAIN_WINDOWS = 256


def minimum_history(context, horizon, validation_origins):
    return context + horizon - 1 + MIN_TRAIN_WINDOWS + validation_origins * horizon


@dataclass(frozen=True)
class Genome:
    width: int
    stride: int
    topology: str


def windows(values, cutoffs, context, horizon):
    history = np.stack([values[i - context:i] for i in cutoffs])
    targets = np.stack([values[i:i + horizon] for i in cutoffs])
    return history, targets


def features(history, genome, seed, center, scale):
    rng = np.random.default_rng(seed)
    inputs = rng.uniform(-0.8, 0.8, genome.width)
    bias = rng.uniform(-0.4, 0.4, genome.width)
    if genome.topology == "ring":
        recurrent = 0.75 * np.roll(np.eye(genome.width), 1, axis=1)
    else:
        recurrent = rng.normal(size=(genome.width, genome.width))
        recurrent *= 0.75 / np.linalg.norm(recurrent, ord=2)
    states = np.zeros((len(history), genome.width))
    for observation in history[:, ::-1][:, ::genome.stride][:, ::-1].T:
        states = np.tanh(((observation - center) / scale)[:, None] * inputs + states @ recurrent + bias)
    return np.column_stack((states, np.ones(len(history))))


def baseline(history, season, horizon):
    return np.asarray([seasonal_naive(row, season, horizon) for row in history])


@dataclass
class EvolvedForecaster:
    genome: Genome
    seed: int
    center: float
    scale: float
    readout: np.ndarray
    season: int

    def predict(self, history, horizon):
        history = np.asarray([history])
        states = features(history, self.genome, self.seed, self.center, self.scale)
        return (baseline(history, self.season, horizon) + self.scale * (states @ self.readout))[0].tolist()


def evolve(values, context, horizon, season, config):
    values = np.asarray(values, dtype=float)
    split = len(values) - config.validation_origins * horizon
    train_cutoffs = range(max(context, split - horizon - MAX_TRAIN_WINDOWS + 1), split - horizon + 1)
    if len(train_cutoffs) < MIN_TRAIN_WINDOWS:
        raise ValueError("At least 16 complete fitting windows are required before evolutionary validation")
    validation_cutoffs = range(split, len(values), horizon)
    train_x, train_y = windows(values, train_cutoffs, context, horizon)
    val_x, val_y = windows(values, validation_cutoffs, context, horizon)
    center = float(values[:split].mean())
    scale = max(float(values[:split].std()), 1e-6)
    residuals = (train_y - baseline(train_x, season, horizon)) / scale
    val_baseline = baseline(val_x, season, horizon)
    rng = np.random.default_rng(config.seed)
    choices = [Genome(*genes) for genes in product(WIDTHS, STRIDES, TOPOLOGIES)]
    scores, readouts, trace = {}, {}, []

    def evaluate(genome, generation):
        train_states = features(train_x, genome, config.seed, center, scale)
        val_states = features(val_x, genome, config.seed, center, scale)
        penalty = 0.1 * np.eye(train_states.shape[1])
        penalty[-1, -1] = 0
        readout = np.linalg.solve(train_states.T @ train_states + penalty, train_states.T @ residuals)
        mae = float(np.abs(val_y - (val_baseline + scale * (val_states @ readout))).mean())
        if not np.isfinite(mae):
            raise ValueError("Nonfinite evolutionary validation score")
        scores[genome], readouts[genome] = mae, readout
        trace.append({"generation": generation, "genome": asdict(genome), "validation_mae": mae})

    for i in rng.choice(len(choices), size=6, replace=False):
        evaluate(choices[i], 0)
    for generation in range(1, config.generations + 1):
        parents = sorted(scores, key=scores.get)[:2]
        for _ in range(4):
            mutations = [child for parent in parents for child in choices if child not in scores and
                         sum(a != b for a, b in zip(asdict(parent).values(), asdict(child).values())) == 1]
            if not mutations:
                break
            evaluate(mutations[rng.integers(len(mutations))], generation)

    winner = min(scores, key=scores.get)
    model = EvolvedForecaster(winner, config.seed, center, scale, readouts[winner], season)
    evidence = {"method": "elitist architecture mutation with ridge-trained recurrent reservoir readout",
                "genome": asdict(winner), "seed": config.seed, "validation_mae": scores[winner],
                "initial_population_best_mae": min(row["validation_mae"] for row in trace[:6]),
                "validation_seasonal_naive_mae": float(np.abs(val_y - val_baseline).mean()),
                "fit_windows": len(train_cutoffs), "validation_origins": len(validation_cutoffs),
                "validation_start_index": split, "search_trace": trace,
                "readout": readouts[winner].tolist(), "normalization": {"center": center, "scale": scale},
                "trainable_parameters": (winner.width + 1) * horizon}
    return model, evidence
