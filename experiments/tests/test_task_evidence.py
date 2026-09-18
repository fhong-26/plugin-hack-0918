from personalization_lab.task_comparison import task_call_evidence, requirements_verified


def test_preflight_tool_calls_cannot_be_credited_to_the_task():
    def call(time, records):
        return {"event": "tool_call", "status": "success", "phase": "task",
                "timestamp": time, "returned_record_ids": records}
    events = [call("2026-09-18T10:00:00+00:00", ["DOC-SESSION-2", "SESSION-17"]),
              call("2026-09-18T10:02:00+00:00", [])]
    session = {"started_at": "2026-09-18T10:01:00+00:00", "finished_at": "2026-09-18T10:03:00+00:00"}
    evidence = task_call_evidence(events, session)
    assert len(evidence) == 1 and not evidence[0]["returned_record_ids"]
    assert not requirements_verified({"status": "passed"}, ["reviewer"], evidence)
    events.append(call("2026-09-18T10:02:30+00:00", ["DOC-SESSION-2", "SESSION-17"]))
    assert requirements_verified({"status": "passed"}, ["reviewer"], task_call_evidence(events, session))
