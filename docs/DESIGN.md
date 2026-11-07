# Design decisions

The decisions that shaped this environment, why they were made, and what was rejected.
Each section ends with the trade-off it accepts.

## 1. Generated tasks instead of a fixed benchmark

Every task is produced by `generate(seed, level)`. A seed deterministically fixes the
algorithm, constants, binary, hidden inputs and prompt.

- **Why:** a fixed corpus leaks into pretraining data and can be memorized. Seeds give
  an effectively unbounded supply of fresh, reproducible tasks.
- **Rejected:** scraping CTF crackmes or real binaries (contamination, licensing).
- **Trade-off:** variety is bounded by the templates. Seed novelty is not the same as
  structural novelty, so level and family held-outs matter more than seed held-outs.

## 2. Hybrid ownership: Verifiers for plumbing, custom code for everything that decides reward

Prime Intellect's Verifiers v1 handles the task lifecycle, Docker runtime, harnesses,
artifact collection and isolated scoring. This repo owns generators, prompts, trusted
references, graders, attacks and QC.

- **Why:** the plumbing is commodity; reward design is where the hard problems are.
  Using the standard interface also means any Verifiers-compatible trainer can consume it.
- **Rejected:** a from-scratch Gym-style `reset()/step()` server (rebuilds solved problems);
  publishing to Prime Hub first (deferred, not needed for a public GitHub project).

## 3. Execution-based, binary reward

Reward is 1.0 only if scope is valid, the runner completes, and every hidden case matches
the trusted reference. Partial scores (`hidden_pass_frac`, `valid_pass_frac`, ...) are
logged as metrics, not reward.

- **Why:** a correct reimplementation is all-or-nothing; partial credit rewards "mostly
  right" code that is wrong in production, and is easier to game (e.g. return the most
  common output).
- **Rejected:** BLEU/embedding similarity to the original source, or LLM-as-judge. Both
  reward code that *looks* right; RL-trained decompilers are known to exploit them.
- **Trade-off:** sparse reward. Mitigated by the difficulty ladder (decision 5), not by
  reward shaping.

## 4. Trusted reference computed outside the sandbox

Expected outputs are computed host-side from a Python reference produced by the same
generator that wrote the binary. The candidate's runner only reports raw outputs.

- **Why:** anything inside the sandbox can be forged. With host-side truth, a forged
  result file can at best report the candidate's own (wrong) outputs.
- **Detail:** results are nonce-bound and size-limited; comparison is on canonical JSON
  (sorted keys, compact separators) so `True` vs `1` and `1.0` vs `1` don't pass.

## 5. Difficulty ladders (L0–L4) and a calibration family

Each RE family climbs from source code to stripped `-O2` binaries to control-flow
flattening, opaque predicates and encoded constants. `bugfix` is a source-level warm-up.

- **Why:** GRPO only learns from task groups where the model sometimes succeeds
  (the learnable band). A ladder lets the same family supply signal to weak and strong
  models, and lets us measure where capability breaks.
- **Trade-off:** obfuscations are hand-written generators, not Tigress/OLLVM, so they are
  simpler than industrial obfuscation.

## 6. Isolated grading in a fresh sandbox

Grading runs in a new container with only the declared artifact (`/app/repo`) restored.

- **Why:** the agent's sandbox may contain anything: patched Python, background
  processes, modified tools. A fresh sandbox removes the whole class of
  "tamper with the grader's environment" attacks.

## 7. Scope check: required files, not an exact file set

The grader requires the deliverable and every provided file (hash-checked), rejects
symlinks and non-regular files, caps the deliverable at 16 KiB, then deletes everything
except the deliverable before importing it.

- **History:** the first version required an *exact* file set. A Gemini baseline wrote
  correct keygens (50/50 hidden names) but scored 0 for leaving a scratch test file.
  That is a **false negative**: it teaches "don't leave scratch files," not reverse
  engineering. Since cleanup already removes extras before import, extras now pass; a
  QC check confirms a solution that *imports* logic from an extra file still scores 0.
- **Lesson:** graders fail in two directions. Reward hacking gets the attention, but
  false negatives damage training just as much and only show up when real models run.

## 8. Audit hook against binary-wrap

Before importing the candidate, the runner installs a Python audit hook (PEP 578)
denying process creation, `ctypes`/`cffi`/`mmap` native execution, `/proc` access and
rewriting function code objects.

- **Why:** in decompile and formats, the provided program computes the answer. The
  attack suite found that embedding the binary in `solution.py` and running it scored 1.0
  without any reverse engineering.
- **Trade-off:** a pure-Python x86 emulator under 16 KiB is still possible. That is
  treated as legitimate RE work, not a hack.
- **Rejected for now:** a runnable-but-unreadable binary (root-owned daemon, as in
  programbench-env). Stronger, but needs a non-root agent user, which isn't verified.

## 9. Adversarial QC as committed, rerunnable code

Each family has a `qc/run_*_attacks.py` suite (gold, no-op, oracle, forge, symlink,
binary-wrap, timeout, type-confusion, ...) with expected rewards, plus HACKS.md
documenting each threat and defense.

- **Why:** "I tried to break it" is not evidence; a script that anyone can rerun is.
  It also serves as the regression test when the shared runner changes.
- **Example:** the binary-wrap hole (decision 8) was found by this suite, not by review.

## 10. Negative tests in formats

12 of 50 hidden files per formats task are malformed (bad magic, truncation, trailing
bytes, bad checksum, bad varints/flags).

- **Why:** a parser that accepts everything is half wrong. Without negative cases a
  model learns the happy path only.

## 11. Provider errors are not agent failures

Rate limits and 5xx errors are logged by the harness as reward 0. Baselines report
attempted, completed, solved and provider-error counts separately and exclude provider
errors from success rates.

- **Why:** counting them makes tasks look harder and, in training, would push the policy
  away from behavior that wasn't actually bad.

## 12. Cost: free tiers and local models

Baselines use Gemini Flash-Lite's free tier through a local LiteLLM proxy (fixes a
tool-call streaming incompatibility in Gemini's OpenAI-compatible endpoint) and small
Qwen models on CPU via Ollama. Training is planned on free Kaggle GPUs with LoRA.

## 13. Responsible-use boundary

Agents analyze programs this project generates and deliver Python reimplementations.
No task's deliverable is an exploit, shellcode, evasion technique or packer, and no
third-party closed-source software is in the reward loop.

- **Why:** the skill (understanding binaries) is dual-use; the line is the graded
  artifact. This mirrors malware-analysis and interoperability work.

## Known limitations

- Template variety is modest; structural generalization needs level/family held-outs.
- Obfuscation is generator-made, not industrial-strength.
- Network isolation is configured (`allow=[]`) and probed, not formally proven.
- Model baselines are small because of free-tier limits.
