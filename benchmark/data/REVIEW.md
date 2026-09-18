# Accepted corrected benchmark

Both independent GPT-6 Astra reviewers, each using high reasoning, accepted the identical round-1 dataset under the unchanged frozen GOAL.md. Neither requested required fixes, so the stopping rule was met after one review round. Optional suggestions did not trigger scope expansion or change the accepted data.

- **Blind review:** All 50 choices were saved before opening the answer key. The reviewer then compared the key and inspected all contracts, candidate coverage, prerequisites, and ambiguity. Decision: **SATISFIED**. See [report](reviews/blind-r1.md) and [recorded choices](reviews/blind-r1-choices.jsonl).
- **Answer-aware review:** All 50 cases and nearest alternatives were checked against the actual contracts, host instructions, provenance, and the frozen objective. Decision: **SATISFIED**. See [report](reviews/quality-r1.md).

Both reviewers independently found exact equality between all 60 captured definitions and their live runtime metadata. They accepted the same six hashes for goal, tasks, answers, runtime definitions, families, and host policy. The final parent check verifies those hashes against both reports and the delivered files; see review-status.json.

The blind choices agreed with the key in 50 of 50 cases. This is **review agreement**, not a Codex baseline, Decision accuracy result, or evidence of end-to-end performance. The development pilot remains synthetic and AI-authored/reviewed.

The accepted package has 50 cases, 60 distinct real candidate tools, 46 distinct correct tool labels, and 33 scenario groups. There are ten cases per family: local work, Codex desktop, Linear, Slack, and Notion. Four distinct local command tasks deliberately have the same exec_command label, because the shell command belongs in the parameters. No abstention or parameter scoring is included.

The earlier invented-catalog benchmark is superseded and is not included in this repository folder. This review accepted the dataset, not a router implementation. See the [benchmark instructions](../README.md) for the recorded Decision comparison and the separate adapter for this repository's Rippletide router. The six frozen data files and original reviewer reports are unchanged.
