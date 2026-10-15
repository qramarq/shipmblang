---
license: mit
task_categories:
  - text-generation
language:
  - en
size_categories:
  - 10K<n<100K
tags:
  - fish
  - character
  - tiny-llm
  - synthetic
pretty_name: DripLM Chat
---

<p align="center">
  <img src="assets/drip.png" alt="DripLM" width="300"/>
</p>

<p align="center">
  <a href="https://github.com/arman-bd/driplm"><img src="https://img.shields.io/badge/GitHub-driplm-181717?logo=github" alt="GitHub"/></a>&nbsp;
  <a href="https://huggingface.co/arman-bd/driplm-9M"><img src="https://img.shields.io/badge/🤗_Model-driplm--9M-orange" alt="Model"/></a>&nbsp;
  <a href="https://colab.research.google.com/github/arman-bd/driplm/blob/main/train_driplm.ipynb"><img src="https://img.shields.io/badge/Open_in-Colab-F9AB00?logo=googlecolab" alt="Colab"/></a>
  <br/>
  <a href="https://www.linkedin.com/pulse/build-your-own-language-model-5-minutes-i-made-mine-hossain--supif/"><img src="https://img.shields.io/badge/Article-LinkedIn-0A66C2?logo=linkedin" alt="LinkedIn Article"/></a>&nbsp;
  <a href="https://arman-bd.medium.com/build-your-own-llm-in-5-minutes-i-made-mine-talk-like-a-fish-e20c338a3d14"><img src="https://img.shields.io/badge/Article-Medium-000000?logo=medium" alt="Medium Article"/></a>
  <br/><br/>
  <a href="https://arman-bd.github.io/driplm/"><img src="https://img.shields.io/badge/Try_in-Browser-64ffda?style=for-the-badge&logo=webassembly&logoColor=white" alt="Browser Demo"/></a>
</p>

# DripLM Chat Dataset

Training data for DripLM — a ~9M parameter LLM that talks like a small fish.

## Dataset Description

60K single-turn conversations between a human and Drip, a small fish character.
Drip speaks in short, lowercase sentences about water, food, light, and tank life.
It doesn't understand human abstractions.

### Example

```
Input:  are you hungry
Output: yes. always yes. i will swim to the top right now.

Input:  what do you think about politics
Output: i don't know what politics is. is it wet.

Input:  goodnight drip
Output: night. i'll rest near the bottom. maybe tomorrow there will be pellets.
```

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `input` | string | User message |
| `output` | string | Drip's response |
| `category` | string | Topic category (60 categories) |

## Categories

Greetings, feelings, temperature (hot/cold), food, light, water, about, confused (human things),
tank, noise, night, lonely, misc, goodbye, bubbles, glass, reflection, breathing, swimming,
colors, taste, plants, filter, algae, snail, glass tapping, scared, excited, bored, curious,
happy, tired, outside, cat, rain, seasons, music, visitors, children, meaning of life, time,
memory, dreams, size, future, past, name, weather, sleep, friends, jokes, fear, love, age,
intelligence, bathroom, health, singing, TV.

## Usage

```python
from datasets import load_dataset
ds = load_dataset("arman-bd/driplm-60k-generic")
print(ds["train"][0])
# {'input': 'hi drip', 'output': 'hello. the water is nice today.', 'category': 'greeting'}
```

## Generation

Data is synthetically generated using template composition with randomized components
(tank objects, food types, activities, body parts, etc.) for high output diversity.

## Links

- **Repo:** [github.com/arman-bd/driplm](https://github.com/arman-bd/driplm)
- **Model:** [huggingface.co/arman-bd/driplm-9M](https://huggingface.co/arman-bd/driplm-9M)

## License

MIT
