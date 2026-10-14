"""DripLM training loop."""

import json
import math
import os
import time

import torch

from .config import DripConfig, TrainConfig
from .dataset import get_dataloader
from .model import DripLM


def get_device(config):
    if config.device == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(config.device)


def get_lr(step, config):
    if step < config.warmup_steps:
        return config.learning_rate * step / config.warmup_steps
    progress = (step - config.warmup_steps) / max(1, config.max_steps - config.warmup_steps)
    coeff = 0.5 * (1 + math.cos(math.pi * progress))
    return config.min_lr + (config.learning_rate - config.min_lr) * coeff


@torch.no_grad()
def evaluate(model, loader, device, max_batches=50):
    model.eval()
    total_loss, n = 0, 0
    for x, y in loader:
        if n >= max_batches:
            break
        x, y = x.to(device), y.to(device)
        _, loss = model(x, y)
        total_loss += loss.item()
        n += 1
    model.train()
    return total_loss / max(1, n)


def train():
    mc = DripConfig()
    tc = TrainConfig()
    device = get_device(tc)
    torch.manual_seed(tc.seed)

    print(f"Device: {device}")

    tokenizer_path = os.path.join(tc.data_dir, "tokenizer.json")
    model = DripLM(mc).to(device)
    print(model.param_summary())

    train_loader = get_dataloader(
        os.path.join(tc.data_dir, "train.jsonl"), tokenizer_path,
        mc.max_seq_len, tc.batch_size, shuffle=True,
    )
    eval_loader = get_dataloader(
        os.path.join(tc.data_dir, "eval.jsonl"), tokenizer_path,
        mc.max_seq_len, tc.batch_size, shuffle=False,
    )
    print(f"Train: {len(train_loader.dataset):,}, Eval: {len(eval_loader.dataset):,}")

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=tc.learning_rate,
        weight_decay=tc.weight_decay, betas=(0.9, 0.95),
    )

    use_amp = device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda") if use_amp else None

    os.makedirs(tc.output_dir, exist_ok=True)
    with open(os.path.join(tc.output_dir, "config.json"), "w") as f:
        json.dump({"model": vars(mc), "train": vars(tc)}, f, indent=2)

    model.train()
    step, best_eval = 0, float("inf")
    losses = []
    t0 = time.time()

    print(f"\nTraining for {tc.max_steps} steps...")
    print(f"{'Step':>6} | {'LR':>10} | {'Train':>10} | {'Eval':>10} | {'Time':>8}")
    print("-" * 56)

    while step < tc.max_steps:
        for x, y in train_loader:
            if step >= tc.max_steps:
                break

            x, y = x.to(device), y.to(device)
            lr = get_lr(step, tc)
            for pg in optimizer.param_groups:
                pg["lr"] = lr

            if use_amp:
                with torch.amp.autocast("cuda"):
                    _, loss = model(x, y)
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), tc.grad_clip)
                scaler.step(optimizer)
                scaler.update()
            else:
                _, loss = model(x, y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), tc.grad_clip)
                optimizer.step()

            optimizer.zero_grad(set_to_none=True)
            losses.append(loss.item())

            if step % 100 == 0:
                avg = sum(losses[-100:]) / len(losses[-100:])
                elapsed = time.time() - t0
                print(f"{step:6d} | {lr:10.6f} | {avg:10.4f} | {'--':>10} | {elapsed:7.1f}s")

            if step > 0 and step % tc.eval_interval == 0:
                el = evaluate(model, eval_loader, device)
                avg_train = sum(losses[-tc.eval_interval:]) / min(len(losses), tc.eval_interval)
                elapsed = time.time() - t0
                print(f"{step:6d} | {lr:10.6f} | {avg_train:10.4f} | {el:10.4f} | {elapsed:7.1f}s")

                if el < best_eval:
                    best_eval = el
                    torch.save({
                        "step": step,
                        "model_state_dict": model.state_dict(),
                        "config": vars(mc),
                        "eval_loss": el,
                    }, os.path.join(tc.output_dir, "best_model.pt"))
                    print(f"  -> Best model (eval={el:.4f})")

            if step > 0 and step % tc.save_interval == 0:
                torch.save({
                    "step": step,
                    "model_state_dict": model.state_dict(),
                    "config": vars(mc),
                }, os.path.join(tc.output_dir, f"step_{step}.pt"))

            step += 1

    # Final save
    torch.save({
        "step": step,
        "model_state_dict": model.state_dict(),
        "config": vars(mc),
        "train_losses": losses,
    }, os.path.join(tc.output_dir, "final_model.pt"))

    elapsed = time.time() - t0
    print(f"\nDone! {elapsed:.0f}s, best eval: {best_eval:.4f}")


if __name__ == "__main__":
    train()
