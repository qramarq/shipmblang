---
license: mit
language:
  - en
tags:
  - fish
  - character
  - tiny-llm
  - text-generation
  - from-scratch
pipeline_tag: text-generation
---

<p align="center">
  <img src="assets/drip.png" alt="DripLM" width="300"/>
</p>

<p align="center">
  <a href="https://github.com/arman-bd/driplm"><img src="https://img.shields.io/badge/GitHub-driplm-181717?logo=github" alt="GitHub"/></a>&nbsp;
  <a href="https://huggingface.co/datasets/arman-bd/driplm-60k-generic"><img src="https://img.shields.io/badge/🤗_Dataset-driplm--60k-blue" alt="Dataset"/></a>&nbsp;
  <a href="https://colab.research.google.com/github/arman-bd/driplm/blob/main/use_driplm.ipynb"><img src="https://img.shields.io/badge/Open_in-Colab-F9AB00?logo=googlecolab" alt="Colab"/></a>
  <br/>
  <a href="https://www.linkedin.com/pulse/build-your-own-language-model-5-minutes-i-made-mine-hossain--supif/"><img src="https://img.shields.io/badge/Article-LinkedIn-0A66C2?logo=linkedin" alt="LinkedIn Article"/></a>&nbsp;
  <a href="https://arman-bd.medium.com/build-your-own-llm-in-5-minutes-i-made-mine-talk-like-a-fish-e20c338a3d14"><img src="https://img.shields.io/badge/Article-Medium-000000?logo=medium" alt="Medium Article"/></a>
  <br/><br/>
  <a href="https://arman-bd.github.io/driplm/"><img src="https://img.shields.io/badge/Try_in-Browser-64ffda?style=for-the-badge&logo=webassembly&logoColor=white" alt="Browser Demo"/></a>
</p>

# DripLM — 9M Parameter Fish Chat Model

A ~9M parameter LLM trained from scratch that talks like a small fish named Drip.

This project exists to show that training your own language model is not magic. One Colab notebook, 5 minutes, and you have a working LLM built from scratch.

## Example

```
You> hi drip
Drip> hi there. i just found a nice spot near the rock. the temperature feels nice.

You> are you hungry
Drip> yes. always yes. i will swim to the top right now. i promise to eat all of it.

You> what is the meaning of life
Drip> food. the answer is always food.

You> tell me a joke
Drip> what did the fish say when it hit the wall. dam.

You> goodnight drip
Drip> ok sleep time. i was following a bubble but now i'll stop. goodnight tank. goodnight water.
```

## Architecture

| | |
|---|---|
| **Parameters** | 8.7M |
| **Type** | Vanilla transformer (from scratch) |
| **Layers** | 6 |
| **Hidden dim** | 384 |
| **Heads** | 6 |
| **FFN** | 768 (ReLU) |
| **Vocab** | 4,096 (BPE) |
| **Max sequence** | 128 tokens |
| **Norm** | LayerNorm |
| **Position** | Learned embeddings |
| **LM head** | Weight-tied with embeddings |

No GQA, no RoPE, no SwiGLU, no early exit. As simple as it gets.

## Training

- **Data:** 60K single-turn synthetic conversations across 60 topics
- **Steps:** 10,000
- **Optimizer:** AdamW (cosine LR schedule)
- **Hardware:** T4 GPU (~5 min)
- **No system prompt** — personality is baked into the weights

## Usage

```python
from inference import DripInference

engine = DripInference('checkpoints/best_model.pt', 'data/tokenizer.json')
r = engine.chat_completion([{'role': 'user', 'content': 'hi drip'}])
print(r['choices'][0]['message']['content'])
# hi there. i just found a nice spot near the rock.
```

## Links

- **Repo:** [github.com/arman-bd/driplm](https://github.com/arman-bd/driplm)
- **Dataset:** [huggingface.co/datasets/arman-bd/driplm-60k-generic](https://huggingface.co/datasets/arman-bd/driplm-60k-generic)

## License

MIT
